"""OTA/WS 鉴权回归；不访问网络、音箱或用户配置。"""

import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

from xiaozhi.services.protocols.websocket_protocol import WebsocketProtocol
from xiaozhi.utils import config as config_module
from xiaozhi.utils.config import ConfigManager


class OTAWebsocketTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.chdir, self.original_cwd)
        self.original_instance = ConfigManager._instance
        ConfigManager._instance = None
        self.addCleanup(setattr, ConfigManager, "_instance", self.original_instance)
        self.settings = {
            "xiaozhi": {
                "OTA_URL": "http://ota.test/xiaozhi/ota/",
                "WEBSOCKET_URL": "ws://configured.test/xiaozhi/v1/",
                "WEBSOCKET_ACCESS_TOKEN": "manual-token",
                "DEVICE_ID": "02:00:00:00:00:01",
                "VERIFICATION_CODE": "",
            }
        }
        self.config_path = Path("config.py")
        self.config_path.write_text("APP_CONFIG = " + json.dumps(self.settings))
        self.settings_patch = patch.object(
            config_module, "APP_CONFIG", copy.deepcopy(self.settings)
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.ip_patch = patch.object(ConfigManager, "get_local_ip", return_value="127.0.0.1")
        self.ip_patch.start()
        self.addCleanup(self.ip_patch.stop)
        self.post_patch = patch.object(config_module.requests, "post")
        self.post = self.post_patch.start()
        self.addCleanup(self.post_patch.stop)

    def respond(self, payload):
        self.post.return_value = Mock(status_code=200)
        self.post.return_value.json.return_value = payload
        self.post.side_effect = None

    def test_websocket_only_ota_uses_matching_identity_and_keeps_token_in_memory(self):
        self.respond({
            "websocket": {"url": "ws://lan.test/xiaozhi/v1/", "token": "ota-token"},
            "activation": {"code": "123456"},
        })
        manager = ConfigManager.instance()
        headers = self.post.call_args.kwargs["headers"]
        self.assertEqual(headers["Client-Id"], manager.get_client_id())
        self.assertEqual(headers["Device-Id"], manager.get_device_id())
        self.assertEqual(manager.get_config("NETWORK.WEBSOCKET_URL"), "ws://lan.test/xiaozhi/v1/")
        self.assertEqual(manager.get_config("NETWORK.WEBSOCKET_ACCESS_TOKEN"), "ota-token")
        self.assertEqual(manager.get_config("NETWORK.VERIFICATION_CODE"), "123456")
        saved = self.config_path.read_text()
        self.assertIn('"VERIFICATION_CODE": "123456"', saved)
        self.assertNotIn("ota-token", saved)
        self.assertIn("manual-token", saved)

    def test_mqtt_only_response_keeps_explicit_websocket_configuration(self):
        self.respond({"mqtt": {"endpoint": "mqtt.test"}})
        manager = ConfigManager.instance()
        self.assertEqual(manager.get_config("MQTT_INFO"), {"endpoint": "mqtt.test"})
        self.assertEqual(manager.get_config("NETWORK.WEBSOCKET_URL"), self.settings["xiaozhi"]["WEBSOCKET_URL"])
        self.assertEqual(manager.get_config("NETWORK.WEBSOCKET_ACCESS_TOKEN"), "manual-token")

    def test_failed_refresh_retains_last_successful_configuration(self):
        self.respond({"websocket": {"token": "last-token"}})
        manager = ConfigManager.instance()
        self.post.side_effect = requests.Timeout()
        self.assertFalse(manager.refresh_network_config())
        self.assertEqual(manager.get_config("NETWORK.WEBSOCKET_ACCESS_TOKEN"), "last-token")
        self.assertEqual(manager.get_config("NETWORK.WEBSOCKET_URL"), self.settings["xiaozhi"]["WEBSOCKET_URL"])

    def test_missing_token_preserves_manual_token_but_empty_token_clears_it(self):
        self.respond({"websocket": {"url": "ws://lan.test/xiaozhi/v1/"}})
        manager = ConfigManager.instance()
        self.assertEqual(manager.get_config("NETWORK.WEBSOCKET_ACCESS_TOKEN"), "manual-token")
        self.respond({"websocket": {"token": ""}})
        self.assertTrue(manager.refresh_network_config())
        self.assertEqual(manager.get_config("NETWORK.WEBSOCKET_ACCESS_TOKEN"), "")

    def test_invalid_response_and_activation_do_not_change_persisted_config(self):
        self.respond({"websocket": {"url": "https://invalid.test"}, "activation": {"code": '"; bad()'}})
        manager = ConfigManager.instance()
        before = self.config_path.read_text()
        self.assertEqual(manager.get_config("NETWORK.WEBSOCKET_URL"), self.settings["xiaozhi"]["WEBSOCKET_URL"])
        self.respond([])
        self.assertFalse(manager.refresh_network_config())
        self.assertEqual(self.config_path.read_text(), before)

    async def test_each_connection_refreshes_off_loop_and_uses_current_token(self):
        self.respond({"websocket": {"token": "initial-token"}})
        manager = ConfigManager.instance()
        protocol = WebsocketProtocol()
        main_thread = threading.get_ident()
        request_threads = []
        handshake_tokens = []

        def ota_response(*args, **kwargs):
            request_threads.append(threading.get_ident())
            self.assertEqual(kwargs["headers"]["Client-Id"], protocol.CLIENT_ID)
            token = "fresh-" + str(len(request_threads))
            result = Mock(status_code=200)
            result.json.return_value = {"websocket": {"url": "ws://fresh.test/", "token": token}}
            return result

        async def connect(*args, **kwargs):
            self.assertEqual(kwargs["uri"], "ws://fresh.test/")
            headers = kwargs["additional_headers"]
            self.assertEqual(headers["Client-Id"], manager.get_client_id())
            self.assertEqual(headers["Device-Id"], manager.get_device_id())
            handshake_tokens.append(headers["Authorization"])
            socket = Mock()
            socket.close = AsyncMock()
            socket.send = AsyncMock()
            return socket

        async def receive_hello():
            await protocol._handle_server_hello({"type": "hello", "transport": "websocket"})

        self.post.side_effect = ota_response
        with patch("xiaozhi.services.protocols.websocket_protocol.websockets.connect", side_effect=connect), patch.object(protocol, "_message_handler", side_effect=receive_hello):
            self.assertTrue(await protocol.connect())
            self.assertTrue(await protocol.connect())
        self.assertEqual(handshake_tokens, ["Bearer fresh-1", "Bearer fresh-2"])
        self.assertTrue(all(identity != main_thread for identity in request_threads))
        await protocol._close_websocket()


if __name__ == "__main__":
    unittest.main()

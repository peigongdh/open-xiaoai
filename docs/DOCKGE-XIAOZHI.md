# Home Lab：Open-XiaoAI 小智桥接

本服务使用 `examples/xiaozhi` 的 Python Server，把小爱音箱接到现有 `xiaozhi-esp32-server`。Ubuntu 运行一个独立 Dockge 栈，实施验收见 [PLAN-001](PLAN-001-dockge-xiaozhi.md)。

## 入口与配置

| 用途 | 地址或路径 |
| --- | --- |
| Dockge 管理 | http://192.168.31.109:5001/compose/open-xiaoai-xiaozhi |
| 音箱 Rust Client 的 Server 地址 | `ws://192.168.31.109:4399` |
| 当前后端 OTA | `http://192.168.31.109:8002/xiaozhi/ota/` |
| 当前后端 WebSocket | `ws://192.168.31.109:8000/xiaozhi/v1/` |
| 智控台及设备绑定 | http://192.168.31.109:8002/ |
| 运行 Compose 与环境 | `/srv/homelab/stacks/managed/open-xiaoai-xiaozhi/{compose.yaml,.env}` |
| 生效的业务配置 | `/srv/homelab/data/open-xiaoai-xiaozhi/config.py` |
| 生成的唤醒词文件 | `/srv/homelab/data/open-xiaoai-xiaozhi/keywords.txt` |
| 验收摘要 | `/srv/homelab/data/open-xiaoai-xiaozhi/deployment-verification.json` |

[Compose 来源](../deploy/xiaozhi/compose.yaml)固定上游镜像摘要，包含 VAD/KWS 模型；运行身份为宿主用户 `1000:1000`，重启策略为 `unless-stopped`。业务配置与唤醒词文件归该用户所有，权限 0600，数据目录 0700。监听只绑定上述 LAN 地址。4399 是单音箱 WebSocket 接口，没有浏览器页面或身份认证；仅供可信局域网使用。

[仓库 config.py](../examples/xiaozhi/config.py)是初始配置来源，已对齐上述 LAN 地址。启动会生成并持久化 `DEVICE_ID`，OTA 激活码写入 `VERIFICATION_CODE`；后续在运行副本调整唤醒词等配置后，通过 Dockge 重启。不要用仓库模板覆盖已有运行配置，否则会丢失设备身份。

## OTA 鉴权兼容

上游镜像忽略 OTA 的 `websocket.token`，且 OTA 未传递与 WebSocket 相同的 `Client-Id`，无法直接接入当前开启鉴权的后端。本仓修复 [配置管理](../examples/xiaozhi/xiaozhi/utils/config.py)与 [WebSocket 连接](../examples/xiaozhi/xiaozhi/services/protocols/websocket_protocol.py)：携带同一身份获取 OTA，在每次连接前在线程中刷新地址及令牌；刷新失败保留现有配置，令牌仅驻留内存。

运行 `.env` 的 `PATCH_ROOT` 指向固定发布目录 `/srv/homelab/releases/open-xiaoai-xiaozhi/ota-auth-022be55512d7`，以只读绑定覆盖镜像中的这两个文件。该目录含 `sha256.json`；运行容器不直接挂载开发检出。升级时先在新目录准备并验证补丁，再更新 `PATCH_ROOT`；更新镜像摘要时须重新确认兼容性，不能直接移除补丁。

隔离回归测试（不访问网络或音箱）：

```sh
docker run --rm --network none --read-only --tmpfs /tmp \
  -v /home/zhangpei/project/open-xiaoai/examples/xiaozhi:/tests-source:ro \
  -w /tmp --entrypoint /app/.venv/bin/python \
  idootop/open-xiaoai-xiaozhi@sha256:02024eb540c7ad204fcc6fab1eb6d52096e7b0f69aabb342a276178bdf04b645 \
  -m unittest discover -s /tests-source/tests -v
```

## 音箱接入与验收边界

音箱须已按 [Rust Client 文档](../packages/client-rust/README.md)安装补丁，`/data/open-xiaoai/server.txt` 填写 `ws://192.168.31.109:4399`。本次没有刷机、修改或登录实体音箱。

服务首次启动会自动连接小智后端；未绑定时返回设备绑定提示。用智控台现有账号登录，为目标智能体绑定运行配置或 Dockge 日志中的当前激活码，并按后端说明配置模型。绑定后重启桥接服务。激活码可能过期，以当次 OTA/日志为准。

容器健康检查读取 4399 的监听状态；Home Manager 的 `open-xiaoai-xiaozhi` 登记使用 TCP 探活，并依赖小智后端 8000 的 HTTP 存活检查。两者不表示实体音箱、模型或实际语音对话已就绪。不要使用周期性 WebSocket 握手探活：它会占用单音箱连接，并触发音箱初始化 RPC。

## 操作与恢复

生命周期统一在 Dockge 执行 Start / Stop / Restart 和查看日志，Home Manager 保留观察与管理链接。重建前确保两个可写文件均已存在且归 `1000:1000` 所有；Compose 不会自动创建缺失的绑定文件。`keywords.txt` 可先创建为空，启动时按配置重新生成。

停止栈保留数据目录、运行 `.env` 及其指向的补丁目录，用相同 Compose 可恢复。配置备份应包含这些文件；本次未接入定时 NAS 备份，也未测试宿主重启。不要清空 `DEVICE_ID`、删除数据目录或执行全局 prune 排障。

如果后端在桥接启动时不可用，原上游逻辑可能不会自动重新建立首次连接；待后端恢复后在 Dockge 重启桥接栈。修改模型或绑定设备后也可通过该入口重新连接。

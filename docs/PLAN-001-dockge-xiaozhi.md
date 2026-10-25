# PLAN-001：Open-XiaoAI 小智桥接服务部署

2026-10-25，用户授权参考 `examples/xiaozhi/README.md`，在现有 Dockge 部署 `open-xiaoai-xiaozhi`，对齐当前小智后端的 LAN 地址。

## 范围与验收

在 Ubuntu 新建独立 Dockge 栈，使用上游镜像固定摘要；运行配置和设备身份独立持久化。验证进程健康、4399 接入、OTA 与鉴权 WebSocket、Dockge 纳管和 Home Manager 观察登记。实体音箱补丁安装、模型账户配置与实际语音对话需对应设备及用户配置，不以端口可达代替。

## 实施结果

已于 2026-10-25 14:40（Asia/Shanghai）完成服务部署范围。

1. 本仓开始时干净；相邻 `xiaozhi-esp32-server` 仓库已有的部署修改保持原状。核对真实后端 OTA `http://192.168.31.109:8002/xiaozhi/ota/`、WebSocket `ws://192.168.31.109:8000/xiaozhi/v1/`，修改本仓配置并建立独立运行副本。
2. 修复 OTA 与 WS 使用相同 `Client-Id`，读取并在连接前刷新 OTA 令牌，不落盘。固定上游镜像内隔离执行 6 项回归测试全部通过；镜像原始两文件与本仓原版一致，修复以固定发布副本只读挂载。Compose 和业务配置来源见 [运行说明](DOCKGE-XIAOZHI.md)。
3. 通过 Dockge 认证 `deployStack` 接口部署，最终以非 root `1000:1000` 运行、禁用全部 capabilities；配置和生成的唤醒词单独挂载并可写。容器 healthy，监听 `192.168.31.109:4399`，Dockge 回读 `managed=true/status=3`。实际 `restartStack` 后再次 healthy，设备身份保持，配置权限 0600，唤醒词已生成。
4. 从新容器验证 LAN OTA、无令牌 WS 拒绝、OTA 令牌认证后的 WS ping/pong；重启后复验通过。主应用启动收到真实设备绑定提示。验证探针未发送应用消息、音频或模型请求；应用本身启动 hello 会触发后端绑定提示。
5. Home Manager 完整候选经正式 API 校验后单项保存并回读，57 项增至 58 项，其余登记和全局配置不变。新服务 TCP 探活和后端 HTTP 依赖均 healthy，无需重启 Home Manager。
6. 核对原有 27 个运行容器的 ID、启动时间和重启次数均保持。没有改动小智后端部署、模型配置或实体音箱。变更未提交或推送。

私有验收摘要：`/srv/homelab/data/open-xiaoai-xiaozhi/deployment-verification.json`。实体音箱补丁、设备绑定、模型配置及实际语音对话未验证，接入步骤见运行说明；这些不作为容器健康的已完成保证。本次未接入定时 NAS 备份，未测试宿主重启。

## 恢复边界

仅创建和管理 `open-xiaoai-xiaozhi` 栈，停止时保留配置与设备身份；不执行卷删除、全局 prune 或更改既有小智后端。运行配置、令牌及私有验收材料不入库。生命周期由 Dockge 统一管理。

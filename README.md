# AstrBot maimai 水鱼更新器

这是一个独立 AstrBot 插件，用于把舞萌 DX 官方机台成绩同步到水鱼查分器。

## 功能

- `/maimai_bind` / `舞萌绑定` / `水鱼绑定`：等待用户发送官方二维码识别出的 `SGWCMAID/SGID` 文本，解析并保存可复用的机台凭据。
- `/maimai_token <Import-Token>` / `水鱼token`：保存水鱼 Import-Token。
- `/maimai_update` / `更新水鱼` / `更新b50`：从机台数据源拉取成绩并更新到水鱼。
- `/maimai_status` / `水鱼状态`：查看绑定与最近同步状态，Token 只脱敏展示。
- `/maimai_unbind` / `水鱼解绑`：删除当前用户保存的凭据。

群聊中收到 SGID 或 Token 后会尽量自动撤回并阻止继续分发；私聊不会撤回。

## Windows x64 依赖

当前按 Python 3.13 + Windows x64 固定 `maimai-py==1.1.0`，因为该组合可解析到可用的 `maimai-ffi` wheel。

## 数据

插件数据保存到 AstrBot 标准插件数据目录下的 `users.json`。按本项目需求，数据明文保存；日志不会输出完整 SGID、Import-Token 或机台凭据。


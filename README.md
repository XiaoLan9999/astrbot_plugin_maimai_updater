# AstrBot maimai 水鱼更新器

这是一个独立 AstrBot 插件，用于把舞萌 DX 官方机台成绩同步到水鱼查分器。

## 功能

- `/maimai_bind` / `舞萌绑定` / `水鱼绑定`：等待用户发送官方二维码识别出的 `SGWCMAID/SGID` 文本，解析并保存可复用的机台凭据。
- `/maimai_token <Import-Token>` / `水鱼token`：保存水鱼 Import-Token。
- `/maimai_update` / `更新水鱼` / `更新b50`：从机台数据源拉取成绩并更新到水鱼。
- `/maimai_status` / `水鱼状态`：查看绑定与最近同步状态，Token 只脱敏展示。
- `/maimai_unbind` / `水鱼解绑`：删除当前用户保存的凭据。

群聊中收到 SGID 或 Token 后会尽量自动撤回并阻止继续分发（有管理员权限）；私聊不会撤回。

## 运行环境

插件代码本身没有固定操作系统要求，只要 AstrBot 和依赖能正常安装即可。实际部署时需要注意的是：

- Python 需要满足 `maimai-py` 的要求；当前依赖版本要求 Python `>=3.10,<4.0`。
- 读取官方机台数据依赖 `maimai-ffi`，它是二进制 wheel；你的系统、CPU 架构和 Python 版本必须有对应 wheel。
- 本仓库的 `requirements.txt` 固定 `maimai-py==1.1.0`，这是为了让 Windows x64 + Python 3.13 环境能稳定安装到可用的 `maimai-ffi` wheel，并不是插件只支持 Windows。
- 如果你在 Linux/Docker 或其它 Python 版本部署，优先直接安装 `requirements.txt`；如果 `maimai-ffi` 安装失败，请调整 Python 版本，或根据 `maimai-ffi`/`maimai-py` 当前 wheel 支持情况选择匹配版本。

## 数据

插件数据保存到 AstrBot 标准插件数据目录下的 `users.json`。本项目的数据是明文保存；日志不会输出完整 SGID、Import-Token 或机台凭据。

## 排障

如果绑定时报 `SyntaxError`、`maimai-py/maimai-ffi 依赖导入失败`，通常是 AstrBot 运行环境里的依赖版本冲突或安装残留。进入 AstrBot 使用的 Python 环境后，在插件目录执行：

```bash
python -m pip uninstall -y maimai-py maimai-ffi maimai_py
python -m pip install --no-cache-dir -r requirements.txt
```

如果群聊敏感消息撤回失败，请检查 Bot 是否有撤回/管理消息权限。插件会在日志里输出撤回失败 traceback，便于判断是权限、message_id，还是平台适配器不支持。

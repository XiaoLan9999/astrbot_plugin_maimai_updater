# AstrBot maimai 水鱼更新器

这是一个独立 AstrBot 插件，用于把舞萌 DX 官方机台成绩同步到水鱼查分器。

## 功能

- `/maimai_bind` / `舞萌绑定` / `水鱼绑定`：等待用户发送官方二维码识别出的 `SGWCMAID/SGID` 文本，只验证本次二维码能否解析，不保存 SGID 或官方临时凭据。
- `/maimai_token <Import-Token>` / `水鱼token`：保存水鱼 Import-Token。
- `/maimai_update` / `更新水鱼` / `更新b50`：要求用户再次发送本次操作用的 `SGWCMAID/SGID`，从机台数据源拉取成绩并更新到水鱼。
- `/maimai_status` / `水鱼状态`：查看水鱼 Token、最近验证、最近同步状态，Token 只脱敏展示。
- `/maimai_unbind` / `水鱼解绑`：删除当前用户保存的水鱼 Token 和本地展示状态。

群聊中收到 SGID 或 Token 后会尽量自动撤回并阻止继续分发（需要 Bot 有撤回/管理消息权限）；私聊不会撤回。插件会单独发送“已尝试撤回消息，如果没撤回请手动撤回”的安全提示，不会把撤回提示粘在绑定结果里。

## 重要说明

舞萌官方二维码识别出的 SGID 以及 maimai.py 解析出的官方临时凭据都不适合作为长期凭据保存。它们用于本次机台登录/查询链路，复用可能失败，也可能影响玩家在机台正常登录。

因此本插件只持久化水鱼 Import-Token 和展示用状态，不持久化 SGID，也不持久化 `arcade_credentials`。每次执行 `/maimai_update` 都需要用户重新提供一次新的官方二维码识别文本。

`/maimai_bind` 不会读取玩家名/Rating，因为当前 maimai.py 的官方玩家资料预览接口可能已和华立标题服返回格式不兼容。玩家名只会在更新流程中尽量从官方/机台数据源读取；插件不会从水鱼反查玩家名。Rating 会优先使用官方玩家资料里的数值，读不到时使用本次官方成绩计算出的 B50 Rating。

## 运行环境

插件代码本身没有固定操作系统要求，只要 AstrBot 和依赖能正常安装即可。实际部署时需要注意的是：

- Python 需要满足 `maimai-py` 的要求；当前依赖版本要求 Python `>=3.9,<4.0`。
- 读取官方机台数据依赖 `maimai-ffi`，它是二进制 wheel；你的系统、CPU 架构和 Python 版本必须有对应 wheel。
- 本仓库的 `requirements.txt` 固定 `maimai-py==1.4.2`，该版本依赖 `maimai-ffi==0.7.0`。
- 已确认 `maimai-ffi==0.7.0` 可为 Windows x64 + Python 3.10 下载到 `maimai_ffi-0.7.0-cp310-cp310-win_amd64` wheel。
- 如果你在 Linux/Docker 或其它 Python 版本部署，优先直接安装 `requirements.txt`；如果 `maimai-ffi` 安装失败，请调整 Python 版本，或根据 `maimai-ffi`/`maimai-py` 当前 wheel 支持情况选择匹配版本。

## 数据

插件数据保存到 AstrBot 标准插件数据目录下的 `users.json`。本项目的数据是明文保存；日志不会输出完整 SGID、Import-Token 或官方临时凭据。

`users.json` 只保存：

- `player_name`
- `rating`
- `divingfish_import_token`
- `bound_at`
- `last_sync_at`
- `last_sync_result`

如果旧版本数据里存在 `arcade_credentials`，插件读取时会忽略，下一次保存会自动移除。

## 排障

如果绑定时报 `SyntaxError`、`maimai-py/maimai-ffi 依赖导入失败`，通常是 AstrBot 运行环境里的依赖版本冲突或安装残留。进入 AstrBot 使用的 Python 环境后，在插件目录执行：

```bash
python -m pip uninstall -y maimai-py maimai-ffi maimai_py
python -m pip install --no-cache-dir -r requirements.txt
```

也可以手动安装核心依赖：

```bash
python -m pip install --no-cache-dir "maimai-py==1.4.2" "httpx>=0.28.0,<0.29.0"
```

### Windows 提示 `[WinError 5] 拒绝访问 arcade.cp310-win_amd64.pyd`

这是 Windows 正在锁定 `maimai_ffi` 的二进制扩展文件，通常是因为 AstrBot 当前进程已经加载过 `maimai_ffi`。不要在 AstrBot 运行中覆盖安装这个依赖。

处理方式：

1. 完全关闭 AstrBot Launcher 和所有 AstrBot/Python 进程。
2. 打开一个新的 PowerShell。
3. 使用 AstrBot 同一个 Python 执行：

```powershell
python -m pip uninstall -y maimai-py maimai-ffi maimai_py
python -m pip install --no-cache-dir "maimai-py==1.4.2" "httpx>=0.28.0,<0.29.0"
```

4. 重新启动 AstrBot，再安装或重载插件。

如果群聊敏感消息撤回失败，请检查 Bot 是否有撤回/管理消息权限。插件会在日志里记录一行撤回失败原因，不会输出完整 SGID 或 Token。

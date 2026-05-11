# AstrBot maimai 水鱼更新器

这是一个独立 AstrBot 插件，用一次性的舞萌 DX 官方二维码识别文本 `SGWCMAID/SGID`，把机台成绩同步到水鱼查分器。

![maimai 水鱼更新流程](assets/maimai-updater-flow.png)

## 功能

- `maimaitoken <Import-Token>` / `水鱼token`：保存用户自己的水鱼 Import-Token。
- `水鱼更新 SGWCMAID...`：用这次官方二维码拉取成绩并更新水鱼。
- `maimaiupdate <SGID>` / `更新水鱼` / `更新b50`：等价的 AstrBot 命令触发方式。
- `maimaiclear 确认清空` / `清空水鱼 确认清空`：向水鱼发送清空成绩请求，用于误用他人 SGID 后手动处理。
- `maimaistatus` / `水鱼状态`：查看 token 绑定状态、最近同步结果和当前 SGID 触发方式。
- `maimaiunbind` / `水鱼解绑`：删除当前用户保存的水鱼 Token 和本地展示状态。

命令名已去除下划线。插件不再提供 `maimai_bind`，因为官方 SGID 只适合一次性使用，每次更新都需要用户重新提供新的二维码识别文本。

## SGID 更新触发

插件不会响应裸 `SGWCMAID...`，避免误触发或和其它插件冲突。默认用法是：

```text
水鱼更新 SGWCMAID...
```

插件配置里可以调整：

- `enable_text_update_trigger`：开启/关闭“水鱼更新 SGID”这种普通文本触发。
- `text_update_command`：修改文本触发词，默认是 `水鱼更新`。

如果关闭文本触发，仍可使用 AstrBot 命令 `maimaiupdate <SGID>`。

## 安全说明

舞萌官方二维码识别出的 SGID，以及 maimai.py 解析出的官方临时凭据，都不适合长期保存。复用旧 SGID 可能失败，也可能影响玩家在机台正常登录。

因此本插件只持久化水鱼 Import-Token 和展示状态，不持久化 SGID，也不持久化 `arcade_credentials`。插件会校验 SGID 内嵌时间戳，默认只接受 180 秒内生成的 SGID；同一条 SGID 在插件进程内也只允许使用一次。

群聊中收到 SGID 或 Token 后，插件会尝试撤回原消息，并单独发送“已尝试撤回消息，如果没撤回请手动撤回”。私聊不会撤回。

## 玩家名说明

玩家名只能从官方/机台数据源读取，插件不会从水鱼反查玩家名。当前 maimai.py 的新版机台成绩链路可以同步成绩，但玩家资料预览能力受华立标题服接口变化影响，可能无法返回玩家名。读不到玩家名时，更新仍会继续，Rating 会尽量使用本次官方成绩链路返回的值。

## 运行环境

插件代码本身没有固定操作系统要求，只要 AstrBot 和依赖能正常安装即可。实际部署时需要注意：

- Python 需要满足 `maimai-py` 的要求；当前依赖版本要求 Python `>=3.9,<4.0`。
- 读取官方机台数据依赖 `maimai-ffi`，它是二进制 wheel；系统、CPU 架构和 Python 版本必须有对应 wheel。
- 本仓库的 `requirements.txt` 固定 `maimai-py==1.4.2`，该版本依赖 `maimai-ffi==0.7.0`。
- 已确认 Windows x64 + Python 3.10 可下载 `maimai_ffi-0.7.0-cp310-cp310-win_amd64` wheel。

如果网络无法解析华立标题服域名，可以在 Windows hosts 中加入：

```text
43.137.89.146 wq.sys-all.cn
43.137.89.146 ai.sys-all.cn
43.137.89.146 wi.sys-all.cn
43.137.89.146 at.sys-all.cn
```

## 数据

插件数据保存到 AstrBot 标准插件数据目录下的 `users.json`，明文保存。日志不会输出完整 SGID、Import-Token 或官方临时凭据。

`users.json` 只保存：

- `player_name`
- `rating`
- `divingfish_import_token`
- `bound_at`
- `last_sync_at`
- `last_sync_result`

如果旧版本数据里存在 `arcade_credentials`，插件读取时会忽略，下一次保存会自动移除。

## 排障

如果安装或更新依赖时报 `SyntaxError`、`maimai-py/maimai-ffi 依赖导入失败`，通常是 AstrBot 运行环境里的依赖版本冲突或安装残留。进入 AstrBot 使用的 Python 环境后，在插件目录执行：

```bash
python -m pip uninstall -y maimai-py maimai-ffi maimai_py
python -m pip install --no-cache-dir -r requirements.txt
```

也可以手动安装核心依赖：

```bash
python -m pip install --no-cache-dir "maimai-py==1.4.2" "httpx>=0.28.0,<0.29.0"
```

检查当前 Python 中实际安装版本：

```powershell
python -c "import importlib.metadata as m; print('maimai-py', m.version('maimai-py')); print('maimai-ffi', m.version('maimai-ffi'))"
```

### Windows 提示 `[WinError 5] 拒绝访问 arcade.cp310-win_amd64.pyd`

这是 Windows 正在锁定 `maimai_ffi` 的二进制扩展文件，通常因为 AstrBot 进程已经加载过它。不要在 AstrBot 运行中覆盖安装这个依赖。

处理方式：

1. 完全关闭 AstrBot Launcher 和所有 AstrBot/Python 进程。
2. 打开新的 PowerShell。
3. 使用 AstrBot 同一个 Python 执行：

```powershell
python -m pip uninstall -y maimai-py maimai-ffi maimai_py
python -m pip install --no-cache-dir "maimai-py==1.4.2" "httpx>=0.28.0,<0.29.0"
```

4. 重新启动 AstrBot，再安装或重载插件。

如果群聊敏感消息撤回失败，请检查 Bot 是否有撤回/管理消息权限。插件会在日志里记录一行撤回失败原因，不会输出完整 SGID 或 Token。

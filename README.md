# AstrBot maimai 水鱼更新器

这是一个独立的 AstrBot 插件，用一次性的舞萌 DX 官方二维码识别文本 `SGWCMAID/SGID`，把官方成绩同步到水鱼查分器。

![maimai 水鱼更新流程](assets/maimai-updater-flow.png)


## 更新日志

### v0.6.1

- 新增面板配置 `score_source_mode`，可选择 `official_only`、`official_then_arcade`、`arcade`。
- 默认使用 `official_only`，未配置官包 DLL 或标题服务器 base URL 时直接提示配置缺失，不再静默回退到缺少 FC/FS/AP 的基础链路。
- `/水鱼状态` 会显示当前成绩来源模式。
- 更新 README 中的官方完整成绩链路说明。

### v0.6.0

- 加入实验性官包接口链路，尝试通过一次性 SGID 拉取 `UserMusic/GetUserRating`。
- 将 `comboStatus/syncStatus` 映射为水鱼可识别的 FC/FCP/AP/APP 与 SYNC/FS/FSP/FSD/FSDP。

### v0.5.2

- 修复 MAIMAI2026 新版本下 Rating 仍按旧版本拆分的问题。

### v0.5.1

- 修复关闭唤醒前缀后，中文免前缀命令未完整触发的问题。

## 功能

- `maimaitoken <Import-Token>` / `水鱼绑定 <Import-Token>` / `绑定水鱼 <Import-Token>`：保存用户自己的水鱼 Import-Token。
- `maimaiupdate <SGID>` / `更新水鱼 <SGID>` / `水鱼更新 <SGID>` / `更新b50 <SGID>`：使用本次官方 SGID 更新水鱼成绩。
- `maimaiclear 确认清空` / `清空水鱼 确认清空` / `清空b50 确认清空`：向水鱼发送清空成绩请求，用于误用他人 SGID 后手动处理。
- `maimaistatus` / `水鱼状态`：查看 token 绑定状态、最近同步结果和当前命令触发方式。
- `maimaiunbind` / `水鱼解绑`：删除当前用户保存的水鱼 Token 和本地展示状态。

插件不再提供 `maimai_bind`。官方 SGID 只适合一次性使用，每次更新都需要用户重新提供新的二维码识别文本。

## 命令触发

插件不会响应裸 `SGWCMAID...`，避免误触发或和其它插件冲突。

默认开启 `require_command_prefix`，插件只响应 AstrBot 标准命令触发。实际前缀取决于你的 Bot 配置，例如：

```text
/水鱼状态
/水鱼绑定 <Import-Token>
/更新水鱼 SGWCMAID...
```

如果在面板关闭 `require_command_prefix`，本插件所有命令都可以不带 Bot 唤醒前缀直接发送：

```text
水鱼状态
水鱼绑定 <Import-Token>
绑定水鱼 <Import-Token>
更新水鱼 SGWCMAID...
水鱼更新 SGWCMAID...
清空b50 确认清空
水鱼解绑
```

关闭该开关只影响本插件命令，不会让裸 `SGWCMAID...` 自动更新。

## 完整成绩链路

面板里的 `score_source_mode` 用来选择成绩来源。推荐保持默认的 `official_only`：插件会使用你在面板里配置的官包 `chimelib_dll.dll` 和标题服务器接口，通过一次性 SGID 拉取 `UserMusic/GetUserRating`，再把 FC/FS/AP 等特殊标识一并导入水鱼。

可选模式：

- `official_only`：只使用官方完整成绩链路。没有填写官包 DLL 或标题服务器 base URL 时会直接报错，不会静默回退到缺少 FC/FS/AP 的基础链路。
- `official_then_arcade`：未配置官方链路时才使用 maimai-py 基础链路；如果官方链路已经配置但请求失败，不会复用同一条 SGID 强行回退。
- `arcade`：只使用 maimai-py ArcadeProvider 基础链路。它能更新基础成绩和 Rating，但不会返回 FC/FS/AP 等特殊标识。

从 `v0.6.1` 开始，官方完整成绩链路会执行这些步骤：

1. 用官包 `ChimeLib.NET/chimelib_dll.dll` 的 `CCommGetUserData` 逻辑把一次性 SGID 换成本次 `userId + token`。
2. 按官包 `Assembly-CSharp.dll` 中的标题服协议请求 `GetUserPreviewApi`、`UserLoginApi`、`GetUserMusicApi`、`GetUserRatingApi`。
3. 将 `UserMusicDetail.comboStatus/syncStatus` 映射为水鱼可识别的 FC/FCP/AP/APP 与 SYNC/FS/FSP/FSD/FSDP，再导入水鱼。

要使用官方完整成绩链路，需要在插件配置里填写：

- `score_source_mode`: 推荐 `official_only`。
- `official_chimelib_dll_path`: 官包中的 `Package\Sinmai_Data\Plugins\chimelib_dll.dll` 绝对路径。
- `official_title_base_url`: 标题服务器完整 base URL，通常是 AllNet 返回的 `GameServerUri`，应以 `/` 结尾。
- `official_keychip_id`: Keychip ID，例如官包 `segatools.ini` 里的 `A63E-01E11890000`。
- `official_client_id`: 可留空，留空时使用 `official_keychip_id`。
- `official_region_id`: 中国大陆通常为 `8`。
- `official_place_id`: 不确定时先填 `0`，按实测日志调整。
- `official_server_url_index`: 默认 `0`。

`enable_official_protocol` 是旧版配置兼容项。新安装或新调整时优先使用 `score_source_mode`。

插件不会自带、上传或重新分发官包 DLL，也不会执行游戏主程序。开启官方完整成绩链路后，只会在收到用户 SGID 时调用你配置的 `chimelib_dll.dll` 解析本次会话。

## 安全说明

舞萌官方二维码识别出的 SGID，以及由它解析出的本次临时会话，都不适合长期保存。复用旧 SGID 可能失败，也可能影响玩家正常登录。

因此插件只持久化水鱼 Import-Token 和展示状态，不持久化 SGID，也不持久化旧版使用过的 `arcade_credentials`。插件会校验 SGID 内嵌时间戳，默认只接受 180 秒内生成的 SGID；同一条 SGID 在插件进程内也只允许使用一次。

群聊中收到 SGID 或 Token 后，插件会尝试撤回原消息，并单独发送“已尝试撤回消息，如果没撤回请手动撤回”的安全提示。私聊不会撤回。

## 玩家名说明

默认 maimai-py 基础链路不会从水鱼反查玩家名，也不会在更新结果里展示玩家名。开启官方完整链路后，如果 `GetUserPreviewApi` 成功返回玩家名，插件只在内部结果中保留本次返回值；当前更新完成提示仍以 Rating、成绩数、特殊标识数量为主，避免在群聊暴露身份信息。

## 运行环境

插件代码本身没有固定操作系统要求，只要 AstrBot 和依赖能正常安装即可。需要注意：

- Python 需要满足 `maimai-py` 的要求，当前依赖版本要求 Python `>=3.9,<4.0`。
- `requirements.txt` 固定 `maimai-py==1.5.1`，并显式依赖 `httpx` 与 `cryptography`。
- `maimai-py==1.5.1` 依赖 `maimai-ffi==0.7.0`。
- 官方完整成绩链路的 `chimelib_dll.dll` 调用仅适用于 Windows x64 环境；其它系统请将 `score_source_mode` 设为 `arcade`。

## 数据

插件数据保存到 AstrBot 标准插件数据目录下的 `users.json`，明文保存。日志不会输出完整 SGID、Import-Token 或官方临时会话。

`users.json` 只保存：

- `rating`
- `divingfish_import_token`
- `bound_at`
- `last_sync_at`
- `last_sync_result`

如果旧版本数据里存在 `arcade_credentials`，插件读取时会忽略，下一次保存会自动移除。

## 排障

如果安装或更新依赖时出现 `SyntaxError`、`maimai-py/maimai-ffi 依赖导入失败`，通常是 AstrBot 运行环境里的依赖版本冲突或安装残留。进入 AstrBot 使用的 Python 环境后，在插件目录执行：

```bash
python -m pip uninstall -y maimai-py maimai-ffi maimai_py
python -m pip install --no-cache-dir -r requirements.txt
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
python -m pip install --no-cache-dir "maimai-py==1.5.1" "httpx>=0.28.0,<0.29.0" "cryptography>=38.0"
```

4. 重新启动 AstrBot，再安装或重载插件。

如果选择 `official_only` 后仍没有 FC/FS/AP，请检查：

- `official_chimelib_dll_path` 是否指向真实存在的 `chimelib_dll.dll`。
- `official_title_base_url` 是否是当前可用标题服务器 base URL。
- Bot 所在机器是否能访问标题服务器。
- 日志里是否有 `official chime session failed` 或 `official title API ... failed`。

如果群聊敏感消息撤回失败，请检查 Bot 是否有撤回/管理消息权限。插件只会记录一行撤回失败原因，不会输出完整 SGID 或 Token。

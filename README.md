# AstrBot maimai 水鱼更新器

这是一个独立的 AstrBot 插件，用一次性的舞萌 DX 官方二维码识别文本 `SGWCMAID/SGID`，把成绩同步到水鱼查分器。

![maimai 水鱼更新流程](assets/maimai-updater-flow.png)

## 更新日志

### v0.6.5

- 修复标题服 404：官方完整成绩请求改为直接复用 `maimai-ffi.request` 层，由 ffi 构造 Wahlap GM 标题服 URL、API hash、`Mai-Encoding` 与加密载荷。
- 移除运行时对 `wq/ai/wi/at.sys-all.cn` 与 `43.137.89.146` Host-header 候选的依赖，避免错误入口返回 404。
- 优化 maimai-ffi 标题服异常的用户提示。

### v0.6.4

- 修复官方 userId 获取：不再尝试截获 maimai-ffi 的 Fernet 明文，改为复用 ffi 本地解析后的 `GetUserRivalMusicApi` payload 捕获 `userId`，不会发出这次探针请求。
- 标准 AstrBot 命令路径在识别到 Token/SGID 后立即 `stop_event()`，避免敏感内容继续进入 LLM 或其它监听插件。

### v0.6.3

- 默认更新链路改为官包确认出的官方完整成绩链路：本次 SGID -> 官方 userId -> `GetUserMusicApi` / `GetUserRatingApi` -> 水鱼导入。
- 成功时会从官方 `comboStatus` / `syncStatus` 转换并导入 FC、AP、FS、FSD 等特殊标识。
- 通过 `maimai-ffi.request` 复用 Wahlap GM 标题服请求层，不在面板暴露 MAI ID、Keychip、placeId、serverURLIndex 等官包内部字段。
- 仍然不保存 SGID、官方 userId/token 或 MAI 临时会话；每次更新都必须重新提供一次新的 SGID。

### v0.6.2

- 收敛插件面板配置，移除实验性官包链路的内部参数项，避免用户误以为需要填写或保存 MAI/Keychip/官方临时凭据。
- 保持原有使用方式：绑定水鱼 Import-Token 后，每次通过 `更新水鱼 SGWCMAID...` 提供一次性 SGID 更新。
- 明确说明插件不会保存 SGID、MAI 临时会话、官方 userId/token 或旧版 `arcade_credentials`。
- pack 包仅用于确认官包链路和后续优化方向，不作为普通用户运行时配置项。

### v0.6.1

- 更新到 `maimai-py==1.5.1` / `maimai-ffi==0.7.0`。
- 修正 MAIMAI2026 新版本下 Rating 仍按旧版本拆分的问题。
- 保留一次性 SGID 更新语义，不恢复 `maimai_bind` 长期绑定流程。

### v0.5.1

- 修复关闭唤醒前缀后，中文免前缀命令未完整触发的问题。

## 功能

- `maimaitoken <Import-Token>` / `水鱼绑定 <Import-Token>` / `绑定水鱼 <Import-Token>`：保存用户自己的水鱼 Import-Token。
- `maimaiupdate <SGID>` / `更新水鱼 <SGID>` / `水鱼更新 <SGID>` / `更新b50 <SGID>`：使用本次官方 SGID 更新水鱼成绩。
- `maimaiclear 确认清空` / `清空水鱼 确认清空` / `清空b50 确认清空`：向水鱼发送清空成绩请求，用于误用他人 SGID 后手动处理。
- `maimaistatus` / `水鱼状态`：查看 token 绑定状态、最近同步结果和当前命令触发方式。
- `maimaiunbind` / `水鱼解绑`：删除当前用户保存的水鱼 Token 和本地展示状态。

插件不提供 `maimai_bind`。官方 SGID 只适合一次性使用，每次更新都需要用户重新提供新的二维码识别文本。

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

## 数据链路说明

当前正式功能保持简单稳定：

1. 用户先绑定自己的水鱼 Import-Token。
2. 用户每次从官方二维码识别出新的 `SGWCMAID...` 文本。
3. 用户发送 `更新水鱼 SGWCMAID...`。
4. 插件立即尝试撤回群聊中的 SGID 消息。
5. 插件用本次 SGID 当场解析官方 userId，然后请求官包确认出的 `Maimai2Servlet/GetUserMusicApi` 与 `GetUserRatingApi` 拉取完整成绩并同步到水鱼。

SGID、MAI 临时会话、官方 userId/token 都是一次性信息。插件不会保存这些内容，也不会要求用户在面板里填写 MAI ID、Keychip ID、placeId、serverURLIndex 等官包内部字段。

我用你提供的 pack 包确认过官包内存在 `GetUserPreviewApi`、`GetUserMusicApi`、`GetUserRatingApi`、`Maimai2Servlet/` 等链路。插件现在通过 `maimai-ffi.request` 复用 Wahlap GM 标题服请求层，并把官方 `comboStatus` / `syncStatus` 转换为水鱼可识别的 FC/FS/AP 等标识；普通用户不需要手动填写官包内部配置。

## 安全说明

舞萌官方二维码识别出的 SGID，以及由它解析出的本次临时会话，都不适合长期保存。复用旧 SGID 可能失败，也可能影响玩家正常登录。

因此插件只持久化水鱼 Import-Token 和展示状态，不持久化 SGID，也不持久化旧版本使用过的 `arcade_credentials`。插件会校验 SGID 内嵌时间戳，默认只接受 180 秒内生成的 SGID；同一条 SGID 在插件进程内也只允许使用一次。

群聊中收到 SGID 或 Token 后，插件会尝试撤回原消息，并单独发送“已尝试撤回消息，如果没撤回请手动撤回”的安全提示。私聊不会撤回。

## 运行环境

插件代码本身没有固定操作系统要求，只要 AstrBot 和依赖能正常安装即可。需要注意：

- Python 需要满足 `maimai-py` 的要求，当前依赖版本要求 Python `>=3.9,<4.0`。
- `requirements.txt` 固定 `maimai-py==1.5.1`，并显式依赖 `httpx` 与 `cryptography`。
- `maimai-py==1.5.1` 依赖 `maimai-ffi==0.7.0`。

## 数据

插件数据保存到 AstrBot 标准插件数据目录下的 `users.json`，明文保存。日志不会输出完整 SGID 或 Import-Token。

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

如果群聊敏感消息撤回失败，请检查 Bot 是否拥有撤回/管理消息权限。插件只会记录一行撤回失败原因，不会输出完整 SGID 或 Token。

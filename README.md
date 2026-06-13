# AstrBot maimai 水鱼更新器

这是一个独立 AstrBot 插件，用一次性的舞萌 DX 官方二维码识别文本 `SGWCMAID/SGID`，把官方成绩同步到水鱼查分器。

![maimai 水鱼更新流程](assets/maimai-updater-flow.png)

## 功能

- `maimaitoken <Import-Token>` / `水鱼绑定` / `绑定水鱼`：保存用户自己的水鱼 Import-Token。
- `maimaiupdate <SGID>` / `更新水鱼` / `水鱼更新` / `更新b50`：使用本次官方 SGID 更新水鱼成绩。
- `maimaiclear 确认清空` / `清空水鱼 确认清空` / `清空b50 确认清空`：向水鱼发送清空成绩请求，用于误用他人 SGID 后手动处理。
- `maimaistatus` / `水鱼状态`：查看 token 绑定状态、最近同步结果和当前更新触发方式。
- `maimaiunbind` / `水鱼解绑`：删除当前用户保存的水鱼 Token 和本地展示状态。

命令名已去除下划线。插件不再提供 `maimai_bind`，因为官方 SGID 只适合一次性使用，每次更新都需要用户重新提供新的二维码识别文本。

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
清空水鱼 确认清空
水鱼解绑
```

关闭该开关只影响本插件自己的命令，不会让裸 `SGWCMAID...` 自动更新。

从旧版本升级时，如果配置文件里仍然保留 `enable_prefixless_update_command`，插件会在运行时兼容它：旧开关为开启时，会按“本插件命令不需要唤醒前缀”处理。

## 成绩标识说明

当前用户侧可用的更新凭据仍然是 SGID。复制微信公众号/maimaiNET 的 OAuth 回调链接不可行，因为它依赖微信内置浏览器授权上下文，Bot 所在机器直接访问会失败。

需要注意：maimai.py 当前公开的 SGID 机台数据源只返回达成率、DX 分等基础字段，不包含 FC/FS/AP 标识。已检查 `maimai-py==1.5.1`，该版本修正了 2026 新版本 Rating 分组，但仍未给 SGID/ArcadeProvider 增加 FC/FS/AP 字段。因此当前插件可以更新基础成绩，但还不能补全 FULL COMBO、FULL SYNC、ALL PERFECT 等特殊标识。要补全这些标识，需要后续接入“SGID -> 官方详细成绩”的新接口或实现。

## 安全说明

舞萌官方二维码识别出的 SGID，以及 maimai.py 解析出的官方临时凭据，都不适合长期保存。复用旧 SGID 可能失败，也可能影响玩家正常登录。

因此本插件只持久化水鱼 Import-Token 和展示状态，不持久化 SGID，也不持久化旧版本曾使用过的 `arcade_credentials`。插件会校验 SGID 内嵌时间戳，默认只接受 180 秒内生成的 SGID；同一条 SGID 在插件进程内也只允许使用一次。

群聊中收到 SGID 或 Token 后，插件会尝试撤回原消息，并单独发送“已尝试撤回消息，如果没撤回请手动撤回”。私聊不会撤回。

## 玩家名说明

插件不会从水鱼反查玩家名，也不会在更新结果里展示玩家名，避免把一次性凭据和身份信息暴露到群聊。更新仍会继续，Rating 会尽量使用本次官方成绩链路返回的值。

## 运行环境

插件代码本身没有固定操作系统要求，只要 AstrBot 和依赖能正常安装即可。实际部署时需要注意：

- Python 需要满足 `maimai-py` 的要求；当前依赖版本要求 Python `>=3.9,<4.0`。
- 读取官方机台数据依赖 `maimai-ffi`，它是二进制 wheel；系统、CPU 架构和 Python 版本必须有对应 wheel。
- 本仓库的 `requirements.txt` 固定 `maimai-py==1.5.1`，该版本依赖 `maimai-ffi==0.7.0`。
- 已确认 Windows x64 + Python 3.10 可下载 `maimai_ffi-0.7.0-cp310-cp310-win_amd64` wheel。


## 数据

插件数据保存到 AstrBot 标准插件数据目录下的 `users.json`，明文保存。日志不会输出完整 SGID、Import-Token 或官方临时凭据。

`users.json` 只保存：

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
python -m pip install --no-cache-dir "maimai-py==1.5.1" "httpx>=0.28.0,<0.29.0"
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
python -m pip install --no-cache-dir "maimai-py==1.5.1" "httpx>=0.28.0,<0.29.0"
```

4. 重新启动 AstrBot，再安装或重载插件。

如果更新后没有 FC/FS/AP 等标识，这是当前 SGID 机台数据源的限制，不是 B50 渲染问题。

如果群聊敏感消息撤回失败，请检查 Bot 是否有撤回/管理消息权限。插件会在日志里记录一行撤回失败原因，不会输出完整 SGID 或 Token。

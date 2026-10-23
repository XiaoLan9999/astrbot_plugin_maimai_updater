# AstrBot maimai 水鱼更新器

这是一个 AstrBot 插件，用舞萌 DX 官方玩家二维码图片或 `SGWCMAID...` 文本和水鱼 Import-Token，把完整成绩同步到水鱼查分器。

![maimai 水鱼更新流程](assets/maimai-updater-flow.png)

## 更新日志

见 [CHANGELOG.md](CHANGELOG.md)。

## 功能

- `maimaitoken <Import-Token>` / `水鱼绑定 <Import-Token>` / `绑定水鱼 <Import-Token>`：保存水鱼 Import-Token。
- `maimaiupdate` / `更新水鱼` / `水鱼更新` / `更新b50`：开始更新，按提示发送二维码图片或 SGID。
- `maimaiclear 确认清空` / `清空水鱼 确认清空` / `清空b50 确认清空`：向水鱼发送清空成绩请求。
- `maimaistatus` / `水鱼状态`：查看绑定状态、最近同步结果和命令触发方式。
- `maimaiunbind` / `水鱼解绑`：删除当前用户保存的水鱼 Token 和本地状态。
- `maimaisetup` / `舞萌环境准备`：Bot 管理员准备安卓 Ubuntu 本地运行环境。
- `maimairuntime` / `舞萌环境检测`：Bot 管理员检查本地运行环境，无需 SGID。

绑定一次水鱼后，每次更新先发送更新命令，再在同一会话的 180 秒内发送官方玩家二维码图片或本次 SGID。等待期间发送 `取消更新` 可结束；重新发送更新命令会重新计时。等待时间可在面板修改。

同一张图片中的二维码会全部扫描，聊天消息含多张图片时也会逐张扫描。无 SGID 时会提示重新发送；有多个不同 SGID 时需要单独发送目标玩家的二维码。重复出现的同一 SGID 只处理一次。

原来的 `更新水鱼 SGWCMAID...` 单条命令仍然可用，也可将更新命令和二维码图片放在同一条消息中。

## 命令触发

默认开启 `require_command_prefix`，插件只响应 AstrBot 标准命令触发。实际前缀取决于 Bot 配置，例如：

```text
/水鱼状态
/水鱼绑定 <Import-Token>
/更新水鱼
[随后发送二维码图片或 SGWCMAID...]
```

如果在面板关闭 `require_command_prefix`，本插件命令可以不带 Bot 唤醒前缀直接发送：

```text
水鱼状态
水鱼绑定 <Import-Token>
绑定水鱼 <Import-Token>
更新水鱼
[随后发送二维码图片或 SGWCMAID...]
清空b50 确认清空
水鱼解绑
```

唤醒前缀只影响开始更新的命令；等待中的二维码或 SGID 无需带前缀。没有开始更新时，单独发送二维码或 SGID 不会触发。

## 当前数据链路

插件会通过本次 SGID 读取完整官方成绩字段，并写入水鱼 Import-Token 对应账号。

更新后的水鱼数据会保留 FC / FS / AP / SYNC 等特殊标识；不会用基础成绩链路猜测或补全这些标识。

## 运行环境

- Python `>=3.10,<4.0`
- AstrBot `>=4.5.2`
- 依赖见 `requirements.txt`

Windows x64 使用本地成绩链路；Linux x64 需已有配套运行环境。安卓 Ubuntu 容器使用同一个插件包，可尝试本地运行环境，也可使用远程成绩服务；均使用完整成绩字段，保留 FC / FS / AP / SYNC 标识。

### 安卓 Ubuntu 容器

旧版 [AstrBot-Android-App](https://github.com/zz6zz666/AstrBot-Android-App/tree/v1.5.3) 使用 Ubuntu 24.04 ARM64 容器，本版本为其增加了实验性本地运行环境准备。

Bot 管理员发送 `舞萌环境准备`（按面板配置添加唤醒前缀）。首次会下载约 310 MB，并通过容器的包管理器安装配套组件，需要容器管理员权限、4 KB 内存页和至少 3 GB 可用空间。安装过程保持 App 运行。工具不会自动移除已安装的软件包，遇到冲突会停止。

准备完成后发送 `舞萌环境检测`。只有实际运行探针通过，插件才会允许本地读取完整成绩。将 `remote_score_url` 留空后，正常发送更新水鱼即可；手机本地模式不需要另一台成绩服务器。

这是实验性兼容方案，目前尚未完成安卓手机的官方会话实测。手机内核、内存页大小与 PRoot 限制仍可能影响启动；下载或单元测试通过不代表手机完整链路已验证。排查步骤见 [手机本地环境](docs/android-local-runtime.md)。

不满足本地条件的设备，可以在插件面板填写 `remote_score_url` 和 `remote_score_token`，通过自行部署的完整成绩服务更新，详见 [远程成绩服务](docs/remote-score-service.md)。水鱼 Import-Token 仍使用水鱼绑定命令单独绑定。

图片识别使用 Pillow 与 zxing-cpp；不需要额外安装系统级扫码工具。图片最大 20 MB、2400 万像素。

如果依赖安装失败，完整关闭 AstrBot Launcher 和相关 Python 进程后重新安装插件依赖。

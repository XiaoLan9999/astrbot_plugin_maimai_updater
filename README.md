# AstrBot maimai 水鱼更新器

这是一个 AstrBot 插件，用舞萌 DX 官方二维码识别文本 `SGWCMAID...` 和水鱼 Import-Token，把成绩同步到水鱼查分器。

![maimai 水鱼更新流程](assets/maimai-updater-flow.png)

## 更新日志

### v0.6.26

- 修复当前版本下官方成绩读取失败的问题，更新水鱼时继续保留 FC / FS / AP / SYNC 等特殊标识。
- 精简公开说明，隐藏插件内部实现细节。

### v0.6.18 - v0.6.25

- 连续修复当前官方流程兼容性问题。
- 每次 SGID 更新结束后释放运行时资源，避免 Windows 持续占用本插件文件。

### v0.6.17

- 每次 SGID 解析结束后显式释放插件资源，避免 Windows 下更新或卸载插件时被占用。
- 成功、失败和会话创建异常路径都会执行清理。

### v0.6.16

- 将成绩更新所需的最小接口层内置到公开插件，公开安装版无需额外安装接口包即可保留 FC / FS / AP 等特殊标识。
- 公开插件只包含水鱼成绩更新所需的最小接口层，额外扩展能力后续由独立插件处理。

### v0.6.15

- 优先接入独立接口层，统一 SGID 会话、完整成绩和后续扩展能力；未启用时保留内置链路兜底。

### v0.6.14

- 更新水鱼时改为读取完整官方成绩字段，保留 FC、FC+、AP、AP+、FS、FS+、FSD、FSD+、SYNC。
- Rating 优先使用当前官方数据，避免显示旧版本 Rating。

### v0.6.13

- 停用基础成绩链路补全特殊标识的错误路径。
- 改为只在能读取完整字段时写入特殊标识。
- 修正插件注册版本与市场元数据版本不一致的问题。

### v0.6.12

- 尝试直接读取一次性 SGID 对应的原始成绩数据以保留 FC、FS、AP 等特殊标识。
- Rating 改为使用当前 maimai.py 曲库版本在本地重新计算。

### v0.6.5 - v0.6.11

- 调整一次性 SGID 会话解析和官方完整成绩链路。
- 收敛面板配置项，普通使用只保留水鱼 Token 和 SGID 更新流程。

## 功能

- `maimaitoken <Import-Token>` / `水鱼绑定 <Import-Token>` / `绑定水鱼 <Import-Token>`：保存水鱼 Import-Token。
- `maimaiupdate <SGID>` / `更新水鱼 <SGID>` / `水鱼更新 <SGID>` / `更新b50 <SGID>`：用本次 SGID 更新水鱼成绩。
- `maimaiclear 确认清空` / `清空水鱼 确认清空` / `清空b50 确认清空`：向水鱼发送清空成绩请求。
- `maimaistatus` / `水鱼状态`：查看绑定状态、最近同步结果和命令触发方式。
- `maimaiunbind` / `水鱼解绑`：删除当前用户保存的水鱼 Token 和本地状态。

插件不提供 `maimai_bind`。每次更新都直接发送一次更新命令和本次 SGID。

## 命令触发

默认开启 `require_command_prefix`，插件只响应 AstrBot 标准命令触发。实际前缀取决于 Bot 配置，例如：

```text
/水鱼状态
/水鱼绑定 <Import-Token>
/更新水鱼 SGWCMAID...
```

如果在面板关闭 `require_command_prefix`，本插件命令可以不带 Bot 唤醒前缀直接发送：

```text
水鱼状态
水鱼绑定 <Import-Token>
绑定水鱼 <Import-Token>
更新水鱼 SGWCMAID...
水鱼更新 SGWCMAID...
清空b50 确认清空
水鱼解绑
```

裸 `SGWCMAID...` 不会触发更新。

## 当前数据链路

插件会通过本次 SGID 读取完整官方成绩字段，并写入水鱼 Import-Token 对应账号。

更新后的水鱼数据会保留 FC / FS / AP / SYNC 等特殊标识；不会用基础成绩链路猜测或补全这些标识。

## 运行环境

- Python `>=3.9,<4.0`
- AstrBot `>=4.5.2`
- 依赖见 `requirements.txt`

如果依赖安装失败，完整关闭 AstrBot Launcher 和相关 Python 进程后重新安装插件依赖。

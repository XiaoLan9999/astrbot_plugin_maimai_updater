# 手机本地运行环境

适用目标为旧版 AstrBot-Android-App 的 Ubuntu 24.04 ARM64 容器。通过 Hangover 的 ARM64 本地运行环境执行现有完整成绩链路，手机侧直接把成绩导入水鱼。未改用不含 FC/FS 的基础成绩来源。

## 使用步骤

1. 更新插件并重载。
2. 由 AstrBot 配置中的 Bot 管理员发送 `舞萌环境准备`。命令是否加唤醒前缀由插件面板配置决定，群管理员身份不等于 Bot 管理员。
3. 保持 App 运行直至准备完成。首次约下载 310 MB，并通过容器包管理器安装依赖，请至少预留 3 GB 空间。
4. 发送 `舞萌环境检测`。此过程只运行加载探针，不需要或消耗 SGID。
5. 检测通过后，绑定水鱼并发送更新水鱼，再发送官方二维码或本次 SGID。

支持前提为 Ubuntu 24.04、ARM64、4 KB 内存页，以及容器内管理员和包管理器可用。运行时文件位于容器用户的数据目录，插件更新后无需重新下载。准备工具校验下载包 SHA-256，仅安装指定运行组件，不会修改 App 启动脚本或自动移除已有软件包。

## 反馈启动问题

目前已验证运行包校验与内容、安装和检测逻辑、ARM64 调用分支，以及 Windows 原生探针；尚无安卓真机上的完整官方会话验证。

- 下载失败：检查 App 容器访问 GitHub 的网络，再执行准备命令重试。
- 系统、内存页或空间不符：按检测结果处理；不适用本地模式时请联系维护者反馈设备信息。
- 包安装或探针失败：容器内的 `~/.local/share/astrbot-maimai/native/setup.log` 保存安装记录；提交错误类型和末尾相关日志即可，启动探针不需要 SGID。
- 探针通过后实际更新仍失败：再检查官方会话与网络请求，探针通过仅说明本地程序可启动和加载。

也可以在 App 的 Ubuntu 终端中进入插件目录，执行 `python tools/setup_local_runtime.py --install`。仅检测执行 `python tools/setup_local_runtime.py`。不需要手动放置插件内部文件。

## 上游来源

- [AstrBot-Android-App v1.5.3](https://github.com/zz6zz666/AstrBot-Android-App/tree/v1.5.3)
- [Hangover](https://github.com/AndreRH/hangover)，使用已固定版本并校验摘要的 Ubuntu 24.04 ARM64 运行包。
- [Hangover 内存页要求](https://github.com/AndreRH/hangover/wiki/Page-Size)

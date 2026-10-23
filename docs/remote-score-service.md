# 远程成绩服务

此功能自 v0.7.2 起暂时停用。插件面板不再提供远程地址与密钥配置，旧配置也不会生效。当前请使用原有本地成绩链路，安卓环境准备见 [手机本地环境](android-local-runtime.md)。

以下仅保留为维护参考，不适用于当前插件版本。

安卓 Ubuntu / ARM64 容器可以使用本插件的远程模式，也可以尝试 [手机本地环境](android-local-runtime.md)。远程模式的服务端部署在已经能正常读取完整官方成绩的 Windows x64 或 Linux x64 环境。

在服务端获取本仓库，安装 `requirements.txt`。从仓库根目录启动服务：

Windows PowerShell：

```powershell
$env:MAIMAI_SCORE_SERVICE_TOKEN = "设置自己的访问密钥"
python tools/score_bridge_server.py --host 0.0.0.0 --port 18250
```

Linux：

```sh
export MAIMAI_SCORE_SERVICE_TOKEN='设置自己的访问密钥'
python tools/score_bridge_server.py --host 0.0.0.0 --port 18250
```

Linux 服务进程沿用原来已配置好的本地成绩运行环境。默认不带参数时只监听 `127.0.0.1:18250`；手机跨设备访问时使用可访问的服务地址，公网部署使用 HTTPS 反向代理。

在手机 AstrBot 插件面板填写：

- `remote_score_url`：服务根地址，例如 `https://scores.example.com`，不包含 `/v1/scores`。
- `remote_score_token`：与服务进程 `MAIMAI_SCORE_SERVICE_TOKEN` 一致的访问密钥。

保存并重载插件，绑定水鱼后发送更新水鱼，再发送二维码或 SGID。Windows/Linux 客户端也可使用该模式；将服务地址留空即可使用原来的本地模式。

服务只接收一次更新所需的 SGID，返回完整成绩及 Rating。手机直接向水鱼导入成绩，水鱼 Import-Token 不发给远程成绩服务。成绩中缺少 FC/FS 字段时不导入。

## 服务接口

`GET /health` 返回 `{"protocol":1,"status":"ok"}`，用于确认服务进程可达，不代表已完成官方接口实测。

`POST /v1/scores` 使用 `Authorization: Bearer <访问密钥>`，请求体为 `{"sgid":"SGWCMAID..."}`。成功返回 `protocol: 1`、`rating` 和完整 `music_details`；不返回官方会话凭据。

服务串行处理官方请求，繁忙时返回 503；客户端不会自动重试一次性凭据。完整成绩读取后的登出和资源释放沿用本地接口实现。

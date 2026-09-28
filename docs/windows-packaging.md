# Windows 打包基线

本项目使用 `electron-builder` 生成 Windows x64 桌面产物。当前配置同时生成：

- NSIS 安装包：适合常规安装、开始菜单和桌面快捷方式。
- Portable 可执行文件：适合不安装的测试运行。

## 前置条件

- Windows 10/11 x64
- Node.js 与 npm
- 已安装项目依赖

```powershell
npm install
npm run desktop:test
```

## 生成测试包

```powershell
npm run desktop:dist:win
```

产物写入 `dist/windows/`。该命令固定使用 `--publish never`，只生成本地产物，不会创建或修改 GitHub Release。`electron-builder.yml` 中的 GitHub 配置仅用于生成更新元数据并为后续发布流程预留仓库坐标。

## 自动更新

发布版使用 `electron-updater` 和 GitHub Releases：

- 应用启动 5 秒后自动检查，发现新版本后在后台下载。
- 下载不会强制打断正在进行的工作；完成后可在“设置 / 软件更新”主动选择“重启并升级”。
- 用户正常退出时，已经下载的更新会自动安装。
- 开发模式不会请求更新服务，浏览器模式不显示桌面更新入口。
- 主动升级会先停止应用持有的 Python 后台和 embedded PostgreSQL，再启动 NSIS 更新器。
- 渲染层只能通过白名单 IPC 读取状态、发起检查和安装，更新源及错误细节不会由页面传入或回显。

真实更新验收至少需要两个不同版本。先发布并安装旧版本，再将新版本对应 Release 从 Draft 发布为可访问状态，并确认其中包含安装包、blockmap 与 `latest.yml`。验证新版本下载、数据保留、重启安装和失败回滚后，才能把更新通道标记为已验证。本地 `--publish never` 构建只能验证产物结构，不能证明远程升级链正常。

## 签名与未签名构建

本地没有代码签名证书时，`forceCodeSigning: false` 允许生成 unsigned 测试包。Windows SmartScreen 可能警告，这类包只用于内部验证，不是正式发行物。

需要签名时，在构建环境中提供 electron-builder 支持的 `CSC_LINK` 和 `CSC_KEY_PASSWORD` 环境变量。electron-builder 会自动发现证书并签名；证书、密码和 Token 不得写入仓库、YAML、npm 脚本或日志。正式发布前必须在干净环境中检查 Authenticode 签名和时间戳。

## 用户数据与卸载

NSIS 配置明确设置 `deleteAppDataOnUninstall: false`。默认卸载不会删除 Electron `userData` 目录、`%USERPROFILE%/.comic-pipeline/database` 本地数据库或 Documents 中的创作数据。需要清理时应由用户显式执行，安装器不做静默删除。

## 2026-09-28 本机验收

- `npm run desktop:dist:win` 成功生成 `Comic Generation-Setup-0.1.0-x64.exe`、`Comic Generation-Portable-0.1.0-x64.exe`、blockmap 和 `latest.yml`。
- 解包目录、Portable 和 NSIS 安装版本均实际启动随包 Python 后台与 embedded PostgreSQL；`8199`、`54329` 就绪，`/api/config` 数据库状态正常且不返回数据库连接串。
- 同版本 NSIS 修复安装返回 `ExitCode=0`。静默卸载删除安装目录，同时保留 `%APPDATA%/Comic Pipeline` 和 `%USERPROFILE%/.comic-pipeline/database`。
- Docker 源 PostgreSQL 在构建、安装和运行测试前后保持同一容器、同一启动时间、健康状态和 `RestartCount=0`。
- Python `232/232`、Vue `22/22`、Electron/Node `41/41` 测试通过；四种桌面分辨率的核心视图没有横向溢出或不可达控件。

本轮是当前开发机上的内部验收，不等同于正式发行。自动化使用隐藏窗口时，NSIS 安装版本无法取得 GUI 关闭句柄，测试结束采用精确进程清理；Portable 已验证正常窗口关闭后释放后台和数据库端口。

## v1.1.0 发布说明

`v1.1.0` 是首个包含 Windows 桌面运行时和自动更新客户端的公开版本。发布资产应包含 Setup、Portable、Setup blockmap 与 `latest.yml`。当前产物尚未签名，安装时可能出现 SmartScreen 警告；在取得代码签名证书并完成两个已发布版本之间的升级验证前，签名和真实更新链仍属于待验收项。

## 正式发行门槛

1. 提供正式的 Windows `.ico` 应用图标；当前测试包使用 Electron 默认图标。
2. 提供有效代码签名证书并验证时间戳与 SmartScreen；当前 Setup 和 Portable 的 Authenticode 状态均为 `NotSigned`。
3. 在一台干净的 Windows 10/11 x64 机器重复安装、首次启动、重启、修复安装和卸载测试。
4. 接入并验证真实更新客户端与版本升级链；生成 `latest.yml` 不能替代一次真实的旧版到新版升级。
5. 正式迁移必须由用户显式触发；内部恢复演练不会自动覆盖桌面默认数据库。

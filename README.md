# Comic Generation

面向长篇小说的漫画生产工作台。它将小说拆解、设定审核、全局素材、分镜生成、页面审核和下一章循环集中在一个桌面应用中，并保留人工审核节点。

## 下载与安装

当前版本：`v1.1.0`

- [Windows 安装版](https://github.com/ToxicantX/Comic-Generation/releases/download/v1.1.0/Comic-Generation-Setup-1.1.0-x64.exe)
- [Windows 便携版](https://github.com/ToxicantX/Comic-Generation/releases/download/v1.1.0/Comic-Generation-Portable-1.1.0-x64.exe)
- [版本说明](https://github.com/ToxicantX/Comic-Generation/releases/tag/v1.1.0)

推荐使用安装版。桌面包已包含 Python 运行环境和 PostgreSQL，普通用户不需要安装 Docker、Python 或 ComfyUI。

首次启动后：

1. 打开 `设置`，分别配置小说处理模型和图片生成模型。
2. 测试两个模型的连接并保存。
3. 导入小说文件，开始章节识别和全书设定扫描。
4. 审核全局设定与参考素材，再进入章节生成。

> `v1.1.0` 尚未进行代码签名，Windows 可能显示 SmartScreen 提示。

## 工作流程

1. **导入小说**：识别章节并提取角色、场景、道具和世界观。
2. **审核设定**：编辑、补充或使用 AI 重新提取全书设定。
3. **生成全局素材**：建立跨章节复用的角色、场景和道具参考图。
4. **章节细读**：生成页面规划、原文证据、分镜提示词和素材引用。
5. **小批量生成**：先生成少量分镜，确认画风和人物一致性。
6. **审核与 QA**：检查单格、整页、文字和一致性；支持重新生成。
7. **进入下一章**：审核通过后继续循环，不自动跳过人工确认。

## 图片生成后端

| 后端 | 适用场景 | 是否需要 ComfyUI |
| --- | --- | --- |
| `direct_api` | 默认模式，使用 OpenAI-compatible 图片 API | 否 |
| `comfyui` | 本地 checkpoint、LoRA、ControlNet 和自定义工作流 | 是 |

文本模型与图片模型独立配置，可使用不同的 Base URL、模型和 API Key。日常配置都在应用的 `设置` 中完成。

选择本地 ComfyUI 后端时，安装项目节点并重启 ComfyUI：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_to_comfyui.ps1 -Force -DisableLegacySingleFileNode
```

ComfyUI 是可选生成后端，不是主要操作界面。

## 源码启动

### 桌面开发模式

需要 Node.js 和 Docker Desktop。开发模式会构建前端，并在后台未运行时通过 Docker Compose 启动服务。

```powershell
git clone git@github.com:ToxicantX/Comic-Generation.git
cd Comic-Generation
npm ci
npm run desktop:dev
```

### 浏览器与 Docker 模式

```powershell
powershell -ExecutionPolicy Bypass -File .\start_docker.ps1 -Build
```

打开 [http://127.0.0.1:8199](http://127.0.0.1:8199)。默认使用 `direct_api`，不会启动或探测 `8188`。

使用本机 ComfyUI 时：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_docker.ps1 `
  -ImageBackend comfyui `
  -ComfyRoot "D:\ComfyUI" `
  -ComfyUrl "http://127.0.0.1:8188" `
  -Build
```

## 常用命令

```powershell
# 前端、桌面端测试与构建检查
npm test

# Python 测试
python -m pytest -q

# 构建 Windows 安装版和便携版
npm run desktop:dist:win

# Docker 状态与日志
docker compose ps
docker compose logs --tail=100 comic-console
docker compose down
```

## 数据与安全

桌面版数据位置：

- 应用配置、日志和备份：`%APPDATA%/Comic Pipeline`
- PostgreSQL 数据：`%USERPROFILE%/.comic-pipeline/database`
- 用户文档与导出：`%USERPROFILE%/Documents/Comic Pipeline`

桌面版 API Key 使用 Electron `safeStorage` 保存。源码模式的本机配置位于 `config/`，真实 `.env`、API Key、小说原文、运行日志和生成结果均不应提交到 Git。

通过局域网或反向代理开放浏览器模式时，请在进程环境中设置 `COMIC_PIPELINE_CONSOLE_TOKEN`。

## 项目结构

- `console/`：Python API、任务、审核和数据访问。
- `desktop/`：Electron 桌面容器与自动更新。
- `console/frontend/`：Vue 3 + TypeScript 界面。
- `scripts/`：拆解、生成、拼版和 QA 脚本。
- `custom_nodes/`：可选的 ComfyUI 节点。
- `tests/`：Python、前端和桌面端测试。
- `docs/`：设计、迁移、打包和验收文档。

## 详细文档

- [桌面化范围与迁移计划](docs/desktop-migration-plan.md)
- [Windows 打包与发布](docs/windows-packaging.md)
- [直连图片 API 验收记录](docs/direct-api-e2e-2026-09-28.md)
- [界面与漫画预览设计规范](docs/design-guidelines.md)
- [可编辑流程蓝图](docs/comic-pipeline-blueprint.drawio)
- [迁移基线](docs/migration-baseline-20260928.md)

## 当前限制

- `v1.1.0` 未签名，可能触发 Windows SmartScreen。
- 安装版已实现版本检查和后台下载；完整跨版本升级需要在后续版本发布后继续验收。
- 本地模型的最终质量取决于 checkpoint、LoRA、ControlNet 与提示词适配，端口可访问不代表模型已就绪。

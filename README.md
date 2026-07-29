# Comic Pipeline

独立漫画流水线包。目标是把小说拆解、人工审核、漫画生成、页面 QA、下一章循环从当前工作区中独立出来，后续可以复制到其他机器部署。

图片生成长期支持两种后端，所有业务流程共用同一套 PostgreSQL 任务、审核、重试、版本备份、输出、拼版和 QA：

- `direct_api`：默认模式，控制台直连 OpenAI-compatible 图片 API，不依赖 ComfyUI 或 `8188`。
- `comfyui`：可选本地模型模式，用于本地 checkpoint、LoRA、ControlNet 和可视化工作流。它是正式支持的后端，不是待清理的迁移代码。

当前自动生成的默认图片工作流仍使用 `OpenAICompatibleImageGenerate`。ComfyUI 后端可以执行已有的 API-format 本地工作流；自动创建 checkpoint、LoRA、ControlNet 节点图属于后续工作流模板功能，不在当前版本范围内。

## 目录

- `custom_nodes/`: 可选 ComfyUI 后端的漫画流水线节点和 Web 扩展资源。
- `console/`: 独立本地控制台，配置、审核、阶段运行和结果查看都从这里进入。
- `scripts/`: 章节拆解、页面计划、工作流生成、批量生成、页面组装和 QA 脚本。
- `workflows/comic/`: 可提交的是基础 workflow 蓝图；按小说生成的分镜 workflow 属于运行产物。
- `manifests/`: 运行时会写入项目拆解、章节计划和任务结果；默认不提交 `manifests/projects/`。
- `config/.env`: 机器级部署配置，不提交真实内容。
- `config/text.env`: 小说处理模型 API Key 和 Base URL，不提交真实内容。
- `config/image.env`: 图片生成模型 API Key 和 Base URL，不提交真实内容。
- `docs/comic-pipeline-blueprint.drawio`: 可编辑流程蓝图。
- `docs/design-guidelines.md`: 控制台 UI、漫画预览和页面拼版设计准则。

## 提交范围和敏感信息

准备提交仓库时，以 `comic-pipeline/` 作为项目根目录。父级 `E:\workspace\ComfyUIProjects` 下的旧 `docs/`、`scripts/`、`workflows/`、截图和小说文件是历史工作区内容，不属于当前独立项目。

应该提交：

- 源码：`console/`、`custom_nodes/`、`scripts/`、`tests/`。
- 文档：`README.md`、`docs/`。
- 部署模板：`Dockerfile`、`docker-compose.yml`、`*.ps1` 启动/安装脚本。
- 配置样例：`config/.env.example`、`config/.env.docker.example`、`config/text.env.example`、`config/image.env.example`。
- 基础蓝图：`workflows/comic/*blueprint.json`。

不要提交：

- 真实密钥和机器配置：`config/.env`、`config/.env.docker`、`config/text.env`、`config/image.env`。
- 小说原文和用户项目数据：`novels/`、`manifests/projects/`。
- 生成结果和日志：`output/`、`logs/`、`backups/`、`test-results/`、`.playwright-cli/`。
- 按章节/分镜生成的 workflow：`workflows/comic/generated_assets/`、`workflows/comic/ssj_*.json`、`*_fallback_v*.json`、`*_image_v*.json`、`*.bak-*`。
- 任务运行上下文：`manifests/comic_runs/`。

提交前建议执行：

```powershell
cd E:\workspace\ComfyUIProjects\comic-pipeline

# 如果这是新仓库，先初始化 Git；当前父目录的 .git 目录不是有效仓库。
git init

git status --ignored --short
git diff -- .gitignore .dockerignore README.md
Get-ChildItem config -Force
powershell -ExecutionPolicy Bypass -File .\scripts\test_prompt_secret_hygiene.ps1 -SkipComfyProbe

# 检查常见明文密钥模式；命中 config/text.env 或 config/image.env 说明 ignore 生效前不要 add。
Select-String -Path (Get-ChildItem -Recurse -File | Where-Object {
  $_.FullName -notmatch '\\(novels|output|logs|backups|test-results|\.playwright-cli|__pycache__|\.git)\\'
}).FullName -Pattern 'sk-[A-Za-z0-9_-]{20,}|OPENAI_API_KEY\s*=\s*\S+|API_KEY\s*=\s*\S+' |
  Select-Object Path,LineNumber
```

如果密钥已经误提交过，不能只改 `.gitignore`，需要轮换 API Key，并从 Git 历史中清理。

## 初始化配置

默认使用直连图片 API：

```powershell
powershell -ExecutionPolicy Bypass -File .\configure.ps1 `
  -ImageBackend direct_api `
  -NovelPath "E:\workspace\ComfyUIProjects\搜神记.txt" `
  -TextApiKey "sk-..." `
  -TextBaseUrl "https://api.example.com/v1" `
  -ImageApiKey "sk-..." `
  -ImageBaseUrl "https://api.example.com/v1"
```

使用本地 ComfyUI 模型时：

```powershell
powershell -ExecutionPolicy Bypass -File .\configure.ps1 `
  -ImageBackend comfyui `
  -ComfyRoot "G:\ComfyUI" `
  -ComfyUrl "http://127.0.0.1:8188" `
  -NovelPath "E:\workspace\ComfyUIProjects\搜神记.txt"
```

小说处理模型密钥会写到 `config/text.env`，直连图片模型密钥会写到 `config/image.env`。配置和工作流不会保存明文 key。选择 `comfyui` 时，图片 API Key 和云端图片模型不是必填项；只有工作流本身调用云端图片节点时才需要配置。

不想在命令行传 key 时，直接编辑：

- `config/.env`: 图片后端、可选 ComfyUI 路径和 URL、小说文件、输出目录、默认页数、编码。
- `config/text.env`: `OPENAI_API_KEY`、`OPENAI_BASE_URL`。
- `config/image.env`: `OPENAI_API_KEY`、`OPENAI_BASE_URL`。

选择 `comfyui` 时，可以在 ComfyUI 中添加 `comic/pipeline -> 漫画流水线配置` 节点检查当前配置。这个节点只显示 API Key 是否已配置，不输出明文 key。

## 可选：安装到 ComfyUI

只有选择 `comfyui` 本地模型后端时才需要执行本节。`direct_api` 模式不安装节点也能完成漫画生成。

```powershell
powershell -ExecutionPolicy Bypass -File .\install_to_comfyui.ps1 -Force -DisableLegacySingleFileNode
```

安装脚本会复制节点到 `ComfyUI\custom_nodes\comic_episode_pipeline`，并写入 `comic_pipeline_root.txt` 指向当前独立包。这样节点运行时会回到本包读取 `config/.env`、`scripts/`、`manifests/`、`workflows/`。

如果当前 ComfyUI 里还有旧的 `custom_nodes\comic_episode_pipeline_node.py`，必须使用 `-DisableLegacySingleFileNode`，否则同名节点会重复注册。安装后重启 ComfyUI。

## 启动控制台

日常使用不需要进入 ComfyUI 节点图。配置、审核、运行和结果查看都从漫画流水线控制台操作；生成时由设置中选择的图片后端执行。

后续控制台界面、漫画预览和页面拼版必须遵循 `docs/design-guidelines.md`。当前固化方向是视觉紧凑、黑色 gutter、横向大格边缘对齐、无粗边框、无大留白。

### Docker Compose 启动（推荐）

默认 Docker 模式只启动：

- 漫画控制台：`http://127.0.0.1:8199`
- PostgreSQL：宿主机端口 `55432`

默认 `direct_api` 模式不会探测或启动 `8188`，也不会挂载本机 ComfyUI 目录：

```powershell
cd E:\workspace\ComfyUIProjects\comic-pipeline
powershell -ExecutionPolicy Bypass -File .\start_docker.ps1 -Build
```

使用 ComfyUI 本地模型时显式选择后端。启动脚本会在需要时拉起宿主机 ComfyUI，并通过 `docker-compose.comfyui.yml` 将本地模型与输出目录挂载到控制台容器：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_docker.ps1 `
  -ImageBackend comfyui `
  -ComfyRoot "D:\ComfyUI" `
  -ComfyUrl "http://127.0.0.1:8188" `
  -Build
```

ComfyUI 已由其他方式管理时，可追加 `-SkipGenerationBackend`，只让控制台连接现有服务。

Docker 已按默认模式启动后，仅在控制台设置中切换为 `comfyui` 不会动态增加宿主机目录挂载。需要重新运行上述 `start_docker.ps1 -ImageBackend comfyui` 命令；健康检查会在共享输出目录未挂载时阻止生成。

首次启动时脚本只会在缺失时创建：

- `config/.env.docker`：Docker 模式、图片后端、路径和数据库配置。
- `config/text.env`：小说处理模型 API Key 和 Base URL。
- `config/image.env`：图片生成 API Key 和 Base URL。

不会覆盖已有的 `config/.env`、`config/.env.docker`、`config/text.env` 或 `config/image.env`。

Docker 模式下常用命令：

```powershell
docker compose ps
docker compose logs --tail=100 comic-console
docker compose down
```

迁移到其他机器时，默认模式不需要修改 Compose 的本机路径。使用 ComfyUI 时通过 `-ImageBackend comfyui -ComfyRoot <目录>` 启动，不要直接把机器路径写死在 `docker-compose.yml`。真实 API Key 分别写在 `config/text.env` 和 `config/image.env`。

### 本地 Python 启动

启动控制台时会根据 `COMIC_PIPELINE_IMAGE_BACKEND` 处理生成后端。`direct_api` 不启动额外服务；`comfyui` 会检查并按配置尝试拉起本地服务：

```powershell
cd E:\workspace\ComfyUIProjects\comic-pipeline
powershell -ExecutionPolicy Bypass -File .\start_console.ps1
```

默认入口：

```text
http://127.0.0.1:8199
```

控制台提供：

- 在左侧独立 `设置` 中分别配置小说处理模型、图片生成模型、两个 API Key、图片质量、生成后端、输出目录和 PostgreSQL。
- 按当前后端检查直连图片 API，或检查 ComfyUI 的 `object_info`、`extensions`、队列和关键路径。
- 按小说隔离原文、章节拆解、全局设定、全局素材、生成结果、审核记录和任务。
- 按阶段运行：小说导入与章节骨架、项目级设定扫描、全局素材确认、章节细读、生成审核、页面 QA、下一章循环。
- 批量选择设定生成视觉素材，查看串行进度，汇总失败项并仅重试失败素材。
- 对单张分镜或单个一致性素材发起重新生成；旧图会先备份，分镜完成后会尝试重新组装页面。
- 导出或导入项目 ZIP 备份，可选择是否包含图片；导入会校验路径和文件校验和。

## 检查配置

```powershell
powershell -ExecutionPolicy Bypass -File .\check_config.ps1
```

直连图片 API 模式下，真实生成前再执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\check_config.ps1 -RequireImageApiKey
```

## 安全测试

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_comic_episode_pipeline.ps1 `
  -EpisodeNumber 3 `
  -DryRun `
  -SkipImageGeneration
```

这条命令不会生成图片，也不会消耗图片接口额度。它用于验证脚本、路径、章节计划、审核报告链路。

## 生成测试

真实生成前必须经过人工审核和开关确认。日常操作入口是独立控制台：

```text
http://127.0.0.1:8199
```

流程顺序：

1. 在 `设置` 中选择图片生成后端，分别测试小说处理模型和图片生成模型，确认 PostgreSQL 与所选后端可用。
2. 在 `导入小说` 中选择小说文件。首次处理会拆分章节，并提取项目级角色、场景、道具和世界观候选。
3. 在 `小说设定库` 中按分组审核、编辑或 AI 重提设定；核心设定需要审核并锁定。
4. 在 `全局素材库` 中生成并审核核心角色、场景和道具参考图，可批量生成或仅重试失败项。
5. 进入 `章节工作台` 运行细读拆解，审核页面摘要、原文证据、分镜提示和素材引用。
6. 章节素材门禁通过后点击 `小批量生成`；验收时保持 `最大分镜=1`、`最大页数=1`。
7. 在 `生成结果` 中逐项查看页面和分镜，完成质量维度检查；需要修改时可单格或整页重生成。
8. 运行 `页面审核 / QA`，确认文字、一致性和图片健康报告全部通过。
9. 通过 QA 后确认进入下一章，重复“细读 -> 素材门禁 -> 生成 -> 审核 -> QA”的循环。

结果查看：

- 漫画页面：`COMIC_PIPELINE_OUTPUT_ROOT\pages`
- 审核 Markdown：`COMIC_PIPELINE_OUTPUT_ROOT\review_packages`
- 控制台结果页：`http://127.0.0.1:8199`
- ComfyUI 预览：选择 `comfyui` 时保留为辅助入口，不作为主要操作界面。
- 运行 JSON：`manifests\*.json`

图片质量可在 `设置 -> 图片生成 -> 图片生成质量` 中选择 `自动 / 低 / 中 / 高`。日常使用推荐 `自动`；低质量适合节省额度的流程联调。

## 迁移到其他机器

复制整个 `comic-pipeline` 目录到目标机器。默认直连模式：

```powershell
powershell -ExecutionPolicy Bypass -File .\configure.ps1 `
  -ImageBackend direct_api `
  -NovelPath "D:\Novels\novel.txt" `
  -Force

notepad .\config\text.env
notepad .\config\image.env
powershell -ExecutionPolicy Bypass -File .\check_config.ps1
```

需要使用本地模型的机器再安装 ComfyUI 节点并切换后端：

```powershell
powershell -ExecutionPolicy Bypass -File .\configure.ps1 `
  -ImageBackend comfyui `
  -ComfyRoot "D:\ComfyUI" `
  -ComfyUrl "http://127.0.0.1:8188" `
  -NovelPath "D:\Novels\novel.txt" `
  -Force

powershell -ExecutionPolicy Bypass -File .\install_to_comfyui.ps1 -Force -DisableLegacySingleFileNode
powershell -ExecutionPolicy Bypass -File .\check_config.ps1
```

不要把 `config/text.env`、`config/image.env` 或任何真实 `.env` 文件提交或发给别人。

## 部署检查清单

1. 安装依赖：Docker Desktop、Git、Python 3.12；只有本地模型模式需要额外安装 ComfyUI。
2. 克隆或复制 `comic-pipeline/` 到目标机器。
3. 复制样例配置或运行 `configure.ps1` / `start_docker.ps1` 生成本机配置。
4. 在 `config/text.env` 配置小说处理模型，在 `config/image.env` 配置图片生成模型。
5. 在设置中选择 `direct_api` 或 `comfyui`；后者需检查 `COMIC_PIPELINE_COMFY_ROOT`、URL、节点和本地模型。
6. 启动 PostgreSQL 和控制台：推荐 `powershell -ExecutionPolicy Bypass -File .\start_docker.ps1 -Build`。
7. 打开 `http://127.0.0.1:8199`，在 `设置` 中测试小说处理模型和图片模型连接。
8. 导入小说后先跑章节拆解和全局素材审核，再进入章节细读和漫画生成。
9. 运行 `python -m unittest discover -s tests -v`，确认自动化测试全部通过。
10. 使用 `git status --ignored --short` 确认小说、密钥、项目 manifest、生成 workflow 和输出图片均未进入提交范围。

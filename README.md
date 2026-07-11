# Comic Pipeline

独立漫画流水线包。目标是把小说拆解、人工审核、漫画生成、页面 QA、下一章循环从当前工作区中独立出来，后续可以复制到其他机器部署。

## 目录

- `custom_nodes/`: ComfyUI 漫画流水线节点和 Web 控制台资源。
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
- 按章节/分镜生成的 workflow：`workflows/comic/ssj_*.json`、`*_fallback_v*.json`、`*_image_v*.json`、`*.bak-*`。

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

```powershell
powershell -ExecutionPolicy Bypass -File .\configure.ps1 `
  -ComfyRoot "G:\ComfyUI" `
  -ComfyUrl "http://127.0.0.1:8188" `
  -NovelPath "E:\workspace\ComfyUIProjects\搜神记.txt" `
  -TextApiKey "sk-..." `
  -TextBaseUrl "https://api.example.com/v1" `
  -ImageApiKey "sk-..." `
  -ImageBaseUrl "https://api.example.com/v1"
```

小说处理模型密钥会写到 `config/text.env`，图片生成模型密钥会写到 `config/image.env`。工作流只保存 `api_key_env_path`，不会把明文 key 写进 ComfyUI prompt。

不想在命令行传 key 时，直接编辑：

- `config/.env`: ComfyUI 路径、ComfyUI URL、小说文件、输出目录、默认页数、编码。
- `config/text.env`: `OPENAI_API_KEY`、`OPENAI_BASE_URL`。
- `config/image.env`: `OPENAI_API_KEY`、`OPENAI_BASE_URL`。

ComfyUI 里可以添加 `comic/pipeline -> 漫画流水线配置` 节点检查当前配置。这个节点只显示 API Key 是否已配置，不输出明文 key。

## 安装到 ComfyUI

```powershell
powershell -ExecutionPolicy Bypass -File .\install_to_comfyui.ps1 -Force -DisableLegacySingleFileNode
```

安装脚本会复制节点到 `ComfyUI\custom_nodes\comic_episode_pipeline`，并写入 `comic_pipeline_root.txt` 指向当前独立包。这样节点运行时会回到本包读取 `config/.env`、`scripts/`、`manifests/`、`workflows/`。

如果当前 ComfyUI 里还有旧的 `custom_nodes\comic_episode_pipeline_node.py`，必须使用 `-DisableLegacySingleFileNode`，否则同名节点会重复注册。安装后重启 ComfyUI。

## 启动控制台

日常使用不需要进入 ComfyUI 节点图。ComfyUI 只作为后端执行器，配置、审核、运行和结果查看都从漫画流水线控制台操作。

后续控制台界面、漫画预览和页面拼版必须遵循 `docs/design-guidelines.md`。当前固化方向是视觉紧凑、黑色 gutter、横向大格边缘对齐、无粗边框、无大留白。

### Docker Compose 启动（推荐）

Docker 模式会一起启动：

- 漫画控制台：`http://127.0.0.1:8199`
- PostgreSQL：宿主机端口 `55432`
- 宿主机 ComfyUI：默认从 `G:\ComfyUI` 自动启动并监听 `8188`

ComfyUI 作为宿主机生成后端运行，默认地址是 `http://127.0.0.1:8188`。启动脚本会在后端未运行时自动拉起它，控制台容器通过 `host.docker.internal:8188` 访问。使用其他安装目录时传入 `-ComfyRoot`；只启动控制台和数据库时传入 `-SkipGenerationBackend`。

```powershell
cd E:\workspace\ComfyUIProjects\comic-pipeline
powershell -ExecutionPolicy Bypass -File .\start_docker.ps1 -Build

# 自定义 ComfyUI 目录
powershell -ExecutionPolicy Bypass -File .\start_docker.ps1 -ComfyRoot "D:\ComfyUI"
```

首次启动时脚本只会在缺失时创建：

- `config/.env.docker`：Docker 模式路径、数据库、ComfyUI 地址。
- `config/text.env`：小说处理模型 API Key 和 Base URL。
- `config/image.env`：图片生成 API Key 和 Base URL。

不会覆盖已有的 `config/.env`、`config/.env.docker`、`config/text.env` 或 `config/image.env`。

Docker 模式下常用命令：

```powershell
docker compose ps
docker compose logs --tail=100 comic-console
docker compose down
```

如果迁移到其他机器，先修改 `docker-compose.yml` 中的本机 ComfyUI 挂载路径，例如 `G:/ComfyUI:/comfyui`，再修改 `config/.env.docker` 中的输出路径。真实 API Key 分别写在 `config/text.env` 和 `config/image.env`。

### 本地 Python 启动

启动控制台时会自动检查并拉起生成后端：

```powershell
cd E:\workspace\ComfyUIProjects\comic-pipeline
powershell -ExecutionPolicy Bypass -File .\start_console.ps1
```

默认入口：

```text
http://127.0.0.1:8199
```

控制台提供：

- 在顶部 `设置` 中配置生成后端地址、小说文件、输出目录、图片模型、API Key。
- 检查 ComfyUI、`object_info`、`extensions`、队列和关键路径。
- 按阶段运行：预检、AI 拆解、生成审稿包、小批量生成、页面审核、刷新状态。
- 查看章节列表、章节拆解、故事线、素材库、生成页面、生成分镜、QA 审核和任务日志。
- 对单张分镜或单个一致性素材发起重新生成；旧图会先备份，分镜完成后会尝试重新组装页面。

## 检查配置

```powershell
powershell -ExecutionPolicy Bypass -File .\check_config.ps1
```

真实生成前再执行：

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

1. 在左侧选择章节，右侧确认小说路径、输出目录、图片模型、API Key。
2. 点击 `预检`，确认 ComfyUI、路径和配置可用。
3. 点击 `AI 拆解`，在 `章节拆解`、`故事线`、`素材库` 中人工审核。
4. 审核通过后点击 `小批量生成`，测试时保持 `最大分镜=1`、`最大页数=1`。
5. 在 `素材库` 中查看角色、世界/场景、武器、服装、异兽/生物资产；需要更新一致性参考图时点击 `重新生成素材`。
6. 在 `生成结果` 中查看页面和分镜；需要修改某张分镜时点击该分镜的 `重新生成`。
7. 点击 `页面审核`，在 `QA 审核` 中查看文字、一致性和图片健康报告。
8. 当前章通过后，在左侧选择下一章，重复以上流程。

结果查看：

- 漫画页面：`COMIC_PIPELINE_OUTPUT_ROOT\pages`
- 审核 Markdown：`COMIC_PIPELINE_OUTPUT_ROOT\review_packages`
- 控制台结果页：`http://127.0.0.1:8199`
- ComfyUI 预览：保留为兼容入口，不作为主要操作界面。
- 运行 JSON：`manifests\*.json`

## 迁移到其他机器

复制整个 `comic-pipeline` 目录到目标机器，然后：

```powershell
powershell -ExecutionPolicy Bypass -File .\configure.ps1 `
  -ComfyRoot "D:\ComfyUI" `
  -ComfyUrl "http://127.0.0.1:8188" `
  -NovelPath "D:\Novels\novel.txt" `
  -Force

notepad .\config\text.env
notepad .\config\image.env

powershell -ExecutionPolicy Bypass -File .\install_to_comfyui.ps1 -Force -DisableLegacySingleFileNode
powershell -ExecutionPolicy Bypass -File .\check_config.ps1
```

不要把 `config/text.env`、`config/image.env` 或任何真实 `.env` 文件提交或发给别人。

## 部署检查清单

1. 安装依赖：Docker Desktop、Git、Python 3.12；真实生成还需要可访问的 ComfyUI。
2. 克隆或复制 `comic-pipeline/` 到目标机器。
3. 复制样例配置或运行 `configure.ps1` / `start_docker.ps1` 生成本机配置。
4. 在 `config/text.env` 配置小说处理模型，在 `config/image.env` 配置图片生成模型。
5. Docker 模式下检查 `docker-compose.yml` 的 ComfyUI 挂载路径；本地模式下检查 `COMIC_PIPELINE_COMFY_ROOT`。
6. 启动 PostgreSQL 和控制台：推荐 `powershell -ExecutionPolicy Bypass -File .\start_docker.ps1 -Build`。
7. 打开 `http://127.0.0.1:8199`，在 `设置` 中测试小说处理模型和图片模型连接。
8. 导入小说后先跑章节拆解和全局素材审核，再进入章节细读和漫画生成。

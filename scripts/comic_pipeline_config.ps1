function Get-ComicPipelineRoot {
    param([string]$StartPath = $PSScriptRoot)
    $path = Resolve-Path -LiteralPath $StartPath
    $item = Get-Item -LiteralPath $path
    if (-not $item.PSIsContainer) {
        $item = $item.Directory
    }
    while ($item) {
        if ((Test-Path -LiteralPath (Join-Path $item.FullName "config")) -and (Test-Path -LiteralPath (Join-Path $item.FullName "scripts"))) {
            return $item.FullName
        }
        $item = $item.Parent
    }
    throw "Could not locate comic-pipeline root from $StartPath"
}

function Read-ComicEnvFile {
    param([string]$Path)
    $result = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $result
    }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or $trimmed -notmatch "=") {
            continue
        }
        $key, $value = $trimmed.Split("=", 2)
        $result[$key.Trim()] = $value.Trim().Trim('"').Trim("'")
    }
    return $result
}

function Get-ComicEnvValue {
    param(
        [hashtable]$Values,
        [string]$Key,
        [string]$Default = ""
    )
    $envValue = [Environment]::GetEnvironmentVariable($Key, "Process")
    if ($envValue) {
        return $envValue
    }
    if ($Values.ContainsKey($Key) -and $Values[$Key]) {
        return $Values[$Key]
    }
    return $Default
}

function Get-ComicPipelineConfig {
    param([string]$Root = "")
    if (-not $Root) {
        $Root = Get-ComicPipelineRoot
    }
    $envPath = if ($env:COMIC_PIPELINE_CONFIG_PATH) { $env:COMIC_PIPELINE_CONFIG_PATH } else { Join-Path $Root "config\.env" }
    $values = Read-ComicEnvFile -Path $envPath
    $workspace = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_WORKSPACE" -Default $Root
    $comfyRoot = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_ROOT" -Default (Join-Path $Root "ComfyUI")
    $comfyOutputRoot = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_OUTPUT_ROOT" -Default (Join-Path $Root "output")
    $outputRoot = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_OUTPUT_ROOT" -Default (Join-Path $comfyOutputRoot "ComicPipeline")
    $imageEnvPath = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_IMAGE_ENV_PATH" -Default (Join-Path $Root "config\image.env")
    $imageQuality = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_IMAGE_QUALITY" -Default "auto"
    $comfyLoraName = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_LORA_NAME"
    $comfyControlnetName = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_CONTROLNET_NAME"
    $novelPath = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_NOVEL_PATH" -Default (Join-Path $Root "novel.txt")
    $pythonPath = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_PYTHON_PATH"
    if (-not $pythonPath) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pythonCommand -and $pythonCommand.Source) { $pythonCommand.Source } else { "python" }
    }
    return [ordered]@{
        Root = $Root
        EnvPath = $envPath
        Workspace = $workspace
        ComfyRoot = $comfyRoot
        CustomNodesRoot = Join-Path $comfyRoot "custom_nodes"
        ComfyUrl = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_URL" -Default "http://127.0.0.1:8188"
        ComfyOutputRoot = $comfyOutputRoot
        OutputRoot = $outputRoot
        NovelPath = $novelPath
        ImageEnvPath = $imageEnvPath
        ImageBackend = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_IMAGE_BACKEND" -Default "direct_api"
        ComfyCheckpoint = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_CHECKPOINT"
        ComfyLoraName = $comfyLoraName
        ComfyLoraStrengthModel = [double](Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_LORA_STRENGTH_MODEL" -Default "1.0")
        ComfyLoraStrengthClip = [double](Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_LORA_STRENGTH_CLIP" -Default "1.0")
        ComfyControlnetName = $comfyControlnetName
        ComfyControlnetStrength = [double](Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_CONTROLNET_STRENGTH" -Default "1.0")
        ComfyControlnetStart = [double](Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_CONTROLNET_START" -Default "0.0")
        ComfyControlnetEnd = [double](Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_CONTROLNET_END" -Default "1.0")
        ComfySteps = [int](Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_STEPS" -Default "28")
        ComfyCfg = [double](Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_CFG" -Default "7.0")
        ComfySampler = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_SAMPLER" -Default "dpmpp_2m"
        ComfyScheduler = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_COMFY_SCHEDULER" -Default "karras"
        DatabaseUrl = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_DATABASE_URL" -Default "postgresql://comic_pipeline:comic_pipeline@127.0.0.1:54329/comic_pipeline"
        TextModel = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_TEXT_MODEL" -Default "gpt-4.1-mini"
        ImageModel = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_IMAGE_MODEL" -Default "gpt-image-2"
        ImageQuality = $imageQuality
        PythonPath = $pythonPath
        DefaultPages = [int](Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_DEFAULT_PAGES" -Default "8")
        Encoding = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_ENCODING" -Default "gb18030"
        ActiveProject = Get-ComicEnvValue -Values $values -Key "COMIC_PIPELINE_ACTIVE_PROJECT" -Default "sou_shen_ji"
    }
}

function Set-ComicPipelineProcessEnv {
    param($Config)
    $env:COMIC_PIPELINE_WORKSPACE = [string]$Config.Workspace
    $env:COMIC_PIPELINE_COMFY_ROOT = [string]$Config.ComfyRoot
    $env:COMIC_PIPELINE_COMFY_URL = [string]$Config.ComfyUrl
    $env:COMIC_PIPELINE_COMFY_OUTPUT_ROOT = [string]$Config.ComfyOutputRoot
    $env:COMIC_PIPELINE_OUTPUT_ROOT = [string]$Config.OutputRoot
    $env:COMIC_PIPELINE_NOVEL_PATH = [string]$Config.NovelPath
    $env:COMIC_PIPELINE_IMAGE_ENV_PATH = [string]$Config.ImageEnvPath
    $env:COMIC_PIPELINE_IMAGE_BACKEND = [string]$Config.ImageBackend
    $env:COMIC_PIPELINE_COMFY_CHECKPOINT = [string]$Config.ComfyCheckpoint
    $env:COMIC_PIPELINE_COMFY_LORA_NAME = [string]$Config.ComfyLoraName
    $env:COMIC_PIPELINE_COMFY_LORA_STRENGTH_MODEL = [string]$Config.ComfyLoraStrengthModel
    $env:COMIC_PIPELINE_COMFY_LORA_STRENGTH_CLIP = [string]$Config.ComfyLoraStrengthClip
    $env:COMIC_PIPELINE_COMFY_CONTROLNET_NAME = [string]$Config.ComfyControlnetName
    $env:COMIC_PIPELINE_COMFY_CONTROLNET_STRENGTH = [string]$Config.ComfyControlnetStrength
    $env:COMIC_PIPELINE_COMFY_CONTROLNET_START = [string]$Config.ComfyControlnetStart
    $env:COMIC_PIPELINE_COMFY_CONTROLNET_END = [string]$Config.ComfyControlnetEnd
    $env:COMIC_PIPELINE_COMFY_STEPS = [string]$Config.ComfySteps
    $env:COMIC_PIPELINE_COMFY_CFG = [string]$Config.ComfyCfg
    $env:COMIC_PIPELINE_COMFY_SAMPLER = [string]$Config.ComfySampler
    $env:COMIC_PIPELINE_COMFY_SCHEDULER = [string]$Config.ComfyScheduler
    $env:COMIC_PIPELINE_DATABASE_URL = [string]$Config.DatabaseUrl
    $env:COMIC_PIPELINE_TEXT_MODEL = [string]$Config.TextModel
    $env:COMIC_PIPELINE_IMAGE_MODEL = [string]$Config.ImageModel
    $env:COMIC_PIPELINE_IMAGE_QUALITY = [string]$Config.ImageQuality
    $env:COMIC_PIPELINE_PYTHON_PATH = [string]$Config.PythonPath
    $env:COMIC_PIPELINE_DEFAULT_PAGES = [string]$Config.DefaultPages
    $env:COMIC_PIPELINE_ENCODING = [string]$Config.Encoding
    $env:COMIC_PIPELINE_ACTIVE_PROJECT = [string]$Config.ActiveProject
}

function Get-ComicPipelinePython {
    param($Config)
    $pythonPath = [string]$Config.PythonPath
    if ($pythonPath -and (Test-Path -LiteralPath $pythonPath)) {
        return $pythonPath
    }
    if ($env:COMIC_PIPELINE_PYTHON_PATH -and (Test-Path -LiteralPath $env:COMIC_PIPELINE_PYTHON_PATH)) {
        return $env:COMIC_PIPELINE_PYTHON_PATH
    }
    return "python"
}

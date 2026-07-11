param(
    [string]$ComfyRoot = "G:\ComfyUI",
    [string]$ComfyUrl = "http://127.0.0.1:8188",
    [string]$NovelPath = "",
    [string]$TextApiKey = "",
    [string]$TextBaseUrl = "",
    [string]$ImageApiKey = "",
    [string]$ImageBaseUrl = "",
    [string]$DatabaseUrl = "postgresql://comic_pipeline:comic_pipeline@127.0.0.1:54329/comic_pipeline",
    [string]$TextModel = "gpt-4.1-mini",
    [int]$TextModelTimeout = 300,
    [string]$TextModelStream = "true",
    [string]$ImageModel = "gpt-image-2",
    [ValidateSet("auto", "low", "medium", "high")]
    [string]$ImageQuality = "auto",
    [int]$DefaultPages = 8,
    [string]$Encoding = "gb18030",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$configDir = Join-Path $root "config"
$envPath = Join-Path $configDir ".env"
$textEnvPath = Join-Path $configDir "text.env"
$imageEnvPath = Join-Path $configDir "image.env"
New-Item -ItemType Directory -Path $configDir -Force | Out-Null

if ((Test-Path -LiteralPath $envPath) -and -not $Force) {
    throw "Config already exists: $envPath. Use -Force to overwrite."
}
if (-not $NovelPath) {
    $defaultNovel = Join-Path $root "novel.txt"
    if (Test-Path -LiteralPath $defaultNovel) {
        $NovelPath = $defaultNovel
    }
}

@(
    "COMIC_PIPELINE_WORKSPACE=$root",
    "COMIC_PIPELINE_COMFY_ROOT=$ComfyRoot",
    "COMIC_PIPELINE_COMFY_URL=$ComfyUrl",
    "COMIC_PIPELINE_OUTPUT_ROOT=$(Join-Path $ComfyRoot 'output\ComicPipeline')",
    "COMIC_PIPELINE_COMFY_OUTPUT_ROOT=$(Join-Path $ComfyRoot 'output')",
    "COMIC_PIPELINE_NOVEL_PATH=$NovelPath",
    "COMIC_PIPELINE_TEXT_ENV_PATH=$textEnvPath",
    "COMIC_PIPELINE_IMAGE_ENV_PATH=$imageEnvPath",
    "COMIC_PIPELINE_DATABASE_URL=$DatabaseUrl",
    "COMIC_PIPELINE_TEXT_MODEL=$TextModel",
    "COMIC_PIPELINE_TEXT_MODEL_TIMEOUT=$TextModelTimeout",
    "COMIC_PIPELINE_TEXT_MODEL_STREAM=$TextModelStream",
    "COMIC_PIPELINE_IMAGE_MODEL=$ImageModel",
    "COMIC_PIPELINE_IMAGE_QUALITY=$ImageQuality",
    "COMIC_PIPELINE_PYTHON_PATH=python",
    "COMIC_PIPELINE_DEFAULT_PAGES=$DefaultPages",
    "COMIC_PIPELINE_ENCODING=$Encoding",
    "COMIC_PIPELINE_ACTIVE_PROJECT=sou_shen_ji"
) | Set-Content -LiteralPath $envPath -Encoding UTF8

if (-not (Test-Path -LiteralPath $textEnvPath) -or $Force) {
    @(
        "OPENAI_API_KEY=$TextApiKey",
        "OPENAI_BASE_URL=$TextBaseUrl"
    ) | Set-Content -LiteralPath $textEnvPath -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $imageEnvPath) -or $Force) {
    @(
        "OPENAI_API_KEY=$ImageApiKey",
        "OPENAI_BASE_URL=$ImageBaseUrl"
    ) | Set-Content -LiteralPath $imageEnvPath -Encoding UTF8
}

Write-Output "Wrote $envPath"
Write-Output "Wrote $textEnvPath"
Write-Output "Wrote $imageEnvPath"

param(
    [Parameter(Mandatory = $true)]
    [string]$WorkflowPath,
    [string]$KeyPath = "",
    [string]$ComfyUrl = "http://127.0.0.1:8188"
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if (-not $KeyPath) {
    $KeyPath = $comicConfig.ImageEnvPath
}
if ($ComfyUrl -eq "http://127.0.0.1:8188" -and $comicConfig.ComfyUrl) {
    $ComfyUrl = $comicConfig.ComfyUrl
}

if (-not (Test-Path -LiteralPath $WorkflowPath)) {
    throw "Workflow not found: $WorkflowPath"
}
if (-not (Test-Path -LiteralPath $KeyPath)) {
    throw "Key file not found: $KeyPath"
}

$comfyKeyDir = Join-Path $comicConfig.ComfyRoot ".comic-pipeline"
$comfyKeyPath = Join-Path $comfyKeyDir "image.env"
New-Item -ItemType Directory -Path $comfyKeyDir -Force | Out-Null
Copy-Item -LiteralPath $KeyPath -Destination $comfyKeyPath -Force
$workflowKeyPath = ".comic-pipeline/image.env"

$keyText = Get-Content -LiteralPath $KeyPath -Raw -Encoding UTF8
$baseUrl = [regex]::Match($keyText, '"baseURL"\s*:\s*"([^"]+)"').Groups[1].Value
if (-not $baseUrl) {
    $baseUrl = [regex]::Match($keyText, '"base_url"\s*:\s*"([^"]+)"').Groups[1].Value
}
if (-not $baseUrl) {
    $baseUrl = [regex]::Match($keyText, "'baseURL'\s*:\s*'([^']+)'").Groups[1].Value
}
if (-not $baseUrl) {
    $baseUrl = [regex]::Match($keyText, "(?m)^\s*(?:OPENAI_BASE_URL|BASE_URL)\s*=\s*([^\r\n]+)").Groups[1].Value
}

$workflow = Get-Content -LiteralPath $WorkflowPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($node in $workflow.prompt.PSObject.Properties.Value) {
    if ($node.class_type -eq "OpenAICompatibleImageGenerate") {
        if ($baseUrl) {
            $node.inputs | Add-Member -NotePropertyName "base_url" -NotePropertyValue $baseUrl.Trim() -Force
        }
        if ($node.inputs.PSObject.Properties.Name -contains "api_key") {
            $node.inputs.PSObject.Properties.Remove("api_key")
        }
        $node.inputs | Add-Member -NotePropertyName "api_key_env_path" -NotePropertyValue $workflowKeyPath -Force
    }
}

$body = $workflow | ConvertTo-Json -Depth 20
$bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
$result = Invoke-RestMethod -Uri "$ComfyUrl/prompt" -Method Post -Body $bodyBytes -ContentType "application/json; charset=utf-8" -TimeoutSec 30
Write-Output "$WorkflowPath -> prompt_id=$($result.prompt_id)"

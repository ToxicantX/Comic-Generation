param(
    [string]$PlanPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_ep01_page01_plan.json",
    [string]$WorkflowDir = "E:\workspace\ComfyUIProjects\workflows\comic",
    [string]$ResultPath = "E:\workspace\ComfyUIProjects\manifests\ssj_comic_ep01_page01_workflows.json",
    [string]$ImageModel = "gpt-image-2",
    [string]$ImageSize = "1024x1536",
    [switch]$AutoImageSize,
    [switch]$UseFallbackPrompts,
    [string]$EpisodePlanPath = "",
    [switch]$DisableReferenceImages
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if ($PlanPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_ep01_page01_plan.json") { $PlanPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_ep01_page01_plan.json" }
if ($WorkflowDir -eq "E:\workspace\ComfyUIProjects\workflows\comic") { $WorkflowDir = Join-Path $comicConfig.Workspace "workflows\comic" }
if ($ResultPath -eq "E:\workspace\ComfyUIProjects\manifests\ssj_comic_ep01_page01_workflows.json") { $ResultPath = Join-Path $comicConfig.Workspace "manifests\ssj_comic_ep01_page01_workflows.json" }
if ($ImageModel -eq "gpt-image-2" -and $comicConfig.ImageModel) { $ImageModel = $comicConfig.ImageModel }

if (-not (Test-Path -LiteralPath $PlanPath)) {
    throw "Plan file not found: $PlanPath"
}

$plan = Get-Content -Path $PlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
$assetAliases = $null
if (-not $EpisodePlanPath -and $plan.episode_id -match 'EP(\d+)') {
    $episodeNumber = [int]$Matches[1]
    $candidate = Join-Path (Split-Path $PlanPath) ("ssj_comic_episode{0:D2}_pages.json" -f $episodeNumber)
    if (Test-Path -LiteralPath $candidate) {
        $EpisodePlanPath = $candidate
    }
}
if ($EpisodePlanPath -and (Test-Path -LiteralPath $EpisodePlanPath)) {
    $episodePlan = Get-Content -Path $EpisodePlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($episodePlan.asset_aliases) {
        $assetAliases = $episodePlan.asset_aliases
    }
}
$negativeImage = if ($plan.negative_prompt) { [string]$plan.negative_prompt } else { "text, watermark, logo, distorted hands, melted face" }
$globalPrompt = if ($plan.global_prompt_block) { [string]$plan.global_prompt_block } else { "" }
$created = @()

New-Item -ItemType Directory -Path $WorkflowDir -Force | Out-Null

function Get-PanelImageSize {
    param(
        $Panel,
        [string]$DefaultImageSize,
        [bool]$UseAutoImageSize
    )

    if (-not $UseAutoImageSize) {
        return $DefaultImageSize
    }
    if (-not $Panel.layout) {
        return $DefaultImageSize
    }

    $width = [double]$Panel.layout.w
    $height = [double]$Panel.layout.h
    if ($width -le 0 -or $height -le 0) {
        return $DefaultImageSize
    }

    $ratio = $width / $height
    if ($ratio -ge 1.25) {
        return "1536x1024"
    }
    if ($ratio -le 0.80) {
        return "1024x1536"
    }
    return "1024x1024"
}

foreach ($panel in $plan.panels) {
    $suffix = ($panel.panel_id -replace '[^A-Za-z0-9_]+', '_').ToLowerInvariant()
    $workflowVariant = if ($UseFallbackPrompts) { "fallback" } else { "image" }
    $workflowPath = Join-Path $WorkflowDir "$($suffix)_$($workflowVariant)_v001.json"
    $filenamePrefix = if ($UseFallbackPrompts -and $panel.fallback_filename_prefix) {
        [string]$panel.fallback_filename_prefix
    } else {
        [string]$panel.filename_prefix
    }
    $expectedImagePath = Join-Path $comicConfig.ComfyOutputRoot "$($filenamePrefix)_00001_.png"
    $panelPrompt = if ($UseFallbackPrompts -and $panel.fallback_prompt) {
        [string]$panel.fallback_prompt
    } else {
        [string]$panel.prompt
    }
    $panelImageSize = Get-PanelImageSize -Panel $panel -DefaultImageSize $ImageSize -UseAutoImageSize ([bool]$AutoImageSize)
    $prompt = (($globalPrompt, $panelPrompt) | Where-Object { $_ }) -join "`n`n"
    $referenceAlias = if ($panel.PSObject.Properties.Name -contains "reference_alias") { [string]$panel.reference_alias } else { "" }
    $referenceImage = ""
    if (-not $DisableReferenceImages) {
        if ($UseFallbackPrompts -and ($panel.PSObject.Properties.Name -contains "fallback_reference_image") -and $panel.fallback_reference_image) {
            $referenceImage = [string]$panel.fallback_reference_image
        }
        if (-not $referenceImage -and ($panel.PSObject.Properties.Name -contains "reference_image") -and $panel.reference_image) {
            $referenceImage = [string]$panel.reference_image
        }
        if (-not $referenceImage -and $referenceAlias -and $assetAliases -and ($assetAliases.PSObject.Properties.Name -contains $referenceAlias)) {
            $referenceImage = [string]$assetAliases.$referenceAlias
        }
    }

    $workflow = [ordered]@{
        client_id = "codex-longform-comic"
        prompt = [ordered]@{
            "1" = [ordered]@{
                class_type = "OpenAICompatibleImageGenerate"
                inputs = [ordered]@{
                    prompt = $prompt
                    model = $ImageModel
                    size = $panelImageSize
                    quality = $comicConfig.ImageQuality
                    negative_prompt = $negativeImage
                    api_key_env_path = ".comic-pipeline/image.env"
                }
            }
            "2" = [ordered]@{
                class_type = "SaveImage"
                inputs = [ordered]@{
                    images = @("1", 0)
                    filename_prefix = $filenamePrefix
                }
            }
        }
    }

    if ($referenceImage) {
        $workflow.prompt."1".inputs.reference_image_paths = $referenceImage
    }

    $workflow | ConvertTo-Json -Depth 20 | Set-Content -Path $workflowPath -Encoding UTF8

    $created += [ordered]@{
        panel_id = $panel.panel_id
        order = $panel.order
        workflow = $workflowPath
        expected_panel_path = $expectedImagePath
        filename_prefix = $filenamePrefix
        image_size = $panelImageSize
        reference_alias = $referenceAlias
        reference_image = $referenceImage
        fallback = [bool]$UseFallbackPrompts
    }
}

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    project = $plan.project
    episode_id = $plan.episode_id
    page_id = $plan.page_id
    plan_path = $PlanPath
    workflow_dir = $WorkflowDir
    episode_plan_path = $EpisodePlanPath
    image_model = $ImageModel
    image_size = $ImageSize
    auto_image_size = [bool]$AutoImageSize
    fallback = [bool]$UseFallbackPrompts
    created = $created
    next_steps = @(
        "Run each workflow with scripts\\run_image_workflow_and_wait.ps1.",
        "Assemble the page with scripts\\build_comic_page_from_panels.ps1 after panel images exist."
    )
}

New-Item -ItemType Directory -Path (Split-Path $ResultPath) -Force | Out-Null
$result | ConvertTo-Json -Depth 12 | Set-Content -Path $ResultPath -Encoding UTF8
$result | ConvertTo-Json -Depth 12

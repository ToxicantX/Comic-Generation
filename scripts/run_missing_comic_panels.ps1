param(
    [Parameter(Mandatory = $true)]
    [string]$WorkflowResultPath,
    [string]$RunResultDir = "",
    [int]$RetryCount = 0,
    [int]$PollSeconds = 5,
    [int]$MaxPolls = 180,
    [int]$CooldownSeconds = 45,
    [string]$RunLabel = "",
    [string[]]$PanelIds = @()
)

. "$PSScriptRoot\comic_pipeline_config.ps1"
$comicConfig = Get-ComicPipelineConfig
Set-ComicPipelineProcessEnv -Config $comicConfig
if (-not $RunResultDir) {
    $RunResultDir = Join-Path $comicConfig.Workspace "manifests\comic_runs"
}

if (-not (Test-Path -LiteralPath $WorkflowResultPath)) {
    throw "Workflow result file not found: $WorkflowResultPath"
}

New-Item -ItemType Directory -Path $RunResultDir -Force | Out-Null
$workflowResult = Get-Content -Path $WorkflowResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
$safeRunLabel = ($RunLabel -replace '[^A-Za-z0-9_]+', '_').ToLowerInvariant().Trim("_")
$selectedPanelIds = @($PanelIds | ForEach-Object { ([string]$_).Split(",") } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$runs = @()

foreach ($panel in $workflowResult.created) {
    $panelId = [string]$panel.panel_id
    if ($selectedPanelIds.Count -gt 0 -and $selectedPanelIds -notcontains $panelId) {
        continue
    }
    $expectedPanelPath = [string]$panel.expected_panel_path
    $workflowPath = [string]$panel.workflow
    $exists = $expectedPanelPath -and (Test-Path -LiteralPath $expectedPanelPath)
    $run = [ordered]@{
        panel_id = $panelId
        workflow = $workflowPath
        expected_panel_path = $expectedPanelPath
        skipped_existing = $exists
        completed = $exists
        attempts = @()
    }

    if ($exists) {
        $runs += $run
        continue
    }

    for ($attempt = 1; $attempt -le [Math]::Max(1, $RetryCount + 1); $attempt++) {
        if ($CooldownSeconds -gt 0 -and ($runs.Count -gt 0 -or $attempt -gt 1)) {
            Start-Sleep -Seconds $CooldownSeconds
        }

        $safePanelId = ($panelId -replace '[^A-Za-z0-9_]+', '_').ToLowerInvariant()
        $attemptStem = if ($safeRunLabel) { "$($safePanelId)_$($safeRunLabel)_missing_attempt$attempt" } else { "$($safePanelId)_missing_attempt$attempt" }
        $attemptResultPath = Join-Path $RunResultDir "$attemptStem.json"
        $output = & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run_image_workflow_and_wait.ps1") `
            -WorkflowPath $workflowPath `
            -ShotId $panelId `
            -ResultPath $attemptResultPath `
            -PollSeconds $PollSeconds `
            -MaxPolls $MaxPolls

        $exitCode = $LASTEXITCODE
        $attemptResult = $null
        if (Test-Path -LiteralPath $attemptResultPath) {
            $attemptResult = Get-Content -Path $attemptResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        $run.attempts += [ordered]@{
            attempt = $attempt
            exit_code = $exitCode
            result_path = $attemptResultPath
            status = if ($attemptResult) { $attemptResult.status } else { "missing_result" }
            completed = if ($attemptResult) { [bool]$attemptResult.completed } else { $false }
            error = if ($attemptResult) { $attemptResult.error } else { ($output -join "`n") }
        }

        if (($attemptResult -and [bool]$attemptResult.completed) -or (Test-Path -LiteralPath $expectedPanelPath)) {
            $run.completed = $true
            break
        }
    }

    $runs += $run
}

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    workflow_result_path = $WorkflowResultPath
    run_label = $RunLabel
    page_id = $workflowResult.page_id
    selected_panel_ids = $selectedPanelIds
    completed = ($runs.Count -gt 0 -and (($runs | Where-Object { -not $_.completed }).Count -eq 0))
    runs = $runs
}

$pageId = if ($workflowResult.page_id) { [string]$workflowResult.page_id } else { "comic_page" }
$resultStem = if ($safeRunLabel) { "$($pageId)_$($safeRunLabel)_missing_panels_run" } else { "$($pageId)_missing_panels_run" }
$resultPath = Join-Path $RunResultDir "$resultStem.json"
$result | ConvertTo-Json -Depth 20 | Set-Content -Path $resultPath -Encoding UTF8
$result | ConvertTo-Json -Depth 20

if (-not $result.completed) {
    exit 1
}

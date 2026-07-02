param(
    [string]$ResultPath = "",
    [string]$ComfyUrl = "http://127.0.0.1:8188",
    [switch]$SkipComfyProbe,
    [switch]$AllowBusyQueue
)

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $ResultPath) {
    $ResultPath = Join-Path $root "manifests\prompt_secret_hygiene_check.json"
}

$scriptPaths = @(
    (Join-Path $root "scripts\submit_image_workflow.ps1"),
    (Join-Path $root "scripts\run_image_workflow_and_wait.ps1"),
    (Join-Path $root "scripts\run_missing_comic_panels.ps1"),
    (Join-Path $root "scripts\run_comic_episode_auto_batches.ps1")
)

$result = [ordered]@{
    updated = (Get-Date).ToString("s")
    allow_busy_queue = [bool]$AllowBusyQueue
    queue_idle = $null
    secret_ok = $null
    checks = @()
    ok = $true
}

function Add-Check {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Message,
        [bool]$AffectsOverall = $true
    )
    $script:result.checks += [ordered]@{
        name = $Name
        ok = $Ok
        message = $Message
        affects_overall = $AffectsOverall
    }
    if (-not $Ok -and $AffectsOverall) {
        $script:result.ok = $false
    }
}

foreach ($path in $scriptPaths) {
    if (-not (Test-Path -LiteralPath $path)) {
        Add-Check -Name "script_exists:$path" -Ok $false -Message "Missing script."
        continue
    }
    $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $injectsPlainApiKey = $text -match 'NotePropertyName\s+"api_key"\s+-NotePropertyValue\s+\$apiKey'
    $parsesImageApiKeyInSubmit = ([System.IO.Path]::GetFileName($path) -eq "submit_image_workflow.ps1") -and ($text -match '"apiKey"|OPENAI_API_KEY|API_KEYS')
    Add-Check -Name "no_plain_api_key_injection:$([System.IO.Path]::GetFileName($path))" -Ok (-not $injectsPlainApiKey) -Message "Submit scripts must not inject plaintext api_key into Comfy prompt inputs."
    Add-Check -Name "no_image_key_parsing_in_submit:$([System.IO.Path]::GetFileName($path))" -Ok (-not $parsesImageApiKeyInSubmit) -Message "Image submit should pass api_key_env_path and let the Comfy node read credentials at runtime."
}

if ($SkipComfyProbe) {
    Add-Check -Name "comfy_probe_skipped" -Ok $true -Message "Skipped Comfy queue/history probe." -AffectsOverall:$false
} else {
try {
    $queue = Invoke-RestMethod -Uri "$ComfyUrl/queue" -TimeoutSec 5
    $history = Invoke-RestMethod -Uri "$ComfyUrl/history" -TimeoutSec 5
    $queueJson = $queue | ConvertTo-Json -Depth 80
    $historyJson = $history | ConvertTo-Json -Depth 80
    foreach ($pattern in @("sk-", "Bearer ", "AIza", '"apiKey"')) {
        Add-Check -Name "queue_no_secret_pattern:$pattern" -Ok (-not ($queueJson -match [regex]::Escape($pattern))) -Message "Comfy queue should not contain secret pattern $pattern"
        Add-Check -Name "history_no_secret_pattern:$pattern" -Ok (-not ($historyJson -match [regex]::Escape($pattern))) -Message "Comfy history should not contain secret pattern $pattern"
    }
    $queueIdle = ((@($queue.queue_running).Count -eq 0) -and (@($queue.queue_pending).Count -eq 0))
    $result.queue_idle = [bool]$queueIdle
    Add-Check -Name "queue_empty" -Ok $queueIdle -Message "Comfy queue should be empty before unattended pipeline steps." -AffectsOverall:(-not [bool]$AllowBusyQueue)
} catch {
    Add-Check -Name "comfy_probe" -Ok $false -Message $_.Exception.Message
}
}

$secretFailures = @($result.checks | Where-Object {
    -not $_.ok -and $_.name -ne "queue_empty"
})
$result.secret_ok = (@($secretFailures).Count -eq 0)

New-Item -ItemType Directory -Path (Split-Path $ResultPath) -Force | Out-Null
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ResultPath -Encoding UTF8
$result | ConvertTo-Json -Depth 12

if (-not $result.ok) {
    exit 1
}

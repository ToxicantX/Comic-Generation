param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8199,
    [switch]$SkipDatabase,
    [switch]$SkipGenerationBackend
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$server = Join-Path $root "console\server.py"
$configPath = Join-Path $root "config\.env"
$logDir = Join-Path $root "logs"
$postgresScript = Join-Path $root "start_postgres.ps1"

if (-not (Test-Path -LiteralPath $server)) {
    throw "Console server not found: $server"
}

function Read-ComicEnv {
    param([string]$Path)
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $parts = $line.Split("=", 2)
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $values
}

function Test-HttpReady {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return [int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Start-GenerationBackend {
    if ($SkipGenerationBackend) {
        Write-Host "Generation backend autostart skipped."
        return
    }

    $config = Read-ComicEnv -Path $configPath
    $imageBackend = if ($env:COMIC_PIPELINE_IMAGE_BACKEND) {
        $env:COMIC_PIPELINE_IMAGE_BACKEND
    } else {
        $config["COMIC_PIPELINE_IMAGE_BACKEND"]
    }
    if ([string]::IsNullOrWhiteSpace($imageBackend)) {
        $imageBackend = "direct_api"
    }
    if ($imageBackend -ne "comfyui") {
        Write-Host "Direct image API selected; ComfyUI autostart is not required."
        return
    }
    $comfyRoot = $config["COMIC_PIPELINE_COMFY_ROOT"]
    if ([string]::IsNullOrWhiteSpace($comfyRoot)) {
        $comfyRoot = "G:\ComfyUI"
    }
    $comfyUrl = $config["COMIC_PIPELINE_COMFY_URL"]
    if ([string]::IsNullOrWhiteSpace($comfyUrl)) {
        $comfyUrl = "http://127.0.0.1:8188"
    }

    if (Test-HttpReady -Url $comfyUrl) {
        Write-Host "Generation backend already running: $comfyUrl"
        return
    }

    $mainPy = Join-Path $comfyRoot "main.py"
    if (-not (Test-Path -LiteralPath $mainPy)) {
        Write-Warning "Generation backend entry not found: $mainPy"
        return
    }

    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $pythonExe = Join-Path $comfyRoot "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $pythonExe = "python"
    }

    $uri = [Uri]$comfyUrl
    $backendHost = if ([string]::IsNullOrWhiteSpace($uri.Host)) { "127.0.0.1" } else { $uri.Host }
    $backendPort = if ($uri.Port -gt 0) { $uri.Port } else { 8188 }
    $stdout = Join-Path $logDir "generation-backend.out.log"
    $stderr = Join-Path $logDir "generation-backend.err.log"

    Write-Host "Starting generation backend: $comfyUrl"
    Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @($mainPy, "--listen", $backendHost, "--port", [string]$backendPort) `
        -WorkingDirectory $comfyRoot `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden | Out-Null

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        if (Test-HttpReady -Url $comfyUrl) {
            Write-Host "Generation backend ready: $comfyUrl"
            return
        }
    }
    Write-Warning "Generation backend was started but did not respond within 30 seconds. Logs: $stdout / $stderr"
}

function Start-Database {
    if ($SkipDatabase) {
        Write-Host "PostgreSQL autostart skipped."
        return
    }
    if (-not (Test-Path -LiteralPath $postgresScript)) {
        Write-Warning "PostgreSQL startup script not found: $postgresScript"
        return
    }
    try {
        powershell -ExecutionPolicy Bypass -File $postgresScript
    } catch {
        Write-Warning "PostgreSQL autostart failed: $($_.Exception.Message)"
        Write-Warning "You can configure an existing database with COMIC_PIPELINE_DATABASE_URL."
    }
}

Start-Database
Start-GenerationBackend

$url = "http://${HostName}:$Port"
Write-Host "Starting Comic Pipeline Console: $url"
Write-Host "Package root: $root"
python $server --host $HostName --port $Port

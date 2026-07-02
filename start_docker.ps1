param(
    [switch]$Build,
    [switch]$SkipHealthCheck
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Docker {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        throw "Docker is not installed or not in PATH. Install Docker Desktop first."
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is not running."
    }
}

function Copy-ExampleIfMissing {
    param(
        [string]$ExamplePath,
        [string]$TargetPath,
        [string]$Label
    )
    if (Test-Path -LiteralPath $TargetPath) {
        Write-Host "$Label exists: $TargetPath"
        return
    }
    if (-not (Test-Path -LiteralPath $ExamplePath)) {
        throw "$Label example not found: $ExamplePath"
    }
    Copy-Item -LiteralPath $ExamplePath -Destination $TargetPath
    Write-Host "$Label created from example: $TargetPath"
}

function Test-PortListening {
    param([int]$Port)
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return @($connections).Count -gt 0
}

Set-Location $root
Test-Docker

Copy-ExampleIfMissing `
    -ExamplePath (Join-Path $root "config\.env.docker.example") `
    -TargetPath (Join-Path $root "config\.env.docker") `
    -Label "Docker config"

Copy-ExampleIfMissing `
    -ExamplePath (Join-Path $root "config\text.env.example") `
    -TargetPath (Join-Path $root "config\text.env") `
    -Label "Text API config"

Copy-ExampleIfMissing `
    -ExamplePath (Join-Path $root "config\image.env.example") `
    -TargetPath (Join-Path $root "config\image.env") `
    -Label "Image API config"

if (-not (Test-Path -LiteralPath "G:\ComfyUI")) {
    Write-Warning "G:\ComfyUI was not found. Edit docker-compose.yml volume mapping and config\.env.docker before generating images."
}

$existingConsole = docker ps --format "{{.Names}}" | Where-Object { $_ -eq "comic-pipeline-console" }
if (-not $existingConsole -and (Test-PortListening -Port 8199)) {
    throw "Port 8199 is already in use. Stop the existing local console first, then run this script again."
}

$composeArgs = @("compose", "up", "-d")
if ($Build) {
    $composeArgs += "--build"
}

docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed."
}

Write-Host ""
Write-Host "Console URL: http://127.0.0.1:8199"
Write-Host "PostgreSQL URL from host: postgresql://comic_pipeline:comic_pipeline@127.0.0.1:55432/comic_pipeline"
Write-Host "ComfyUI backend expected at: http://127.0.0.1:8188"
Write-Host ""

if (-not $SkipHealthCheck) {
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8199/" -UseBasicParsing -TimeoutSec 2
            if ([int]$response.StatusCode -ge 200 -and [int]$response.StatusCode -lt 500) {
                Write-Host "Console health check passed."
                exit 0
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    Write-Warning "Console did not respond within 45 seconds. Check logs with: docker compose logs --tail=100 comic-console"
}

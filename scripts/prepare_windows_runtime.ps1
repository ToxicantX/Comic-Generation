param(
    [string]$PythonVersion = "3.12.10"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$RuntimeRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot "build\runtime"))
$PythonRoot = [IO.Path]::GetFullPath((Join-Path $RuntimeRoot "python"))
$AppRoot = [IO.Path]::GetFullPath((Join-Path $RuntimeRoot "app"))
$CacheRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime-cache"))
$ExpectedPrefix = $RuntimeRoot.TrimEnd('\') + '\'

if (-not $PythonRoot.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    -not $AppRoot.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Runtime target escaped the project build directory."
}

$ArchiveName = "python-$PythonVersion-embed-amd64.zip"
$ArchivePath = Join-Path $CacheRoot $ArchiveName
$DownloadUrl = "https://www.python.org/ftp/python/$PythonVersion/$ArchiveName"

New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
    Write-Host "Downloading Python $PythonVersion embedded runtime..."
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $ArchivePath
}

if (Test-Path -LiteralPath $PythonRoot) {
    Remove-Item -LiteralPath $PythonRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $PythonRoot | Out-Null
Expand-Archive -LiteralPath $ArchivePath -DestinationPath $PythonRoot -Force

$PthPath = Join-Path $PythonRoot "python312._pth"
if (-not (Test-Path -LiteralPath $PthPath -PathType Leaf)) {
    throw "Unexpected embedded Python layout: $PthPath is missing."
}
@(
    "python312.zip"
    "."
    "Lib/site-packages"
    "../app/console"
    "../app/scripts"
    "import site"
) | Set-Content -LiteralPath $PthPath -Encoding ASCII

$SitePackages = Join-Path $PythonRoot "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $SitePackages | Out-Null
$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"

Write-Host "Installing Python runtime dependencies..."
py -3.12 -m pip install `
    --disable-pip-version-check `
    --ignore-installed `
    --no-compile `
    --upgrade `
    --target $SitePackages `
    --requirement $RequirementsPath

$PythonExecutable = Join-Path $PythonRoot "python.exe"
$env:PYTHONNOUSERSITE = "1"
& $PythonExecutable -I -c "import psycopg, PIL; print('portable-python-ok')"
if ($LASTEXITCODE -ne 0) {
    throw "Portable Python dependency validation failed."
}

if (Test-Path -LiteralPath $AppRoot) {
    Remove-Item -LiteralPath $AppRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path @(
    (Join-Path $AppRoot "console")
    (Join-Path $AppRoot "console\static")
    (Join-Path $AppRoot "scripts")
    (Join-Path $AppRoot "config")
) | Out-Null

Copy-Item -Path (Join-Path $ProjectRoot "console\*.py") -Destination (Join-Path $AppRoot "console")
Copy-Item -Path (Join-Path $ProjectRoot "console\static\*") -Destination (Join-Path $AppRoot "console\static") -Recurse
Copy-Item -Path (Join-Path $ProjectRoot "scripts\*.py") -Destination (Join-Path $AppRoot "scripts")
Copy-Item -Path (Join-Path $ProjectRoot "scripts\*.ps1") -Destination (Join-Path $AppRoot "scripts")
foreach ($Name in @(".env.example", "text.env.example", "image.env.example")) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "config\$Name") -Destination (Join-Path $AppRoot "config\$Name")
}
Copy-Item -LiteralPath (Join-Path $ProjectRoot "workflows") -Destination (Join-Path $AppRoot "workflows") -Recurse
Copy-Item -LiteralPath $RequirementsPath -Destination (Join-Path $AppRoot "requirements.txt")

& $PythonExecutable (Join-Path $AppRoot "console\server.py") --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Portable Python backend smoke test failed."
}

$Sha256 = [Security.Cryptography.SHA256]::Create()
$RequirementsStream = [IO.File]::OpenRead($RequirementsPath)
try {
    $RequirementsHash = (($Sha256.ComputeHash($RequirementsStream) | ForEach-Object { $_.ToString("x2") }) -join "")
}
finally {
    $RequirementsStream.Dispose()
    $Sha256.Dispose()
}

$Manifest = [ordered]@{
    python_version = $PythonVersion
    architecture = "amd64"
    requirements_sha256 = $RequirementsHash
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
}
$Manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $RuntimeRoot "runtime-manifest.json") -Encoding UTF8
Write-Host "Prepared portable Python runtime at $PythonRoot"

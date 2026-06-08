# Portable ffmpeg yuklab olish (winget kerak emas)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Zip = Join-Path $Root "ffmpeg-download.zip"
$Url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

Write-Host "ffmpeg yuklanmoqda..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing

Write-Host "Ochilmoqda..."
$Temp = Join-Path $Root "_ffmpeg_tmp"
if (Test-Path $Temp) { Remove-Item $Temp -Recurse -Force }
Expand-Archive -Path $Zip -DestinationPath $Temp -Force

$BinDir = Get-ChildItem -Path $Temp -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $BinDir) {
    Write-Host "Xato: zip ichida ffmpeg.exe topilmadi"
    exit 1
}

$Target = Join-Path $Root "ffmpeg\bin"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item $BinDir.FullName (Join-Path $Target "ffmpeg.exe") -Force
$Ffprobe = Join-Path $BinDir.DirectoryName "ffprobe.exe"
if (Test-Path $Ffprobe) {
    Copy-Item $Ffprobe (Join-Path $Target "ffprobe.exe") -Force
}

Remove-Item $Zip -Force -ErrorAction SilentlyContinue
Remove-Item $Temp -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "TAYYOR: $Target\ffmpeg.exe"
& (Join-Path $Target "ffmpeg.exe") -version | Select-Object -First 1

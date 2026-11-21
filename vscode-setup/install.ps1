# Restores VS Code settings, extensions and background image on a new machine.
# Usage (from the repo root): powershell -ExecutionPolicy Bypass -File vscode-setup\install.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Install VS Code if missing
$code = (Get-Command code -ErrorAction SilentlyContinue).Source
if (-not $code) {
  $code = Join-Path $env:LOCALAPPDATA "Programs\Microsoft VS Code\bin\code.cmd"
  if (-not (Test-Path $code)) {
    Write-Host "Installing VS Code with winget..."
    winget install --id Microsoft.VisualStudioCode -e --scope user --accept-package-agreements --accept-source-agreements
  }
  if (-not (Test-Path $code)) { throw "VS Code not found after install. Install it manually and re-run." }
}
$userDir = Join-Path $env:APPDATA "Code\User"
New-Item -ItemType Directory -Force -Path $userDir | Out-Null

# Background image -> Pictures
$pictures = [Environment]::GetFolderPath("MyPictures")
$img = Join-Path $pictures "fondo_ola.jpg"
Copy-Item (Join-Path $here "fondo_ola.jpg") $img -Force

# Settings, with the image path pointing to this machine
$settingsTarget = Join-Path $userDir "settings.json"
if (Test-Path $settingsTarget) { Copy-Item $settingsTarget "$settingsTarget.bak" -Force }
$imgUri = "file:///" + ($img -replace "\\", "/")
(Get-Content (Join-Path $here "settings.json") -Raw) `
  -replace "file:///C:/Users/[^/]+/Pictures/fondo_ola\.jpg", $imgUri |
  Set-Content $settingsTarget -Encoding UTF8

if (Test-Path (Join-Path $here "snippets")) {
  Copy-Item (Join-Path $here "snippets\*") (Join-Path $userDir "snippets") -Recurse -Force -ErrorAction SilentlyContinue
}

# Extensions
Get-Content (Join-Path $here "extensions.txt") | Where-Object { $_ } | ForEach-Object {
  & $code --install-extension $_ --force
}

Write-Host "Done. Restart VS Code; the 'background' extension may ask to apply changes."

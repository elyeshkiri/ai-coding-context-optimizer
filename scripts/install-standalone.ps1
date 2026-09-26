$ErrorActionPreference = "Stop"

$repo = "elyeshkiri/ai-coding-context-optimizer"
$version = if ($env:ACCO_VERSION) { $env:ACCO_VERSION } else { "latest" }
$installDir = if ($env:ACCO_INSTALL_DIR) {
    $env:ACCO_INSTALL_DIR
} else {
    Join-Path $env:LOCALAPPDATA "ACCO\bin"
}

$base = if ($version -eq "latest") {
    "https://github.com/$repo/releases/latest/download"
} else {
    "https://github.com/$repo/releases/download/$version"
}
$asset = "acco-windows-x86_64.exe"

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("acco-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $temp | Out-Null
try {
    $binary = Join-Path $temp "acco.exe"
    $checksum = Join-Path $temp "$asset.sha256"
    Invoke-WebRequest -Uri "$base/$asset" -OutFile $binary
    Invoke-WebRequest -Uri "$base/$asset.sha256" -OutFile $checksum

    $expected = ((Get-Content $checksum -Raw).Trim() -split "\s+")[0].ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 $binary).Hash.ToLowerInvariant()
    if ($expected -ne $actual) {
        throw "Checksum verification failed."
    }

    New-Item -ItemType Directory -Force -Path $installDir | Out-Null
    Copy-Item -Force $binary (Join-Path $installDir "acco.exe")
    Write-Host "Installed ACCO to $installDir\acco.exe"
    Write-Host "Add $installDir to PATH if it is not already present."
    Write-Host "Next: cd <project>; acco setup"
} finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $temp
}

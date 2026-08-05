[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ToolchainFile = Join-Path $RepositoryRoot 'toolchains\desktop-windows-x64.json'
$Toolchains = Get-Content -LiteralPath $ToolchainFile -Raw | ConvertFrom-Json
$BuildRoot = Join-Path $RepositoryRoot '.desktop-build'
$ArtifactRoot = Join-Path $RepositoryRoot 'artifacts\windows-x64'
$VenvRoot = Join-Path $BuildRoot 'venv'
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'
$SidecarPath = Join-Path $RepositoryRoot 'src-tauri\binaries\radiology-backend-x86_64-pc-windows-msvc.exe'
$CargoManifest = Join-Path $RepositoryRoot 'src-tauri\Cargo.toml'
$CargoLock = Join-Path $RepositoryRoot 'src-tauri\Cargo.lock'
$PythonLock = Join-Path $RepositoryRoot 'backend\requirements-desktop.lock'
$TranscriptPath = Join-Path $ArtifactRoot 'build.log'
$StableInstaller = Join-Path $ArtifactRoot 'Radiology-Desktop_2.2.0_x64-setup.exe'
$PackagedSidecar = Join-Path $ArtifactRoot 'radiology-backend-x86_64-pc-windows-msvc.exe'
$PortableDirectory = Join-Path $ArtifactRoot 'Radiology-Desktop_2.2.0_x64-portable'
$PortableExecutable = Join-Path $PortableDirectory 'Radiology-Desktop.exe'
$PortableSidecar = Join-Path $PortableDirectory 'radiology-backend.exe'
$PortableZip = Join-Path $ArtifactRoot 'Radiology-Desktop_2.2.0_x64-portable.zip'
$ToolchainManifestPath = Join-Path $ArtifactRoot 'toolchain-manifest.json'
$BuildManifestPath = Join-Path $ArtifactRoot 'build-manifest.json'
$ChecksumsPath = Join-Path $ArtifactRoot 'SHA256SUMS.txt'

function Assert-Command {
    param([Parameter(Mandatory)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found."
    }
}

function Assert-ExactVersion {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Actual,
        [Parameter(Mandatory)][string]$Expected
    )
    if ($Actual -ne $Expected) {
        throw "$Name $Expected is required; found $Actual."
    }
}

function Enter-MsvcEnvironment {
    if (Get-Command cl.exe -ErrorAction SilentlyContinue) {
        return
    }
    $VsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $VsWhere)) {
        throw 'Microsoft Visual Studio Build Tools with the MSVC x64 toolchain are required.'
    }
    $InstallationPath = (& $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
    if (-not $InstallationPath) {
        throw 'MSVC x64 build tools were not found.'
    }
    $VsDevCmd = Join-Path $InstallationPath 'Common7\Tools\VsDevCmd.bat'
    $EnvironmentLines = & cmd.exe /s /c "`"$VsDevCmd`" -no_logo -arch=x64 -host_arch=x64 && set"
    foreach ($Line in $EnvironmentLines) {
        if ($Line -match '^([^=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
        }
    }
    Assert-Command 'cl.exe'
}

function Assert-WebView2 {
    $Locations = @(
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
        'HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    )
    $Location = $Locations | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Location) {
        throw 'Microsoft Edge WebView2 Runtime was not detected.'
    }
    return (Get-ItemProperty -LiteralPath $Location).pv
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath exited with code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

function Assert-WindowsExecutable {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Description
    )
    $Stream = [IO.File]::OpenRead($Path)
    try {
        $Header = [byte[]]::new(2)
        $HeaderRead = $Stream.Read($Header, 0, 2)
        if ($Stream.Length -lt 1048576 -or $HeaderRead -ne 2 -or $Header[0] -ne 0x4d -or $Header[1] -ne 0x5a) {
            throw "$Description is not a valid Windows executable."
        }
    }
    finally {
        $Stream.Dispose()
    }
}

function Test-SidecarExecutable {
    $SmokeRoot = Join-Path $BuildRoot 'smoke'
    New-Item -ItemType Directory -Path $SmokeRoot -Force | Out-Null
    $RuntimeFile = Join-Path $SmokeRoot 'runtime.json'
    $LogFile = Join-Path $SmokeRoot 'backend.log'
    Remove-Item -LiteralPath $RuntimeFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $LogFile -Force -ErrorAction SilentlyContinue
    $TokenBytes = [byte[]]::new(32)
    $Random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $Random.GetBytes($TokenBytes)
    }
    finally {
        $Random.Dispose()
    }
    $Token = -join ($TokenBytes | ForEach-Object { $_.ToString('x2') })

    $env:RADIOLOGY_DESKTOP_RUNTIME = 'true'
    $env:RADIOLOGY_UI_TOKEN = $Token
    $env:RADIOLOGY_RUNTIME_FILE = $RuntimeFile
    $env:RADIOLOGY_LOG_FILE = $LogFile
    $env:RADIOLOGY_PARENT_PID = [string]$PID
    $env:ALLOW_UNRESTRICTED_DATA_PATHS = 'true'
    $env:ALLOW_DATA_MUTATIONS = 'false'
    $env:WEBUI_STATE_DIR = Join-Path $SmokeRoot 'state'
    $env:CORS_ORIGINS = 'http://tauri.localhost,http://localhost:5173'

    $OriginalPath = $env:PATH
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    try {
        $Process = Start-Process -FilePath $SidecarPath -PassThru -WindowStyle Hidden
    }
    finally {
        $env:PATH = $OriginalPath
    }
    try {
        $Deadline = [DateTime]::UtcNow.AddSeconds(45)
        while (-not (Test-Path -LiteralPath $RuntimeFile)) {
            if ($Process.HasExited) {
                throw "Sidecar exited during smoke startup. See $LogFile"
            }
            if ([DateTime]::UtcNow -ge $Deadline) {
                throw "Sidecar handshake timed out. See $LogFile"
            }
            Start-Sleep -Milliseconds 100
        }
        $Runtime = Get-Content -LiteralPath $RuntimeFile -Raw | ConvertFrom-Json
        if ($Runtime.PSObject.Properties.Name -contains 'token') {
            throw 'Sidecar handshake must not contain the runtime token.'
        }
        $BaseUrl = "http://127.0.0.1:$($Runtime.port)"
        $Health = Invoke-RestMethod -Uri "$BaseUrl/api/health" -TimeoutSec 5
        if ($Health.status -ne 'ok') {
            throw 'Sidecar health response was not ready.'
        }

        try {
            Invoke-WebRequest -Uri "$BaseUrl/api/workspace" -TimeoutSec 5 | Out-Null
            throw 'Unauthenticated sidecar API request unexpectedly succeeded.'
        }
        catch {
            $StatusCode = [int]$_.Exception.Response.StatusCode
            if ($StatusCode -ne 401) {
                throw
            }
        }

        Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/desktop/shutdown" -Headers @{ Authorization = "Bearer $Token" } -TimeoutSec 5 | Out-Null
        if (-not $Process.WaitForExit(5000)) {
            throw 'Sidecar did not stop within five seconds after authenticated shutdown.'
        }
        if (Test-Path -LiteralPath $RuntimeFile) {
            throw 'Sidecar did not remove its handshake during shutdown.'
        }
    }
    finally {
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

$RunningOnWindows = [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $RunningOnWindows -or -not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
    throw 'The desktop build requires 64-bit Windows running 64-bit PowerShell.'
}
if (-not (Test-Path -LiteralPath $CargoLock)) {
    throw "Committed Cargo lock not found at $CargoLock"
}
if (-not (Test-Path -LiteralPath $PythonLock)) {
    throw "Hashed Python lock not found at $PythonLock"
}

New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
Remove-Item -LiteralPath $PortableDirectory -Recurse -Force -ErrorAction SilentlyContinue
foreach ($StaleArtifact in @(
    $StableInstaller,
    $PackagedSidecar,
    $PortableZip,
    $ToolchainManifestPath,
    $BuildManifestPath,
    $ChecksumsPath,
    (Join-Path $ArtifactRoot 'Radiology-Desktop_2.2.0_x64-setup.exe.sha256')
)) {
    Remove-Item -LiteralPath $StaleArtifact -Force -ErrorAction SilentlyContinue
}
$BuildSucceeded = $false
Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null

try {
    Assert-Command 'python'
    Assert-Command 'node'
    Assert-Command 'npm'
    Assert-Command 'cargo'
    Assert-Command 'rustc'
    Assert-Command 'git'
    Enter-MsvcEnvironment
    $WebView2Version = Assert-WebView2

    $PythonVersion = (& python -c 'import platform; print(platform.python_version())').Trim()
    $NodeVersion = (& node --version).Trim().TrimStart('v')
    $NpmVersion = (& npm --version).Trim()
    $RustVersion = ((& rustc --version) -split ' ')[1]
    $TauriVersion = ((& cargo tauri --version) -replace '^tauri-cli\s+', '').Trim()
    $MsvcCommand = Get-Command cl.exe
    $MsvcVersion = (Get-Item -LiteralPath $MsvcCommand.Source).VersionInfo.FileVersion
    Assert-ExactVersion 'Python' $PythonVersion $Toolchains.python
    Assert-ExactVersion 'Node.js' $NodeVersion $Toolchains.node
    Assert-ExactVersion 'Rust' $RustVersion $Toolchains.rust
    Assert-ExactVersion 'Tauri CLI' $TauriVersion $Toolchains.tauriCli

    $env:PYTHONHASHSEED = '0'
    $Commit = (& git -C $RepositoryRoot rev-parse HEAD).Trim()
    $env:SOURCE_DATE_EPOCH = (& git -C $RepositoryRoot log -1 --format=%ct).Trim()

    if (-not $SkipInstall) {
        Invoke-Checked 'npm' @('ci') (Join-Path $RepositoryRoot 'frontend')
    }
    if (-not $SkipTests) {
        Invoke-Checked 'npm' @('run', 'test') (Join-Path $RepositoryRoot 'frontend')
        Invoke-Checked 'npm' @('run', 'lint') (Join-Path $RepositoryRoot 'frontend')
    }
    Invoke-Checked 'npm' @('run', 'build') (Join-Path $RepositoryRoot 'frontend')

    if (-not $SkipInstall) {
        if (-not (Test-Path -LiteralPath $VenvPython)) {
            Invoke-Checked 'python' @('-m', 'venv', $VenvRoot) $RepositoryRoot
        }
        Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--require-hashes', '-r', $PythonLock) $RepositoryRoot
    }
    $PyInstallerVersion = (& $VenvPython -c 'import PyInstaller; print(PyInstaller.__version__)').Trim()
    Assert-ExactVersion 'PyInstaller' $PyInstallerVersion $Toolchains.pyinstaller

    if (-not $SkipTests) {
        Invoke-Checked $VenvPython @('-m', 'pytest', 'backend/tests') $RepositoryRoot
    }

    Remove-Item -LiteralPath $SidecarPath -Force -ErrorAction SilentlyContinue
    Invoke-Checked $VenvPython @(
        '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        '--distpath', (Join-Path $RepositoryRoot 'src-tauri\binaries'),
        '--workpath', (Join-Path $BuildRoot 'pyinstaller'),
        (Join-Path $RepositoryRoot 'backend\desktop-sidecar.spec')
    ) $RepositoryRoot
    Test-SidecarExecutable

    if (-not $SkipTests) {
        Invoke-Checked 'cargo' @('fmt', '--manifest-path', $CargoManifest, '--', '--check') $RepositoryRoot
        Invoke-Checked 'cargo' @('clippy', '--locked', '--manifest-path', $CargoManifest, '--target', $Toolchains.target, '--', '-D', 'warnings') $RepositoryRoot
        Invoke-Checked 'cargo' @('test', '--locked', '--manifest-path', $CargoManifest, '--target', $Toolchains.target) $RepositoryRoot
    }
    Invoke-Checked 'cargo' @('tauri', 'build', '--ci', '--target', $Toolchains.target, '--bundles', 'nsis') $RepositoryRoot

    $Installer = Get-ChildItem -LiteralPath (Join-Path $RepositoryRoot "src-tauri\target\$($Toolchains.target)\release\bundle\nsis") -Filter '*.exe' | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if (-not $Installer) {
        throw 'The NSIS installer was not produced.'
    }
    $ReleaseExecutable = Join-Path $RepositoryRoot "src-tauri\target\$($Toolchains.target)\release\radiology-desktop.exe"
    if (-not (Test-Path -LiteralPath $ReleaseExecutable)) {
        throw "The portable desktop executable was not produced at $ReleaseExecutable"
    }

    Copy-Item -LiteralPath $Installer.FullName -Destination $StableInstaller -Force
    Copy-Item -LiteralPath $SidecarPath -Destination $PackagedSidecar -Force
    New-Item -ItemType Directory -Path $PortableDirectory -Force | Out-Null
    Copy-Item -LiteralPath $ReleaseExecutable -Destination $PortableExecutable -Force
    Copy-Item -LiteralPath $SidecarPath -Destination $PortableSidecar -Force

    Assert-WindowsExecutable -Path $StableInstaller -Description 'NSIS installer'
    Assert-WindowsExecutable -Path $PackagedSidecar -Description 'Packaged FastAPI sidecar'
    Assert-WindowsExecutable -Path $PortableExecutable -Description 'Portable desktop application'
    Compress-Archive -Path (Join-Path $PortableDirectory '*') -DestinationPath $PortableZip -CompressionLevel Optimal -Force

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $PortableArchive = [IO.Compression.ZipFile]::OpenRead($PortableZip)
    try {
        $ArchiveEntries = @(
            $PortableArchive.Entries |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_.Name) } |
                ForEach-Object { $_.FullName.Replace('\', '/') }
        )
        $ExpectedEntries = @(
            'Radiology-Desktop.exe',
            'radiology-backend.exe'
        )
        if (Compare-Object -ReferenceObject $ExpectedEntries -DifferenceObject $ArchiveEntries) {
            throw "Portable archive inventory was unexpected: $($ArchiveEntries -join ', ')"
        }
    }
    finally {
        $PortableArchive.Dispose()
    }

    $InstallerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $StableInstaller).Hash.ToLowerInvariant()
    $SidecarHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PackagedSidecar).Hash.ToLowerInvariant()
    $PortableExecutableHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PortableExecutable).Hash.ToLowerInvariant()
    $PortableZipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PortableZip).Hash.ToLowerInvariant()
    "$InstallerHash  $([IO.Path]::GetFileName($StableInstaller))" | Set-Content -LiteralPath (Join-Path $ArtifactRoot 'Radiology-Desktop_2.2.0_x64-setup.exe.sha256') -Encoding ascii

    $ArtifactInventory = @(
        [ordered]@{
            kind = 'nsis-currentUser-installer'
            file = [IO.Path]::GetFileName($StableInstaller)
            bytes = (Get-Item -LiteralPath $StableInstaller).Length
            sha256 = $InstallerHash
        },
        [ordered]@{
            kind = 'portable-zip'
            file = [IO.Path]::GetFileName($PortableZip)
            bytes = (Get-Item -LiteralPath $PortableZip).Length
            sha256 = $PortableZipHash
        },
        [ordered]@{
            kind = 'fastapi-sidecar'
            file = [IO.Path]::GetFileName($PackagedSidecar)
            bytes = (Get-Item -LiteralPath $PackagedSidecar).Length
            sha256 = $SidecarHash
        }
    )

    $Manifest = [ordered]@{
        product = 'Radiology Desktop'
        version = '2.2.0'
        target = $Toolchains.target
        gitCommit = $Commit
        sourceDateEpoch = $env:SOURCE_DATE_EPOCH
        python = $PythonVersion
        node = $NodeVersion
        npm = $NpmVersion
        rust = $RustVersion
        tauriCli = $TauriVersion
        pyinstaller = $PyInstallerVersion
        msvc = $MsvcVersion
        webView2 = $WebView2Version
        powershell = $PSVersionTable.PSVersion.ToString()
        windows = [Environment]::OSVersion.VersionString
        frontendLockSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $RepositoryRoot 'frontend\package-lock.json')).Hash.ToLowerInvariant()
        pythonLockSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PythonLock).Hash.ToLowerInvariant()
        cargoLockSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $CargoLock).Hash.ToLowerInvariant()
        sidecarSha256 = $SidecarHash
        portableExecutableSha256 = $PortableExecutableHash
        installer = [IO.Path]::GetFileName($StableInstaller)
        sha256 = $InstallerHash
        artifacts = $ArtifactInventory
        signed = $false
    }
    $Manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ToolchainManifestPath -Encoding utf8

    $BuildManifest = [ordered]@{
        schemaVersion = 1
        product = 'Radiology Desktop'
        version = '2.2.0'
        target = $Toolchains.target
        gitCommit = $Commit
        sourceDateEpoch = $env:SOURCE_DATE_EPOCH
        generatedAtUtc = [DateTime]::UtcNow.ToString('o')
        artifacts = $ArtifactInventory
        portableContents = @(
            [ordered]@{
                file = [IO.Path]::GetFileName($PortableExecutable)
                sha256 = $PortableExecutableHash
            },
            [ordered]@{
                file = [IO.Path]::GetFileName($PortableSidecar)
                sha256 = $SidecarHash
            }
        )
        evidence = @(
            'build.log',
            'toolchain-manifest.json',
            'SHA256SUMS.txt'
        )
    }
    $BuildManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $BuildManifestPath -Encoding utf8
    $BuildSucceeded = $true
}
finally {
    Stop-Transcript | Out-Null
}

if ($BuildSucceeded) {
    $ChecksumFiles = @(
        $StableInstaller,
        $PortableZip,
        $PackagedSidecar,
        $BuildManifestPath,
        $ToolchainManifestPath,
        $TranscriptPath
    )
    $ChecksumLines = foreach ($ArtifactPath in $ChecksumFiles) {
        $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ArtifactPath).Hash.ToLowerInvariant()
        "$Hash  $([IO.Path]::GetFileName($ArtifactPath))"
    }
    $ChecksumLines | Set-Content -LiteralPath $ChecksumsPath -Encoding ascii
}

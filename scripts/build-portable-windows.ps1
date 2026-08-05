[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$DesktopBuildScript = Join-Path $PSScriptRoot 'build-desktop.ps1'
$ArtifactRoot = Join-Path $RepositoryRoot 'artifacts\windows-x64'
$PortableDirectory = Join-Path $ArtifactRoot 'Radiology-Desktop_2.2.0_x64-portable'
$PortableExecutable = Join-Path $PortableDirectory 'Radiology-Desktop.exe'
$PortableSidecar = Join-Path $PortableDirectory 'radiology-backend.exe'
$PortableZip = Join-Path $ArtifactRoot 'Radiology-Desktop_2.2.0_x64-portable.zip'
$BuildManifestPath = Join-Path $ArtifactRoot 'build-manifest.json'
$ToolchainManifestPath = Join-Path $ArtifactRoot 'toolchain-manifest.json'
$ChecksumsPath = Join-Path $ArtifactRoot 'SHA256SUMS.txt'

function Assert-WindowsExecutable {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description is missing: $Path"
    }
    $Stream = [IO.File]::OpenRead($Path)
    try {
        $Header = [byte[]]::new(2)
        if ($Stream.Length -lt 1048576 -or $Stream.Read($Header, 0, 2) -ne 2 -or $Header[0] -ne 0x4d -or $Header[1] -ne 0x5a) {
            throw "$Description is not a valid Windows executable."
        }
    }
    finally {
        $Stream.Dispose()
    }
}

function Invoke-PortableSigning {
    param([Parameter(Mandatory)][string[]]$Paths)

    $Thumbprint = $env:RADIOLOGY_WINDOWS_CERTIFICATE_THUMBPRINT
    if ([string]::IsNullOrWhiteSpace($Thumbprint)) {
        return $false
    }
    $Thumbprint = $Thumbprint -replace '\s', ''
    if ($Thumbprint -notmatch '^[0-9A-Fa-f]{40}$') {
        throw 'RADIOLOGY_WINDOWS_CERTIFICATE_THUMBPRINT must be a 40-character SHA-1 certificate thumbprint.'
    }

    $SignTool = $env:RADIOLOGY_WINDOWS_SIGNTOOL_PATH
    if ([string]::IsNullOrWhiteSpace($SignTool)) {
        $SignToolCommand = Get-Command 'signtool.exe' -ErrorAction SilentlyContinue
        if (-not $SignToolCommand) {
            throw 'Signing was requested, but signtool.exe was not found.'
        }
        $SignTool = $SignToolCommand.Source
    }
    elseif (-not (Test-Path -LiteralPath $SignTool -PathType Leaf)) {
        throw "RADIOLOGY_WINDOWS_SIGNTOOL_PATH does not exist: $SignTool"
    }

    $SignArguments = @('sign', '/sha1', $Thumbprint, '/fd', 'SHA256')
    $TimestampUrl = $env:RADIOLOGY_WINDOWS_TIMESTAMP_URL
    if (-not [string]::IsNullOrWhiteSpace($TimestampUrl)) {
        $SignArguments += @('/tr', $TimestampUrl, '/td', 'SHA256')
    }

    foreach ($Path in $Paths) {
        & $SignTool @SignArguments $Path
        if ($LASTEXITCODE -ne 0) {
            throw "signtool.exe failed for $Path with exit code $LASTEXITCODE."
        }
        $Signature = Get-AuthenticodeSignature -LiteralPath $Path
        if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Thumbprint -ne $Thumbprint) {
            throw "Authenticode verification failed for $Path."
        }
    }
    return $true
}

function Update-PortableManifests {
    param(
        [Parameter(Mandatory)][bool]$PortableSigned,
        [Parameter(Mandatory)][string]$ExecutableHash,
        [Parameter(Mandatory)][string]$SidecarHash,
        [Parameter(Mandatory)][string]$ZipHash
    )

    $BuildManifest = Get-Content -LiteralPath $BuildManifestPath -Raw | ConvertFrom-Json
    foreach ($Item in $BuildManifest.portableContents) {
        if ($Item.file -eq 'Radiology-Desktop.exe') {
            $Item.sha256 = $ExecutableHash
        }
        elseif ($Item.file -eq 'radiology-backend.exe') {
            $Item.sha256 = $SidecarHash
        }
    }
    $PortableArtifact = @($BuildManifest.artifacts) | Where-Object kind -eq 'portable-zip'
    $PortableArtifact.bytes = (Get-Item -LiteralPath $PortableZip).Length
    $PortableArtifact.sha256 = $ZipHash
    $BuildManifest | Add-Member -NotePropertyName portableSigned -NotePropertyValue $PortableSigned -Force
    $BuildManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $BuildManifestPath -Encoding utf8

    $ToolchainManifest = Get-Content -LiteralPath $ToolchainManifestPath -Raw | ConvertFrom-Json
    $ToolchainManifest.portableExecutableSha256 = $ExecutableHash
    $ToolchainManifest | Add-Member -NotePropertyName portableSidecarSha256 -NotePropertyValue $SidecarHash -Force
    $ToolchainManifest | Add-Member -NotePropertyName portableSigned -NotePropertyValue $PortableSigned -Force
    $ToolchainPortableArtifact = @($ToolchainManifest.artifacts) | Where-Object kind -eq 'portable-zip'
    $ToolchainPortableArtifact.bytes = (Get-Item -LiteralPath $PortableZip).Length
    $ToolchainPortableArtifact.sha256 = $ZipHash
    $ToolchainManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ToolchainManifestPath -Encoding utf8

    $ChecksumNames = @(
        'Radiology-Desktop_2.2.0_x64-setup.exe',
        'Radiology-Desktop_2.2.0_x64-portable.zip',
        'radiology-backend-x86_64-pc-windows-msvc.exe',
        'build-manifest.json',
        'toolchain-manifest.json',
        'build.log'
    )
    $ChecksumLines = foreach ($Name in $ChecksumNames) {
        $Path = Join-Path $ArtifactRoot $Name
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Required portable evidence is missing: $Name"
        }
        $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
        "$Hash  $Name"
    }
    $ChecksumLines | Set-Content -LiteralPath $ChecksumsPath -Encoding ascii
}

$BuildParameters = @{}
if ($SkipInstall) {
    $BuildParameters.SkipInstall = $true
}
if ($SkipTests) {
    $BuildParameters.SkipTests = $true
}
& $DesktopBuildScript @BuildParameters

$ExpectedFiles = @('Radiology-Desktop.exe', 'radiology-backend.exe')
$ActualFiles = @(
    Get-ChildItem -LiteralPath $PortableDirectory -File |
        Sort-Object Name |
        ForEach-Object Name
)
if (Compare-Object -ReferenceObject ($ExpectedFiles | Sort-Object) -DifferenceObject $ActualFiles) {
    throw "Portable folder inventory is invalid: $($ActualFiles -join ', ')"
}
if (Get-ChildItem -LiteralPath $PortableDirectory -Directory) {
    throw 'Portable folder must not contain undeclared directories.'
}

Assert-WindowsExecutable -Path $PortableExecutable -Description 'Portable Tauri host'
Assert-WindowsExecutable -Path $PortableSidecar -Description 'Portable FastAPI sidecar'
$PortableSigned = Invoke-PortableSigning -Paths @($PortableExecutable, $PortableSidecar)

Remove-Item -LiteralPath $PortableZip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $PortableDirectory '*') -DestinationPath $PortableZip -CompressionLevel Optimal

Add-Type -AssemblyName System.IO.Compression.FileSystem
$Archive = [IO.Compression.ZipFile]::OpenRead($PortableZip)
try {
    $ArchiveEntries = @(
        $Archive.Entries |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_.Name) } |
            ForEach-Object { $_.FullName.Replace('\', '/') } |
            Sort-Object
    )
    if (Compare-Object -ReferenceObject ($ExpectedFiles | Sort-Object) -DifferenceObject $ArchiveEntries) {
        throw "Portable ZIP inventory is invalid: $($ArchiveEntries -join ', ')"
    }
}
finally {
    $Archive.Dispose()
}

$ExecutableHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PortableExecutable).Hash.ToLowerInvariant()
$SidecarHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PortableSidecar).Hash.ToLowerInvariant()
$ZipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PortableZip).Hash.ToLowerInvariant()
Update-PortableManifests -PortableSigned $PortableSigned -ExecutableHash $ExecutableHash -SidecarHash $SidecarHash -ZipHash $ZipHash

Write-Output "Portable folder: $PortableDirectory"
Write-Output "Portable ZIP: $PortableZip"
Write-Output "Portable signed: $PortableSigned"

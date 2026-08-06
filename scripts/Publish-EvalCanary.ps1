[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Owner = 'lmdixon23',
    [string]$RepoName = 'evalcanary',
    [ValidateSet('public', 'private')]
    [string]$Visibility = 'public'
)

$ErrorActionPreference = 'Stop'
$PassItems = New-Object System.Collections.Generic.List[string]
$FailItems = New-Object System.Collections.Generic.List[string]

function Add-Pass {
    param([string]$Message)
    $PassItems.Add($Message)
}

function Add-Fail {
    param([string]$Message)
    $FailItems.Add($Message)
}

try {
    if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
        throw ('Project root does not exist: ' + $ProjectRoot)
    }
    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
        throw 'git.exe was not found on PATH.'
    }
    if (-not (Get-Command gh.exe -ErrorAction SilentlyContinue)) {
        throw 'gh.exe was not found on PATH.'
    }

    Push-Location $ProjectRoot
    try {
        & gh.exe auth status
        if ($LASTEXITCODE -ne 0) {
            throw 'GitHub CLI authentication is not ready.'
        }
        Add-Pass 'GitHub CLI authentication verified'

        & git.exe rev-parse --is-inside-work-tree | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Project root is not a Git repository.'
        }

        $Status = (& git.exe status --porcelain=v1)
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to inspect Git status.'
        }
        if (-not [string]::IsNullOrWhiteSpace(($Status -join "`n"))) {
            throw 'Git working tree is not clean. Review and commit changes before publishing.'
        }
        Add-Pass 'Clean Git tree verified'

        & git.exe remote get-url origin *> $null
        if ($LASTEXITCODE -eq 0) {
            throw 'An origin remote already exists. This script will not replace it.'
        }

        $FullName = $Owner + '/' + $RepoName
        & gh.exe repo view $FullName *> $null
        if ($LASTEXITCODE -eq 0) {
            throw ('GitHub repository already exists: ' + $FullName)
        }
        Add-Pass ('Remote name is available to create: ' + $FullName)

        $Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
            throw ('Virtual-environment Python not found: ' + $Python)
        }
        & $Python scripts\release_check.py
        if ($LASTEXITCODE -ne 0) {
            throw 'Release check failed. Publishing is blocked.'
        }
        Add-Pass 'Release gate passed'

        $VisibilityFlag = '--' + $Visibility
        & gh.exe repo create $FullName $VisibilityFlag --source $ProjectRoot --remote origin --push
        if ($LASTEXITCODE -ne 0) {
            throw ('GitHub repository creation failed for ' + $FullName)
        }
        Add-Pass ('Repository created and pushed: https://github.com/' + $FullName)
    }
    finally {
        Pop-Location
    }
}
catch {
    Add-Fail $_.Exception.Message
}

Write-Host ''
Write-Host 'EvalCanary publish summary'
Write-Host ('PASS: ' + $PassItems.Count) -ForegroundColor Green
foreach ($Item in $PassItems) {
    Write-Host ('  PASS ' + $Item) -ForegroundColor Green
}
Write-Host ('FAIL: ' + $FailItems.Count) -ForegroundColor $(
    if ($FailItems.Count -eq 0) { 'Green' } else { 'Red' }
)
foreach ($Item in $FailItems) {
    Write-Host ('  FAIL ' + $Item) -ForegroundColor Red
}

if ($FailItems.Count -ne 0) {
    exit 1
}
exit 0

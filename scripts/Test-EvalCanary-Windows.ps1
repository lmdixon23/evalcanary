[CmdletBinding()]
param(
    [string]$ProjectRoot = ''
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
    if ($PSVersionTable.PSVersion -lt [version]'5.1') {
        throw 'Windows PowerShell 5.1 or later is required.'
    }
    Add-Pass ('PowerShell version verified: ' + $PSVersionTable.PSVersion)

    if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
        if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) {
            throw 'Unable to resolve the script directory. Supply -ProjectRoot explicitly.'
        }
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    }
    if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
        throw ('Project root does not exist: ' + $ProjectRoot)
    }
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    Add-Pass ('Project root resolved: ' + $ProjectRoot)

    $Scripts = @(
        Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'scripts') -Filter '*.ps1' -File
    )
    if ($Scripts.Count -eq 0) {
        throw 'No PowerShell scripts were found for the parser gate.'
    }
    foreach ($Script in $Scripts) {
        $Tokens = $null
        $Errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $Script.FullName,
            [ref]$Tokens,
            [ref]$Errors
        ) | Out-Null
        if ($Errors.Count -ne 0) {
            throw (
                'PowerShell parser errors in ' + $Script.Name + ': ' +
                ($Errors | Out-String)
            )
        }
    }
    Add-Pass ('Repository PowerShell parser gate passed: ' + $Scripts.Count)

    $Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw ('Virtual-environment Python not found: ' + $Python)
    }

    Push-Location $ProjectRoot
    try {
        & $Python scripts\release_check.py
        if ($LASTEXITCODE -ne 0) {
            throw ('Release check failed with exit code ' + $LASTEXITCODE)
        }
        Add-Pass 'Python release check passed'

        & $Python scripts\check_ascii_ps.py
        if ($LASTEXITCODE -ne 0) {
            throw ('PowerShell ASCII gate failed with exit code ' + $LASTEXITCODE)
        }
        Add-Pass 'PowerShell ASCII gate passed'

        $DemoRoot = Join-Path $ProjectRoot '_local\windows-demo'
        if (Test-Path -LiteralPath $DemoRoot) {
            Remove-Item -LiteralPath $DemoRoot -Recurse -Force
        }
        & $Python -m evalcanary demo --out $DemoRoot
        if ($LASTEXITCODE -ne 0) {
            throw ('Demo failed with exit code ' + $LASTEXITCODE)
        }
        $Report = Join-Path $DemoRoot 'report\report.json'
        if (-not (Test-Path -LiteralPath $Report -PathType Leaf)) {
            throw 'Demo JSON report was not created.'
        }
        $Data = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
        if ($Data.transition_counts.fail_to_pass -ne 5) {
            throw 'Demo did not detect the expected five fail-to-pass transitions.'
        }
        Add-Pass 'Windows demo report contract passed'
    }
    finally {
        Pop-Location
    }
}
catch {
    Add-Fail $_.Exception.Message
}

Write-Host ''
Write-Host 'EvalCanary Windows verification summary'
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

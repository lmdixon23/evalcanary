[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$Owner = 'lmdixon23',
    [string]$RepoName = 'evalcanary',
    [ValidateSet('public', 'private')]
    [string]$Visibility = 'public',
    [string]$ExpectedHead = '',
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
$PassItems = New-Object System.Collections.Generic.List[string]
$FailItems = New-Object System.Collections.Generic.List[string]
$RemoteCreated = $false
$PushVerified = $false
$PublicationVerified = $false
$FullName = $Owner + '/' + $RepoName

function Add-Pass {
    param([string]$Message)
    $PassItems.Add($Message)
}

function Add-Fail {
    param([string]$Message)
    $FailItems.Add($Message)
}

function ConvertTo-NativeArgument {
    param([string]$Value)

    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }

    $Builder = New-Object System.Text.StringBuilder
    [void]$Builder.Append('"')
    $Backslashes = 0

    foreach ($Character in $Value.ToCharArray()) {
        if ($Character -eq '\') {
            $Backslashes += 1
            continue
        }

        if ($Character -eq '"') {
            [void]$Builder.Append(('\' * (($Backslashes * 2) + 1)))
            [void]$Builder.Append('"')
            $Backslashes = 0
            continue
        }

        if ($Backslashes -gt 0) {
            [void]$Builder.Append(('\' * $Backslashes))
            $Backslashes = 0
        }
        [void]$Builder.Append($Character)
    }

    if ($Backslashes -gt 0) {
        [void]$Builder.Append(('\' * ($Backslashes * 2)))
    }
    [void]$Builder.Append('"')
    return $Builder.ToString()
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $ProjectRoot,
        [int]$TimeoutSeconds = 300,
        [switch]$Echo
    )

    $StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $StartInfo.FileName = $FilePath
    $StartInfo.Arguments = (($Arguments | ForEach-Object {
        ConvertTo-NativeArgument -Value $_
    }) -join ' ')
    $StartInfo.WorkingDirectory = $WorkingDirectory
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true

    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $StartInfo
    if (-not $Process.Start()) {
        throw ('Unable to start native process: ' + $FilePath)
    }

    $StdOutTask = $Process.StandardOutput.ReadToEndAsync()
    $StdErrTask = $Process.StandardError.ReadToEndAsync()
    if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $Process.Kill() } catch { }
        try { [void]$Process.WaitForExit(5000) } catch { }
        throw ('Native process timed out after ' + $TimeoutSeconds + ' seconds: ' + $FilePath)
    }

    [System.Threading.Tasks.Task[]]$ReadTasks = @(
        $StdOutTask,
        $StdErrTask
    )
    [System.Threading.Tasks.Task]::WaitAll($ReadTasks)
    $Process.Refresh()

    $Result = [pscustomobject]@{
        ExitCode = $Process.ExitCode
        StdOut = $StdOutTask.Result
        StdErr = $StdErrTask.Result
        Command = $FilePath + ' ' + $StartInfo.Arguments
    }

    if ($Echo) {
        if (-not [string]::IsNullOrWhiteSpace($Result.StdOut)) {
            Write-Host $Result.StdOut.TrimEnd()
        }
        if (-not [string]::IsNullOrWhiteSpace($Result.StdErr)) {
            Write-Host $Result.StdErr.TrimEnd() -ForegroundColor Yellow
        }
    }
    return $Result
}

function Require-NativeSuccess {
    param(
        [Parameter(Mandatory = $true)]
        $Result,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    if ($Result.ExitCode -ne 0) {
        $Detail = $Result.StdErr.Trim()
        if ([string]::IsNullOrWhiteSpace($Detail)) {
            $Detail = $Result.StdOut.Trim()
        }
        if ([string]::IsNullOrWhiteSpace($Detail)) {
            $Detail = 'No process output was produced.'
        }
        throw ($FailureMessage + ' Exit code ' + $Result.ExitCode + '. ' + $Detail)
    }
}

function Get-NativeFailureDetail {
    param($Result)

    $Detail = ($Result.StdErr + "`n" + $Result.StdOut).Trim()
    if ([string]::IsNullOrWhiteSpace($Detail)) {
        return 'No process output was produced.'
    }
    return $Detail
}

try {
    if ($PSVersionTable.PSVersion -lt [version]'5.1') {
        throw 'Windows PowerShell 5.1 or later is required.'
    }
    Add-Pass ('PowerShell version verified: ' + $PSVersionTable.PSVersion)

    $ScriptPath = $MyInvocation.MyCommand.Path
    if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
        throw 'Unable to resolve the publication script path.'
    }

    $Tokens = $null
    $ParserErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $ScriptPath,
        [ref]$Tokens,
        [ref]$ParserErrors
    ) | Out-Null
    if ($ParserErrors.Count -ne 0) {
        throw ('Publication script parser errors: ' + ($ParserErrors | Out-String))
    }
    Add-Pass 'Publication script parser gate passed'

    if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
        $ScriptRoot = Split-Path -Parent $ScriptPath
        if ([string]::IsNullOrWhiteSpace($ScriptRoot)) {
            throw 'Unable to resolve the publication script directory.'
        }
        $ProjectRoot = Split-Path -Parent $ScriptRoot
    }

    if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
        throw ('Project root does not exist: ' + $ProjectRoot)
    }
    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    Add-Pass ('Project root resolved: ' + $ProjectRoot)

    $Git = (Get-Command git.exe -ErrorAction Stop).Source
    $Gh = (Get-Command gh.exe -ErrorAction Stop).Source
    $Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw ('Virtual-environment Python not found: ' + $Python)
    }
    Add-Pass 'Git, GitHub CLI, and project Python found'

    $AuthResult = Invoke-Native -FilePath $Gh -Arguments @(
        'auth', 'status', '--hostname', 'github.com'
    ) -TimeoutSeconds 60 -Echo
    Require-NativeSuccess -Result $AuthResult -FailureMessage 'GitHub CLI authentication is not ready.'
    Add-Pass 'GitHub CLI authentication verified'

    $LoginResult = Invoke-Native -FilePath $Gh -Arguments @(
        'api', 'user', '--jq', '.login'
    ) -TimeoutSeconds 60
    Require-NativeSuccess -Result $LoginResult -FailureMessage 'Unable to resolve the authenticated GitHub login.'
    $AuthenticatedLogin = $LoginResult.StdOut.Trim()
    if ($AuthenticatedLogin -ine $Owner) {
        throw ('Authenticated GitHub login is ' + $AuthenticatedLogin + ', but owner is ' + $Owner + '.')
    }
    Add-Pass ('Authenticated owner verified: ' + $AuthenticatedLogin)

    $InsideResult = Invoke-Native -FilePath $Git -Arguments @(
        'rev-parse', '--is-inside-work-tree'
    )
    Require-NativeSuccess -Result $InsideResult -FailureMessage 'Project root is not a Git repository.'
    if ($InsideResult.StdOut.Trim() -ne 'true') {
        throw 'Project root is not inside a Git working tree.'
    }

    $BranchResult = Invoke-Native -FilePath $Git -Arguments @(
        'branch', '--show-current'
    )
    Require-NativeSuccess -Result $BranchResult -FailureMessage 'Unable to resolve the current Git branch.'
    $Branch = $BranchResult.StdOut.Trim()
    if ($Branch -ne 'main') {
        throw ('Publication requires branch main. Current branch: ' + $Branch)
    }
    Add-Pass 'Main branch verified'

    $HeadResult = Invoke-Native -FilePath $Git -Arguments @(
        'rev-parse', 'HEAD'
    )
    Require-NativeSuccess -Result $HeadResult -FailureMessage 'Unable to read Git HEAD.'
    $ActualHead = $HeadResult.StdOut.Trim()
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $ActualHead -ne $ExpectedHead) {
        throw ('Unexpected Git HEAD. Expected ' + $ExpectedHead + ', found ' + $ActualHead + '.')
    }
    if (-not $PreflightOnly -and [string]::IsNullOrWhiteSpace($ExpectedHead)) {
        throw ('Publication requires -ExpectedHead. Current HEAD is ' + $ActualHead + '.')
    }
    Add-Pass ('Release-candidate HEAD verified: ' + $ActualHead)

    $StatusResult = Invoke-Native -FilePath $Git -Arguments @(
        'status', '--porcelain=v1', '--untracked-files=all'
    )
    Require-NativeSuccess -Result $StatusResult -FailureMessage 'Unable to inspect Git status.'
    if (-not [string]::IsNullOrWhiteSpace($StatusResult.StdOut)) {
        throw 'Git working tree is not clean. Review and commit changes before publishing.'
    }
    Add-Pass 'Clean Git tree verified'

    $OriginResult = Invoke-Native -FilePath $Git -Arguments @(
        'remote', 'get-url', 'origin'
    )
    if ($OriginResult.ExitCode -eq 0) {
        throw ('An origin remote already exists: ' + $OriginResult.StdOut.Trim())
    }
    $OriginDetail = Get-NativeFailureDetail -Result $OriginResult
    if ($OriginDetail -notmatch '(?i)No such remote') {
        throw ('Unable to verify that origin is absent. ' + $OriginDetail)
    }
    Add-Pass 'No origin remote verified'

    $AvailabilityResult = Invoke-Native -FilePath $Gh -Arguments @(
        'api', ('repos/' + $FullName)
    ) -TimeoutSeconds 60
    if ($AvailabilityResult.ExitCode -eq 0) {
        throw ('GitHub repository already exists: https://github.com/' + $FullName)
    }
    $AvailabilityDetail = Get-NativeFailureDetail -Result $AvailabilityResult
    if ($AvailabilityDetail -notmatch '(?i)(HTTP 404|Not Found)') {
        throw ('Repository availability could not be established. ' + $AvailabilityDetail)
    }
    Add-Pass ('Remote name is available to create: ' + $FullName)

    $ReleaseResult = Invoke-Native -FilePath $Python -Arguments @(
        'scripts\release_check.py'
    ) -TimeoutSeconds 900 -Echo
    Require-NativeSuccess -Result $ReleaseResult -FailureMessage 'Release check failed. Publishing is blocked.'
    if ($ReleaseResult.StdOut -notmatch 'FAIL: 0') {
        throw 'Release check did not report FAIL: 0.'
    }
    Add-Pass 'Python release gate passed'

    $PowerShellPath = Join-Path $PSHOME 'powershell.exe'
    $WindowsScript = Join-Path $ProjectRoot 'scripts\Test-EvalCanary-Windows.ps1'
    $WindowsResult = Invoke-Native -FilePath $PowerShellPath -Arguments @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $WindowsScript,
        '-ProjectRoot', $ProjectRoot
    ) -TimeoutSeconds 1200 -Echo
    Require-NativeSuccess -Result $WindowsResult -FailureMessage 'Windows verification failed. Publishing is blocked.'
    if ($WindowsResult.StdOut -notmatch 'FAIL: 0') {
        throw 'Windows verification did not report FAIL: 0.'
    }
    Add-Pass 'Windows verification gate passed'

    $DiffCheck = Invoke-Native -FilePath $Git -Arguments @(
        'diff', '--check'
    )
    Require-NativeSuccess -Result $DiffCheck -FailureMessage 'Git whitespace check failed.'
    Add-Pass 'Git whitespace gate passed'

    if ($PreflightOnly) {
        Add-Pass 'Preflight completed; no remote changes were made'
    }
    else {
        $VisibilityFlag = '--' + $Visibility
        $CreateResult = Invoke-Native -FilePath $Gh -Arguments @(
            'repo', 'create', $FullName,
            $VisibilityFlag,
            '--source', $ProjectRoot,
            '--remote', 'origin',
            '--description', 'Catch evaluation drift before it ships.'
        ) -TimeoutSeconds 180 -Echo
        if ($CreateResult.ExitCode -ne 0) {
            $CreateProbe = Invoke-Native -FilePath $Gh -Arguments @(
                'api', ('repos/' + $FullName)
            ) -TimeoutSeconds 60
            if ($CreateProbe.ExitCode -eq 0) {
                $RemoteCreated = $true
            }
            Require-NativeSuccess -Result $CreateResult -FailureMessage ('GitHub repository creation failed for ' + $FullName + '.')
        }
        $RemoteCreated = $true
        Add-Pass ('Repository created: https://github.com/' + $FullName)

        $CreatedView = Invoke-Native -FilePath $Gh -Arguments @(
            'repo', 'view', $FullName, '--json', 'nameWithOwner,url,visibility'
        ) -TimeoutSeconds 60
        Require-NativeSuccess -Result $CreatedView -FailureMessage 'Created GitHub repository could not be verified.'
        $CreatedMetadata = $CreatedView.StdOut | ConvertFrom-Json
        if ($CreatedMetadata.nameWithOwner -ine $FullName) {
            throw ('Created repository identity mismatch: ' + $CreatedMetadata.nameWithOwner)
        }
        if ($CreatedMetadata.visibility.ToString().ToLowerInvariant() -ne $Visibility) {
            throw ('Created repository visibility mismatch: ' + $CreatedMetadata.visibility)
        }
        Add-Pass 'Remote repository identity and visibility verified'

        $NewOrigin = Invoke-Native -FilePath $Git -Arguments @(
            'remote', 'get-url', 'origin'
        )
        Require-NativeSuccess -Result $NewOrigin -FailureMessage 'The new origin remote could not be read.'
        $OriginUrl = $NewOrigin.StdOut.Trim()
        $RepoPattern = [regex]::Escape($Owner) + '[/:]' + [regex]::Escape($RepoName) + '(\.git)?$'
        if ($OriginUrl -notmatch $RepoPattern) {
            throw ('Unexpected origin URL after repository creation: ' + $OriginUrl)
        }
        Add-Pass ('Origin remote verified: ' + $OriginUrl)

        $PushResult = Invoke-Native -FilePath $Git -Arguments @(
            'push', '--set-upstream', 'origin', 'main'
        ) -TimeoutSeconds 600 -Echo
        Require-NativeSuccess -Result $PushResult -FailureMessage 'Push of main failed.'
        Add-Pass 'Main branch pushed'

        $RemoteHeadResult = Invoke-Native -FilePath $Git -Arguments @(
            'ls-remote', '--heads', 'origin', 'refs/heads/main'
        ) -TimeoutSeconds 120
        Require-NativeSuccess -Result $RemoteHeadResult -FailureMessage 'Unable to verify the remote main branch.'
        $RemoteHeadLine = $RemoteHeadResult.StdOut.Trim()
        if ([string]::IsNullOrWhiteSpace($RemoteHeadLine)) {
            throw 'Remote main branch was not returned by git ls-remote.'
        }
        $RemoteHead = ($RemoteHeadLine -split '\s+')[0]
        if ($RemoteHead -ne $ActualHead) {
            throw ('Remote main mismatch. Local ' + $ActualHead + ', remote ' + $RemoteHead + '.')
        }
        $PushVerified = $true
        Add-Pass ('Remote main verified at ' + $RemoteHead)

        $FinalView = Invoke-Native -FilePath $Gh -Arguments @(
            'repo', 'view', $FullName, '--json', 'defaultBranchRef,url,visibility'
        ) -TimeoutSeconds 60
        Require-NativeSuccess -Result $FinalView -FailureMessage 'Published repository metadata could not be verified.'
        $FinalMetadata = $FinalView.StdOut | ConvertFrom-Json
        if ($null -eq $FinalMetadata.defaultBranchRef -or $FinalMetadata.defaultBranchRef.name -ne 'main') {
            throw 'Published repository default branch is not main.'
        }
        Add-Pass ('Published repository verified: ' + $FinalMetadata.url)

        $FinalStatus = Invoke-Native -FilePath $Git -Arguments @(
            'status', '--porcelain=v1', '--untracked-files=all'
        )
        Require-NativeSuccess -Result $FinalStatus -FailureMessage 'Unable to inspect final Git status.'
        if (-not [string]::IsNullOrWhiteSpace($FinalStatus.StdOut)) {
            throw 'Git working tree changed during publication.'
        }
        Add-Pass 'Clean local repository verified after publication'
        $PublicationVerified = $true
    }
}
catch {
    Add-Fail $_.Exception.Message
    if ($RemoteCreated -and -not $PublicationVerified) {
        Add-Fail (
            'Partial publication state exists or may exist at https://github.com/' + $FullName +
            '. Do not rerun blindly; inspect the repository and origin first.'
        )
    }
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

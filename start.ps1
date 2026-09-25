# Windows PowerShell 5.1 and PowerShell 7. No machine-wide policy changes.
param([switch]$Check, [switch]$NoBrowser, [string]$BindAddress = "127.0.0.1")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = $null
$pythonArgs = @()
$probe = 'import sys; sys.exit(not ((3,11) <= sys.version_info[:2] < (3,14)))'
$localPython = Join-Path $PSScriptRoot '.env/Scripts/python.exe'
if (Test-Path -LiteralPath $localPython) {
    & $localPython -c $probe
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'The project Python is incompatible. Move .env aside and rerun the launcher.'
        exit 1
    }
    $python = $localPython
} else {
    foreach ($version in @('-3.11', '-3.12', '-3.13')) {
        $py = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($py) {
            # Windows PowerShell can turn native stderr into a terminating error.
            try { & $py.Source $version -c $probe 2>$null } catch { continue }
            if ($LASTEXITCODE -eq 0) { $python = $py.Source; $pythonArgs = @($version); break }
        }
    }
    if (-not $python) {
        foreach ($name in @('python.exe', 'python3.exe')) {
            $candidate = Get-Command $name -ErrorAction SilentlyContinue
            if ($candidate) {
                & $candidate.Source -c $probe
                if ($LASTEXITCODE -eq 0) { $python = $candidate.Source; break }
            }
        }
    }
}
if (-not $python) {
    Write-Error 'Install Python 3.11, 3.12, or 3.13 from python.org with the Python launcher/PATH option, then reopen PowerShell.'
    exit 1
}
$setupArgs = @((Join-Path $PSScriptRoot 'scripts/setup_portable.py'))
if ($Check) { $setupArgs += '--check' } else { $setupArgs += '--launch' }
if ($NoBrowser) { $setupArgs += '--no-browser' }
$setupArgs += @('--host', $BindAddress)
& $python @pythonArgs @setupArgs
exit $LASTEXITCODE

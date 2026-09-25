param([switch]$Check, [switch]$NoBrowser, [string]$BindAddress = "127.0.0.1")
& (Join-Path $PSScriptRoot 'start.ps1') -Check:$Check -NoBrowser:$NoBrowser -BindAddress $BindAddress
exit $LASTEXITCODE

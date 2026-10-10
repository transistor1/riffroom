param([switch]$Check, [switch]$NoBrowser, [switch]$Lan, [string]$BindAddress = "127.0.0.1")
& (Join-Path $PSScriptRoot 'start.ps1') -Check:$Check -NoBrowser:$NoBrowser -Lan:$Lan -BindAddress $BindAddress
exit $LASTEXITCODE

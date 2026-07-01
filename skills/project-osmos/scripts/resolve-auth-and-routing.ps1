# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
<#
.SYNOPSIS
PowerShell entry point for resolving Project Osmos auth, token, and task routing.

.DESCRIPTION
Runs the same tested Python resolver as resolve-auth-and-routing.py and writes
env.ps1, env.sh, routing.json, and a private MWC token file under OutputDir.
Use this entry point from Windows PowerShell or cross-platform pwsh.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TenantId,

    [Parameter(Mandatory = $true)]
    [string]$WorkspaceId,

    [Parameter(Mandatory = $true)]
    [string]$LakehouseId,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [string]$FabricApiHost = "https://api.fabric.microsoft.com",

    [string]$WorkloadType = "SparkCore",

    [double]$Timeout = 60,

    [string]$TokenResource = "https://analysis.windows.net/powerbi/api",

    [string]$PythonCommand = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-PythonInvocation {
    param([string]$RequestedCommand)

    if (-not [string]::IsNullOrWhiteSpace($RequestedCommand)) {
        return @{
            FileName = $RequestedCommand
            PrefixArgs = @()
        }
    }

    foreach ($candidate in @("python3", "python")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            return @{
                FileName = $command.Source
                PrefixArgs = @()
            }
        }
    }

    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        return @{
            FileName = $pyLauncher.Source
            PrefixArgs = @("-3")
        }
    }

    throw "Could not find python3, python, or py. Install Python or pass -PythonCommand."
}

$python = Resolve-PythonInvocation -RequestedCommand $PythonCommand
$scriptPath = Join-Path $PSScriptRoot "resolve-auth-and-routing.py"
$arguments = @()
$arguments += @($python.PrefixArgs)
$arguments += @(
    $scriptPath,
    "--tenant-id", $TenantId,
    "--workspace-id", $WorkspaceId,
    "--lakehouse-id", $LakehouseId,
    "--output-dir", $OutputDir,
    "--fabric-api-host", $FabricApiHost,
    "--workload-type", $WorkloadType,
    "--timeout", ([string]$Timeout),
    "--token-resource", $TokenResource
)

& $python.FileName @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$envScript = Join-Path $OutputDir "env.ps1"
Write-Host ""
Write-Host "PowerShell env file: $envScript"
Write-Host "Run: . '$envScript'"

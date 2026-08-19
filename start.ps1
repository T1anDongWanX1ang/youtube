<#
Start the Windows development services.

This script always starts the polling worker through the production project's
installed `youtube-crypto` entry point.  That prevents a same-named package in
the caller's working directory from being imported accidentally.

Usage: .\start.ps1 {start|stop|restart|status}
#>

[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSCommandPath
$LogsDir = Join-Path $ProjectDir "logs"
$WorkerPidFile = Join-Path $LogsDir "polling.pid"
$ApiPidFile = Join-Path $LogsDir "api.pid"
$WorkerBin = Join-Path $ProjectDir ".venv\Scripts\youtube-crypto.exe"
$UvicornBin = Join-Path $ProjectDir ".venv\Scripts\uvicorn.exe"
$WebHost = if ($env:YOUTUBE_WEB_HOST) { $env:YOUTUBE_WEB_HOST } else { "0.0.0.0" }
$WebPort = if ($env:YOUTUBE_WEB_PORT) { $env:YOUTUBE_WEB_PORT } else { "8000" }

function Get-ManagedProcess {
    param([string]$PidFile)

    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $null
    }

    $rawPid = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    $processId = 0
    if (-not [int]::TryParse($rawPid, [ref]$processId)) {
        Remove-Item -LiteralPath $PidFile -Force
        return $null
    }

    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Remove-Item -LiteralPath $PidFile -Force
    }
    return $process
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$PidFile,
        [string]$FilePath,
        [string[]]$ArgumentList
    )

    $existing = Get-ManagedProcess -PidFile $PidFile
    if ($null -ne $existing) {
        Write-Output "$Name is already running: pid=$($existing.Id)"
        return
    }

    $stdout = Join-Path $LogsDir "$Name.out.log"
    $stderr = Join-Path $LogsDir "$Name.err.log"
    if ($ArgumentList.Count -gt 0) {
        $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $ProjectDir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    } else {
        $process = Start-Process -FilePath $FilePath -WorkingDirectory $ProjectDir -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    }
    Set-Content -LiteralPath $PidFile -Value $process.Id -NoNewline
    Write-Output "Started ${Name}: pid=$($process.Id) stdout=$stdout stderr=$stderr"
}

function Stop-ManagedProcess {
    param([string]$Name, [string]$PidFile)

    $process = Get-ManagedProcess -PidFile $PidFile
    if ($null -eq $process) {
        Write-Output "$Name is not running"
        return
    }

    Stop-Process -Id $process.Id
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Write-Output "Stopped ${Name}: pid=$($process.Id)"
}

function Show-Status {
    foreach ($item in @(
        @{ Name = "polling worker"; PidFile = $WorkerPidFile },
        @{ Name = "API"; PidFile = $ApiPidFile }
    )) {
        $process = Get-ManagedProcess -PidFile $item.PidFile
        if ($null -eq $process) {
            Write-Output "$($item.Name): stopped"
        } else {
            Write-Output "$($item.Name): running pid=$($process.Id)"
        }
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir ".env"))) {
    throw "Missing $ProjectDir\.env"
}
if (-not (Test-Path -LiteralPath $WorkerBin) -or -not (Test-Path -LiteralPath $UvicornBin)) {
    throw "Missing project executables. Run uv sync --frozen in $ProjectDir first."
}

New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null

switch ($Action) {
    "start" {
        Start-ManagedProcess -Name "polling" -PidFile $WorkerPidFile -FilePath $WorkerBin -ArgumentList @()
        Start-ManagedProcess -Name "api" -PidFile $ApiPidFile -FilePath $UvicornBin -ArgumentList @("youtube_crypto.web.app:app", "--host", $WebHost, "--port", $WebPort)
    }
    "stop" {
        Stop-ManagedProcess -Name "polling worker" -PidFile $WorkerPidFile
        Stop-ManagedProcess -Name "API" -PidFile $ApiPidFile
    }
    "restart" {
        Stop-ManagedProcess -Name "polling worker" -PidFile $WorkerPidFile
        Stop-ManagedProcess -Name "API" -PidFile $ApiPidFile
        Start-ManagedProcess -Name "polling" -PidFile $WorkerPidFile -FilePath $WorkerBin -ArgumentList @()
        Start-ManagedProcess -Name "api" -PidFile $ApiPidFile -FilePath $UvicornBin -ArgumentList @("youtube_crypto.web.app:app", "--host", $WebHost, "--port", $WebPort)
    }
    "status" { Show-Status }
}

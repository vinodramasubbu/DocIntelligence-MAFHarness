[CmdletBinding()]
param(
    [switch]$Production,
    [ValidateRange(1, 600)]
    [int]$StartupTimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$web = Join-Path $root 'web'
$next = Join-Path $web 'node_modules\next\dist\bin\next'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Project .venv is missing. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r api\requirements.txt'
}
if (-not (Test-Path -LiteralPath $next)) {
    throw 'Frontend dependencies are missing. Run npm ci in the web folder.'
}
$node = (Get-Command node.exe -CommandType Application -ErrorAction Stop).Source
if ($Production -and -not (Test-Path -LiteralPath (Join-Path $web '.next\BUILD_ID'))) {
    throw 'Production build is missing. Run npm run build in the web folder first.'
}

foreach ($port in @(8000, 3000)) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    try {
        $listener.Start()
    }
    catch [System.Net.Sockets.SocketException] {
        throw "Port $port is in use. Stop that server first; this script will not stop existing processes."
    }
    finally {
        $listener.Stop()
    }
}

$logs = Join-Path $root '.logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$services = [System.Collections.Generic.List[object]]::new()

function Assert-ServiceRunning {
    param($Service)
    if ($Service.Process.HasExited) {
        $details = (Get-Content -LiteralPath $Service.ErrorLog -Tail 20) -join [Environment]::NewLine
        throw "$($Service.Name) exited with code $($Service.Process.ExitCode).`n$details`nSee $logs for full logs."
    }
}

function Wait-ServiceReady {
    param($Service, [string]$Url, [datetime]$Deadline)
    $lastFailure = 'No response received.'
    while ([datetime]::UtcNow -lt $Deadline) {
        foreach ($started in $services) {
            Assert-ServiceRunning $started
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                Write-Host "$($Service.Name) ready: $Url" -ForegroundColor Green
                return
            }
            $lastFailure = "HTTP $($response.StatusCode)"
        }
        catch {
            $lastFailure = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$($Service.Name) did not become ready in $StartupTimeoutSeconds seconds. Last response: $lastFailure. See $logs."
}

function Stop-AppProcess {
    param([int]$ProcessId)
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId")
    foreach ($child in $children) {
        Stop-AppProcess -ProcessId $child.ProcessId
    }
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        try {
            Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        }
        catch {
            if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
                Write-Warning "Could not stop app process ${ProcessId}: $($_.Exception.Message)"
            }
        }
    }
}

try {
    $backend = [pscustomobject]@{
        Name = 'Backend'
        ErrorLog = Join-Path $logs 'backend.stderr.log'
        Process = Start-Process -FilePath $python -ArgumentList @(
            '-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', '8000'
        ) -WorkingDirectory $root -NoNewWindow -PassThru `
          -RedirectStandardOutput (Join-Path $logs 'backend.stdout.log') `
          -RedirectStandardError (Join-Path $logs 'backend.stderr.log')
    }
    $services.Add($backend)
    $mode = if ($Production) { 'start' } else { 'dev' }
    $frontend = [pscustomobject]@{
        Name = 'Frontend'
        ErrorLog = Join-Path $logs 'frontend.stderr.log'
        Process = Start-Process -FilePath $node -ArgumentList @(
            "`"$next`"", $mode, '--hostname', '127.0.0.1', '--port', '3000'
        ) -WorkingDirectory $web -NoNewWindow -PassThru `
          -RedirectStandardOutput (Join-Path $logs 'frontend.stdout.log') `
          -RedirectStandardError (Join-Path $logs 'frontend.stderr.log')
    }
    $services.Add($frontend)
    Write-Host "Starting Submission Builder. Logs: $logs"
    $deadline = [datetime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
    Wait-ServiceReady $backend 'http://127.0.0.1:8000/openapi.json' $deadline
    Wait-ServiceReady $frontend 'http://127.0.0.1:3000' $deadline
    Wait-ServiceReady $frontend 'http://127.0.0.1:3000/api/openapi.json' $deadline
    Write-Host 'Open http://127.0.0.1:3000. Press Ctrl+C here to stop both servers.' -ForegroundColor Cyan
    while ($true) {
        foreach ($service in $services) {
            Assert-ServiceRunning $service
        }
        Start-Sleep -Seconds 1
    }
}
finally {
    foreach ($service in $services) {
        if (-not $service.Process.HasExited) {
            Stop-AppProcess -ProcessId $service.Process.Id
        }
    }
}

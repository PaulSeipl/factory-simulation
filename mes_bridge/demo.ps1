<#
.SYNOPSIS
    The scheduler showcase in one command: demo database, MES (8091), bridge (8766) and frontend (5173) in one
    Windows Terminal window with three panes, then the browser. See DEMO.md.

.EXAMPLE
    .\demo.ps1            # first run: creates the demo database, then starts everything
    .\demo.ps1 -Reset     # a fresh demo database (drops mes_demo first), then starts everything
    .\demo.ps1 -Solver rule   # the SPT rule without the demo config (EDD, CP-SAT on request)
    .\demo.ps1 -Stop      # stops the three servers
    .\demo.ps1 -Drop      # stops them and drops the demo database
#>
param(
    [switch]$Reset,
    [switch]$Stop,
    [switch]$Drop,
    [ValidateSet('config', 'rule')][string]$Solver = 'config',
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'

$Bridge = $PSScriptRoot                                        # ...\simulation\...\mes_bridge
$Mes = 'C:\Users\pauls\code\fidentis\PROD_DATA_MES_V2____postgres-dbms\.claude\worktrees\planner-api-loop-design-d4a13c'
if ($env:MES_WORKTREE) { $Mes = $env:MES_WORKTREE }            # another MES checkout of this branch
$Secrets = Join-Path $env:TEMP 'mes_demo_secrets.ps1'          # written by demo_db.py setup
$Work = Join-Path $env:TEMP 'mes_demo'                         # pane scripts, bridge state, logs
$DemoDb = Join-Path $Bridge 'tests\e2e\demo_db.py'
$Ports = 8091, 8766, 5173

function Stop-Demo {
    foreach ($port in $Ports) {
        $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($p in $owners) {
            # the server and its parents up to the pane's shell (uv / npm wrappers keep children alive on Windows)
            Get-CimInstance Win32_Process -Filter "ProcessId=$p" -ErrorAction SilentlyContinue |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        }
    }
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match 'mes_bridge\.runner|uvicorn app\.main:app --host 127\.0\.0\.1 --port 8091' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host 'demo servers stopped'
}

if ($Stop -or $Drop) {
    Stop-Demo
    if ($Drop) { Push-Location "$Mes\backend"; try { uv run python $DemoDb drop } finally { Pop-Location } }
    return
}

$busy = $Ports | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue }
if ($busy) { throw "port(s) $($busy -join ', ') in use: run .\demo.ps1 -Stop (or stop the other frontend on 5173)" }

# 1. the demo database (never mes_db): created on the first run or with -Reset
# (demo_scenario.py and other setups write the same secrets file for their own database)
$ours = (Test-Path $Secrets) -and (Select-String -Path $Secrets -Pattern 'POSTGRESQL_DB_NAME = "mes_demo"' -Quiet)
if ($Reset -or -not $ours) {
    Write-Host 'creating the demo database mes_demo ...'
    Push-Location "$Mes\backend"
    try { uv run python $DemoDb setup; if ($LASTEXITCODE) { throw 'demo_db.py setup failed' } } finally { Pop-Location }
    Remove-Item -Recurse -Force (Join-Path $Work 'state') -ErrorAction SilentlyContinue  # the bridge starts fresh
}

# 2. one script per pane (Windows Terminal splits its arguments at ';', so no inline commands)
New-Item -ItemType Directory -Force $Work | Out-Null
$config = if ($Solver -eq 'config') { "--config `"$Bridge\tests\e2e\demo_config.json`"" } else { '' }
@{
    'mes.ps1'      = @"
`$Host.UI.RawUI.WindowTitle = 'MES 8091'
. '$Secrets'
Set-Location '$Mes\backend'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8091
"@
    'bridge.ps1'   = @"
`$Host.UI.RawUI.WindowTitle = 'bridge 8766 ($Solver)'
. '$Secrets'
Set-Location '$Bridge'
.\.venv\Scripts\python.exe -m mes_bridge.runner --url http://127.0.0.1:8091 --port 8766 --state-dir '$Work\state' $config
"@
    'frontend.ps1' = @"
`$Host.UI.RawUI.WindowTitle = 'frontend 5173'
Set-Location '$Mes\frontend'
`$env:PUBLIC_API_URL = 'http://localhost:8091'
npm run dev
"@
}.GetEnumerator() | ForEach-Object { Set-Content -Path (Join-Path $Work $_.Key) -Value $_.Value -Encoding utf8 }

# 3. one window, three panes: MES left, bridge top right, frontend bottom right
# the shell running this script, by its full path: a terminal whose PATH lacks pwsh (IDE, elevated) made wt fail
$Shell = (Get-Process -Id $PID).Path
$pane = { param($name) "`"$Shell`" -NoExit -NoLogo -File `"$(Join-Path $Work $name)`"" }
if (Get-Command wt -ErrorAction SilentlyContinue) {
    $args_ = "-w new --title `"scheduler demo`" $(& $pane 'mes.ps1') ; split-pane -V $(& $pane 'bridge.ps1') ; " +
        "split-pane -H $(& $pane 'frontend.ps1')"
    Start-Process wt -ArgumentList $args_
} else {
    foreach ($n in 'mes.ps1', 'bridge.ps1', 'frontend.ps1') {
        Start-Process $Shell -ArgumentList '-NoExit', '-NoLogo', '-File', (Join-Path $Work $n)
    }
}

# 4. wait for the frontend, then open it
Write-Host 'waiting for the MES, the bridge and the frontend ...'
$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:8091/api/v1/openapi.json' | Out-Null
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://localhost:5173/login' | Out-Null
        break
    } catch { Start-Sleep -Seconds 2 }
}
Write-Host @"

Demo running: http://localhost:5173
  planner:  admin / admin            (Planning -> Team plan, Settings, Orders, Equipment)
  workers:  Timo / fidentis_Timo, Lukas / fidentis_Lukas, Quirin / fidentis_Quirin
  bridge decisions: $Work\state\BOUND\decisions.jsonl
Stop: .\demo.ps1 -Stop    Fresh start: .\demo.ps1 -Reset
"@
if (-not $NoBrowser) { Start-Process 'http://localhost:5173/login' }

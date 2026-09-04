param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [Parameter(Mandatory = $true)][string]$RunRoot,
    [Parameter(Mandatory = $true)][string]$FlintVendor,
    [Parameter(Mandatory = $true)][string]$AgentId,
    [string]$PythonExecutable = "python.exe"
)

$ErrorActionPreference = "Stop"
$RegistryPath = Join-Path $HOME "agent-runs.md"
$LockPath = Join-Path $HOME "agent-runs.lock"
$StatusPath = Join-Path $RunRoot "verification\external-status.jsonl"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$CurrentChild = $null
$Started = [DateTimeOffset]::Now

function Acquire-Lock {
    return [System.IO.File]::Open(
        $LockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
}

function Read-Registry {
    if (Test-Path $RegistryPath) {
        return [System.IO.File]::ReadAllText($RegistryPath, [System.Text.Encoding]::UTF8)
    }
    return "# Active External Compute Runs`n"
}

function Write-Registry([string]$Content) {
    [System.IO.File]::WriteAllText($RegistryPath, $Content, $Utf8NoBom)
}

function Locate-RunBlock([string]$Content) {
    $Marker = $Content.IndexOf($RunId, [System.StringComparison]::Ordinal)
    if ($Marker -lt 0) { throw "Reservation $RunId was not found." }
    $Start = $Content.LastIndexOf("`n## ", $Marker, [System.StringComparison]::Ordinal)
    if ($Start -lt 0) { $Start = 0 } else { $Start += 1 }
    $End = $Content.IndexOf("`n## ", $Marker, [System.StringComparison]::Ordinal)
    if ($End -lt 0) { $End = $Content.Length } else { $End += 1 }
    return @($Start, $End)
}

function Update-Registry([string]$Latest, [int]$ChildPid = 0) {
    $Lock = Acquire-Lock
    try {
        $Content = Read-Registry
        $Bounds = Locate-RunBlock $Content
        $Block = $Content.Substring($Bounds[0], $Bounds[1] - $Bounds[0])
        $Now = [DateTimeOffset]::Now
        $Pids = if ($ChildPid -gt 0) { "$PID, $ChildPid" } else { "$PID" }
        $Count = if ($ChildPid -gt 0) { "2" } else { "1" }
        $Block = [regex]::Replace($Block, '(?m)^Active process count: .*$', "Active process count: $Count")
        $Block = [regex]::Replace($Block, '(?m)^PIDs: .*$', "PIDs: $Pids")
        $Block = [regex]::Replace($Block, '(?m)^Latest progress: .*$', "Latest progress: $Latest")
        $Block = [regex]::Replace($Block, '(?m)^Progress observed: .*$', "Progress observed: $($Now.ToString('o'))")
        $Block = [regex]::Replace($Block, '(?m)^Last update: .*$', "Last update: $($Now.ToString('o'))")
        $Updated = $Content.Substring(0, $Bounds[0]) + $Block + $Content.Substring($Bounds[1])
        Write-Registry $Updated
    } finally {
        $Lock.Dispose()
    }
}
function Emit-Status([string]$State, [string]$Phase, [int]$Completed, [int]$Total, [string]$Detail) {
    $Record = [ordered]@{
        run_id = $RunId
        timestamp = [DateTimeOffset]::Now.ToString('o')
        state = $State
        phase = $Phase
        completed = $Completed
        total = $Total
        elapsed_seconds = ([DateTimeOffset]::Now - $Started).TotalSeconds
        detail = $Detail
    }
    [System.IO.File]::AppendAllText(
        $StatusPath,
        (($Record | ConvertTo-Json -Compress) + "`n"),
        $Utf8NoBom
    )
}

function Quote-Argument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-Certificate(
    [string]$Name,
    [string[]]$Arguments,
    [string]$NativeStatus,
    [string]$Stdout,
    [string]$Stderr,
    [int]$CompletedBefore,
    [int]$Total
) {
    $StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = $PythonExecutable
    $StartInfo.Arguments = (($Arguments | ForEach-Object { Quote-Argument $_ }) -join " ")
    $StartInfo.WorkingDirectory = $RunRoot
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $Process = [System.Diagnostics.Process]::new()
    $Process.StartInfo = $StartInfo
    if (-not $Process.Start()) { throw "$Name did not start." }
    $script:CurrentChild = $Process
    $StdoutTask = $Process.StandardOutput.ReadToEndAsync()
    $StderrTask = $Process.StandardError.ReadToEndAsync()
    Emit-Status "running" $Name $CompletedBefore $Total "process started"
    while (-not $Process.WaitForExit(5000)) {
        $Detail = "running"
        $NativePath = Join-Path $RunRoot $NativeStatus
        if (Test-Path $NativePath) {
            $Lines = @(Get-Content -Encoding UTF8 $NativePath)
            if ($Lines.Count -gt 0) {
                $Native = $Lines[-1] | ConvertFrom-Json
                $Detail = "phase=$($Native.phase); completed=$($Native.completed)/$($Native.total); elapsed=$([math]::Round([double]$Native.elapsed_seconds,1))s"
            }
        }
        Update-Registry "$Name; $Detail" $Process.Id
        Emit-Status "running" $Name $CompletedBefore $Total $Detail
    }
    $Process.Refresh()
    $OutText = $StdoutTask.GetAwaiter().GetResult()
    $ErrText = $StderrTask.GetAwaiter().GetResult()
    [System.IO.File]::WriteAllText((Join-Path $RunRoot $Stdout), $OutText, $Utf8NoBom)
    [System.IO.File]::WriteAllText((Join-Path $RunRoot $Stderr), $ErrText, $Utf8NoBom)
    $ExitCode = [int]$Process.ExitCode
    $script:CurrentChild = $null
    if ($ExitCode -ne 0) { throw "$Name failed with exit code $ExitCode." }
    Emit-Status "running" $Name ($CompletedBefore + 1) $Total "completed with exit code zero"
    Update-Registry "$Name completed; $($CompletedBefore + 1)/$Total" 0
}

New-Item -ItemType Directory -Force -Path (Join-Path $RunRoot "artifacts\lb") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RunRoot "artifacts\dual") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RunRoot "verification") | Out-Null
Remove-Item -Force -ErrorAction SilentlyContinue $StatusPath
$env:PYTHONPATH = $FlintVendor
$env:OMP_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS = "1"

$Lock = Acquire-Lock
try {
    $Content = Read-Registry
    if ($Content.Contains($RunId)) { throw "Reservation $RunId already exists." }
    $ReservedCores = 0
    $ReservedMemoryGiB = 0.0
    $AgentReservedCores = 0
    $AgentReservedMemoryGiB = 0.0
    foreach ($Match in [regex]::Matches($Content, '(?ms)^## .*?(?=^## |\z)')) {
        $Block = $Match.Value
        if ($Block -notmatch '(?m)^Status: (reserved|running|stale)$') { continue }
        if ($Block -notmatch '(?m)^Requested cores: ([0-9]+) logical$') { throw "Cannot parse active CPU reservation." }
        $BlockCores = [int]$Matches[1]
        $ReservedCores += $BlockCores
        if ($Block -notmatch '(?m)^Maximum aggregate memory: ([0-9.]+)GB$') { throw "Cannot parse active memory reservation." }
        $BlockMemoryGiB = [double]::Parse($Matches[1], [System.Globalization.CultureInfo]::InvariantCulture)
        $ReservedMemoryGiB += $BlockMemoryGiB
        if ($Block -match '(?m)^Agent ID: (.+)$' -and $Matches[1].Trim() -eq $AgentId) {
            $AgentReservedCores += $BlockCores
            $AgentReservedMemoryGiB += $BlockMemoryGiB
        }
    }
    if ($AgentReservedCores + 1 -gt 8) { throw "Per-agent CPU ceiling would be exceeded." }
    if ($AgentReservedMemoryGiB + 2.0 -gt 7.7) { throw "Per-agent memory ceiling would be exceeded." }
    if ($ReservedCores + 1 -gt 16) { throw "Insufficient Windows CPU capacity." }
    if ($ReservedMemoryGiB + 2.0 -gt 8.0) { throw "Insufficient Windows memory capacity." }
    $FreeMemoryGiB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
    if ($FreeMemoryGiB -lt 2.5) { throw "Insufficient free physical memory." }
    $Now = [DateTimeOffset]::Now
    $ExpectedFinish = $Now.AddMinutes(35)
    $Entry = @"

## $RunId - submission certificate replay

Project: complex-grothendieck-certificates-v4
Task: audit the verifier code and replay LB-CERT and DUAL-CERT at the exact certificate thresholds
Owner: Codex
Agent ID: $AgentId
Machine: windows
Command: python.exe relative certificate verifiers
Terminal success: the code audit, both directed verifiers, and the frozen-result checker pass
Terminal failure: any nonzero exit, nonpositive directed margin, or missing result
Estimated duration: 35m
Expected finish: $($ExpectedFinish.ToString('o'))
Started: $($Now.ToString('o'))
Requested cores: 1 logical
Maximum aggregate memory: 2GB
Workers: one single-threaded Arb verifier
Planned process count: 2
Agent CPU slot: native-windows-unenforced
Agent CPU ceiling: 8 logical processors
Guard run root: N/A; native Windows
Per-agent ceiling: within 50%
Over-50% authorization: none
Launcher PID: $PID
Process group: N/A; Windows process tree rooted at PID $PID
Active process count: 1
PIDs: $PID
Resource mode: serial directed python-flint interval arithmetic
Output: portable release artifacts
Progress source: verification/external-status.jsonl
Maximum heartbeat interval: 15s
Latest progress: reserved
Progress observed: $($Now.ToString('o'))
Status: running
Last update: $($Now.ToString('o'))
"@
    Write-Registry ($Content.TrimEnd() + "`n" + $Entry.TrimStart() + "`n")
} finally {
    $Lock.Dispose()
}

try {
    Emit-Status "running" "startup" 0 4 "reservation acquired"
    Invoke-Certificate "CODE-AUDIT" @(
        "verification/audit_code.py",
        "--root", ".",
        "--report", "verification/code-audit.json"
    ) "verification\external-status.jsonl" "verification\code-audit.stdout.log" "verification\code-audit.stderr.log" 0 4
    Invoke-Certificate "LB-CERT" @(
        "computations/certify_weighted_chaos_candidate_arb.py",
        "--run-id", "CGC-SUBMISSION-LB-REPRO",
        "--parameters-json", "computations/weighted_chaos_safe_candidate.json",
        "--threshold", "1.35584631827168",
        "--precision-digits", "180",
        "--status", "artifacts/lb/status.jsonl",
        "--output", "artifacts/lb/result.json"
    ) "artifacts\lb\status.jsonl" "artifacts\lb\stdout.log" "artifacts\lb\stderr.log" 1 4
    Invoke-Certificate "DUAL-CERT" @(
        "computations/certify_weighted_chaos_dual_mixture_arb.py",
        "--run-id", "CGC-SUBMISSION-DUAL-REPRO",
        "--candidate-json", "computations/weighted_chaos_dual_mixture_candidate.json",
        "--mode", "continuum",
        "--maximum-moment", "8",
        "--precision-digits", "80",
        "--threshold", "1.35584697425050",
        "--derivative-order", "8",
        "--cover-end", "100000",
        "--initial-step", "0.01",
        "--maximum-relative-step", "0.2",
        "--minimum-step", "1e-10",
        "--maximum-intervals", "10000",
        "--require-global-tail",
        "--status", "artifacts/dual/status.jsonl",
        "--output", "artifacts/dual/result.json"
    ) "artifacts\dual\status.jsonl" "artifacts\dual\stdout.log" "artifacts\dual\stderr.log" 2 4
    Invoke-Certificate "RESULT-CHECK" @(
        "verification/verify_results.py",
        "--root", ".",
        "--only", "all",
        "--report", "artifacts/result-check.json"
    ) "verification\external-status.jsonl" "artifacts\result-check.stdout.log" "artifacts\result-check.stderr.log" 3 4

    $PythonVersion = (& $PythonExecutable -c "import sys; print(sys.version.split()[0])").Trim()
    $FlintVersion = (& $PythonExecutable -c "import flint; print(flint.__version__)").Trim()
    $ResultCheck = Get-Content -Raw -Encoding UTF8 (Join-Path $RunRoot "artifacts\result-check.json") | ConvertFrom-Json
    $CertificateResultSha256 = [ordered]@{
        "LB-CERT" = $ResultCheck.checks.'LB-CERT'.result_sha256
        "DUAL-CERT" = $ResultCheck.checks.'DUAL-CERT'.result_sha256
    }
    $Environment = [ordered]@{
        schema_version = 1
        run_id = $RunId
        status = "passed"
        machine = "windows"
        operating_system = [System.Environment]::OSVersion.VersionString
        python_version = $PythonVersion
        python_flint_version = $FlintVersion
        requested_cores = 1
        maximum_aggregate_memory_gib = 2
        certificate_result_sha256 = $CertificateResultSha256
        started = $Started.ToString('o')
        completed = [DateTimeOffset]::Now.ToString('o')
        commands = @(
            "python3 verification/audit_code.py --root . --report verification/code-audit.json",
            "python3 computations/certify_weighted_chaos_candidate_arb.py --run-id CGC-SUBMISSION-LB-REPRO --threshold 1.35584631827168 ...",
            "python3 computations/certify_weighted_chaos_dual_mixture_arb.py --run-id CGC-SUBMISSION-DUAL-REPRO --threshold 1.35584697425050 ...",
            "python3 verification/verify_results.py --root . --only all"
        )
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $RunRoot "artifacts\external-run-environment.json"),
        (($Environment | ConvertTo-Json -Depth 8) + "`n"),
        $Utf8NoBom
    )
    Emit-Status "complete" "done" 4 4 "code audit, both certificates, and the frozen-result checker passed"
} catch {
    Emit-Status "failed" "exception" 0 4 $_.Exception.Message
    throw
} finally {
    if ($null -ne $CurrentChild -and -not $CurrentChild.HasExited) {
        $CurrentChild.Kill()
        $CurrentChild.WaitForExit()
    }
    $Lock = Acquire-Lock
    try {
        $Content = Read-Registry
        if ($Content.Contains($RunId)) {
            $Bounds = Locate-RunBlock $Content
            $Updated = $Content.Substring(0, $Bounds[0]) + $Content.Substring($Bounds[1])
            Write-Registry ($Updated.TrimEnd() + "`n")
        }
    } finally {
        $Lock.Dispose()
    }
}

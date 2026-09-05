#!/usr/bin/env python3
"""Recompute the two numerical certificates used in the paper."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import check_results


ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "verification"


def write_summary(path: Path, summary: dict) -> None:
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def progress(path: Path | None, name: str) -> None:
    if path is None or not path.exists():
        return
    try:
        record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    except (OSError, ValueError, IndexError):
        return
    phase = record.get("phase", "computing")
    if phase == "continuum-simpson-panels":
        print(f"  {name}: interval {record['interval_index']}, "
              f"quadrature panels {record['completed']}/{record['total']}", flush=True)
    elif phase == "continuum-interval-certified":
        print(f"  {name}: {record['completed']} intervals certified", flush=True)
    else:
        print(f"  {name}: {phase}", flush=True)


def run_step(name: str, command: list[str], output: Path, environment: dict,
             summary: dict, status_file: Path | None = None) -> None:
    print(f"START: {name}", flush=True)
    began = time.monotonic()
    log = output / f"{name}.log"
    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(command, cwd=ROOT, env=environment,
                                   stdout=handle, stderr=subprocess.STDOUT)
        last_progress = began
        try:
            while process.poll() is None:
                now = time.monotonic()
                if now - last_progress >= 15:
                    progress(status_file, name)
                    last_progress = now
                time.sleep(0.5)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    elapsed = time.monotonic() - began
    summary["checks"].append({"name": name, "exit_code": process.returncode,
                              "elapsed_seconds": elapsed})
    write_summary(output / "summary.json", summary)
    if process.returncode:
        detail = log.read_text(encoding="utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"{name} failed; see {log}\n{detail}")
    print(f"PASS: {name} ({elapsed:.1f}s)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("all", "lb", "dual"), default="all",
                        help="recompute both certificates (default), or one certificate")
    args = parser.parse_args()
    if not __debug__ or sys.flags.optimize:
        parser.error("run Python without -O or -OO")
    if sys.version_info < (3, 11):
        parser.error("use Python 3.11 or newer")

    try:
        import flint
    except ImportError as error:
        raise SystemExit(
            "Install the dependency first: "
            "python3 -m pip install -r verification/requirements.txt"
        ) from error
    if flint.__version__ != "0.8.0":
        raise SystemExit("This calculation uses python-flint==0.8.0.")

    # Validate the exact input before starting any interval computation.
    if args.only in ("all", "lb"):
        check_results.load_lb_candidate(ROOT)
    if args.only in ("all", "dual"):
        check_results.verify_exact_dual_input(ROOT)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = ROOT / "replay-results" / stamp
    output.mkdir(parents=True, exist_ok=False)
    print(f"Results: {output.relative_to(ROOT)}", flush=True)
    environment = os.environ.copy()
    environment.pop("PYTHONOPTIMIZE", None)
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        environment[key] = "1"
    # python-flint defaults to one thread; child processes also set this explicitly.
    summary = {"status": "running", "only": args.only, "python": sys.version,
               "python_flint": flint.__version__, "checks": []}
    write_summary(output / "summary.json", summary)

    def relative(path: Path) -> str:
        return path.relative_to(ROOT).as_posix()

    try:
        run_step("formulas",
                 [sys.executable, str(HERE / "test_formulas.py"), "--root", ".",
                  "--report", relative(output / "formulas.json")],
                 output, environment, summary)
        if args.only in ("all", "lb"):
            run_step("LB-CERT", [
                sys.executable, str(HERE / "computations/lower_bound.py"),
                "--run-id", "LB-CERT", "--parameters-json", "verification/data/lower_bound.json",
                "--threshold", "1.35584631827168", "--precision-digits", "180",
                "--status", relative(output / "lb-status.jsonl"),
                "--output", relative(output / "lb.json"),
            ], output, environment, summary, output / "lb-status.jsonl")
        if args.only in ("all", "dual"):
            # Use the original adaptive cover tolerance. The checker below
            # separately requires the sharper bound stated in the paper.
            run_step("DUAL-CERT", [
                sys.executable, str(HERE / "computations/dual_bound.py"),
                "--run-id", "DUAL-CERT", "--candidate-json", "verification/data/dual_pair.json",
                "--mode", "continuum", "--maximum-moment", "8", "--precision-digits", "80",
                "--threshold", "1.355847", "--derivative-order", "8",
                "--cover-end", "100000", "--initial-step", "0.01",
                "--maximum-relative-step", "0.2", "--minimum-step", "1e-10",
                "--maximum-intervals", "10000", "--require-global-tail",
                "--status", relative(output / "dual-status.jsonl"),
                "--output", relative(output / "dual.json"),
            ], output, environment, summary, output / "dual-status.jsonl")
        checks = check_results.verify(ROOT, output, args.only)
        print("PASS: the paper's strict bounds and all result-consistency checks", flush=True)
        run_step("failure-tests", [
            sys.executable, str(HERE / "test_checks.py"),
            "--results", str(output), "--only", args.only,
        ], output, environment, summary)
        summary["status"] = "passed"
        summary["certificates"] = list(checks)
        write_summary(output / "summary.json", summary)
        print("VERIFIED: " + " and ".join(checks) +
              f"; results: {output.relative_to(ROOT)}", flush=True)
        return 0
    except BaseException as error:
        summary["status"] = "failed"
        summary["error"] = str(error)
        write_summary(output / "summary.json", summary)
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise SystemExit(f"FAILED: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())

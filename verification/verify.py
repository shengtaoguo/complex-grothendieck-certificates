#!/usr/bin/env python3
"""Verify the frozen complex Grothendieck certificate repository."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "verification" / "verify_results.py"


def main() -> int:
    if not CHECKER.is_file():
        raise SystemExit(
            f"checker is missing from the repository: {CHECKER.relative_to(ROOT)}"
        )

    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONUNBUFFERED": "1",
        }
    )
    command = [
        sys.executable,
        str(CHECKER),
        "--root",
        ".",
        "--only",
        "all",
        "--audit-bundle",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        return completed.returncode

    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"checker returned invalid JSON: {error}") from error
    if report.get("status") != "passed":
        raise SystemExit("checker did not report status=passed")
    checks = report.get("checks")
    if not isinstance(checks, dict) or set(checks) != {"LB-CERT", "DUAL-CERT"}:
        raise SystemExit("checker did not verify exactly LB-CERT and DUAL-CERT")
    if any(record.get("status") != "passed" for record in checks.values()):
        raise SystemExit("one or more certificate checks did not pass")

    bundle = report.get("bundle_audit")
    if not isinstance(bundle, dict) or bundle.get("status") != "passed":
        raise SystemExit("repository audit did not pass")
    release_status = bundle.get("release_status")
    submission_ready = str(bool(bundle.get("submission_ready"))).lower()
    print(
        "VERIFIED: LB-CERT and DUAL-CERT; "
        f"release_status={release_status}; submission_ready={submission_ready}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

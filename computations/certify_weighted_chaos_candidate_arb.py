#!/usr/bin/env python3
"""Directed Arb certification for a parameterized two-pole candidate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import traceback

import certify_ten_chaos_arb as certificate


def bundle_relative_path(path: Path) -> str:
    root = Path.cwd().resolve()
    resolved = path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(
            f"certificate input lies outside the bundle root: {path}"
        ) from error


def emit_status(path: Path, run_id: str, **record: object) -> None:
    payload = dict(record)
    payload["run_id"] = run_id
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def load_decimal_candidate(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"), parse_float=str)
    for key in ("candidate", "final"):
        if key in payload:
            payload = payload[key]
            break
    required = ("rho", "beta", "alpha", "eta", "zeta", "delta")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"candidate is missing fields: {missing}")
    if len(payload["beta"]) != 10 or len(payload["zeta"]) != 2 or len(payload["delta"]) != 2:
        raise ValueError("candidate must contain ten beta values and two poles")
    return {key: payload[key] for key in required}


def install_candidate(
    candidate_parameters: dict[str, object],
    run_id: str,
    threshold: str,
) -> None:
    certificate.RUN_ID = run_id
    certificate.CERTIFIED_THRESHOLD_TEXT = threshold
    certificate.RHO_TEXT = str(candidate_parameters["rho"])
    certificate.BETA_TEXTS = [
        str(value) for value in candidate_parameters["beta"]
    ]
    certificate.WEIGHT_TEXTS = {
        "alpha": str(candidate_parameters["alpha"]),
        "eta": str(candidate_parameters["eta"]),
        "zeta1": str(candidate_parameters["zeta"][0]),
        "zeta2": str(candidate_parameters["zeta"][1]),
        "delta1": str(candidate_parameters["delta"][0]),
        "delta2": str(candidate_parameters["delta"][1]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--parameters-json", type=Path, required=True)
    parser.add_argument("--threshold", required=True)
    parser.add_argument("--precision-digits", type=int, default=180)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--startup-delay", type=float, default=0.0)
    arguments = parser.parse_args()

    arguments.status.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    emit_status(
        arguments.status,
        arguments.run_id,
        state="running",
        phase="startup",
        completed=0,
        total=4,
        elapsed_seconds=0.0,
        estimated_remaining_seconds="unknown",
    )
    if arguments.startup_delay:
        time.sleep(arguments.startup_delay)
    started = time.monotonic()

    try:
        candidate_parameters = load_decimal_candidate(arguments.parameters_json)
        install_candidate(
            candidate_parameters,
            arguments.run_id,
            arguments.threshold,
        )
        result = certificate.certify(
            arguments.precision_digits,
            arguments.status,
        )
        source_path = Path(__file__).resolve()
        verifier_source = source_path.with_name("certify_ten_chaos_arb.py")
        result["role"] = (
            "directed Arb verification of the optimized ten-chaos two-pole "
            "unrestricted complex lower certificate"
        )
        result["source"] = {
            "path": bundle_relative_path(source_path),
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "verifier_path": bundle_relative_path(verifier_source),
            "verifier_sha256": hashlib.sha256(
                verifier_source.read_bytes()
            ).hexdigest(),
            "parameters_path": bundle_relative_path(arguments.parameters_json),
            "parameters_sha256": hashlib.sha256(
                arguments.parameters_json.read_bytes()
            ).hexdigest(),
        }
        result["elapsed_seconds"] = time.monotonic() - started
        arguments.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        emit_status(
            arguments.status,
            arguments.run_id,
            state="complete",
            phase="done",
            completed=4,
            total=4,
            elapsed_seconds=result["elapsed_seconds"],
            estimated_remaining_seconds=0.0,
            output=str(arguments.output),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    except Exception as error:
        emit_status(
            arguments.status,
            arguments.run_id,
            state="failed",
            phase="error",
            completed=0,
            total=4,
            elapsed_seconds=time.monotonic() - started,
            estimated_remaining_seconds=0.0,
            error=repr(error),
            traceback=traceback.format_exc(),
        )
        raise


if __name__ == "__main__":
    main()

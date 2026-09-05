#!/usr/bin/env python3
"""Test rejection of deliberately damaged copies of freshly computed results."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tempfile

import check_results as checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--only", choices=("all", "lb", "dual"), default="all")
    args = parser.parse_args()
    checks.verify(checks.ROOT, args.results, args.only)
    count = 0

    def reject(operation, name: str) -> None:
        nonlocal count
        try:
            operation()
        except (OSError, ValueError, TypeError, KeyError, ArithmeticError):
            count += 1
        else:
            raise AssertionError(f"invalid input was accepted: {name}")

    for text in ("nan", "inf", "[-inf,+inf]", "[1 +/- -0.1]", "[1", "1]", ""):
        reject(lambda text=text: checks.ball_bounds(text), "malformed interval " + text)

    with tempfile.TemporaryDirectory(prefix="cgc-checks-") as folder:
        root = Path(folder)
        data = root / "verification/data"
        results = root / "results"
        data.mkdir(parents=True)
        results.mkdir()
        inputs = {
            "lower_bound.json": checks.load_json(checks.ROOT / "verification/data/lower_bound.json"),
            "dual_pair.json": checks.load_json(checks.ROOT / "verification/data/dual_pair.json"),
        }
        baseline = {}
        for name in ("lb", "dual"):
            if args.only in ("all", name):
                baseline[name + ".json"] = checks.load_json(args.results / (name + ".json"))

        def write(path: Path, value) -> None:
            path.write_text(json.dumps(value), encoding="utf-8")

        def restore() -> None:
            for name, value in inputs.items():
                write(data / name, value)
            for name, value in baseline.items():
                write(results / name, value)

        def mutate_result(name: str, label: str, mutation) -> None:
            restore()
            value = copy.deepcopy(baseline[name + ".json"])
            mutation(value)
            write(results / (name + ".json"), value)
            reject(lambda: checks.verify(root, results, name), label)

        def mutate_input(name: str, label: str, mutation) -> None:
            restore()
            file = "lower_bound.json" if name == "lb" else "dual_pair.json"
            value = copy.deepcopy(inputs[file])
            mutation(value)
            write(data / file, value)
            reject(lambda: checks.verify(root, results, name), label)

        for name in baseline:
            restore()
            (results / name).unlink()
            reject(lambda: checks.verify(root, results, args.only), "missing " + name)
        malformed = root / "malformed.json"
        for text in ('{"a": 1, "a": 2}', '{"a": NaN}', '[]', '{'):
            malformed.write_text(text, encoding="utf-8")
            reject(lambda: checks.load_json(malformed), "malformed JSON")

        if args.only in ("all", "lb"):
            for label, mutation in [
                ("failed LB status", lambda r: r.update(status="failed")),
                ("wrong LB proof type", lambda r: r.update(proof_status="floating point only")),
                ("altered LB parameters", lambda r: r["parameters"].update(rho="0.5")),
                ("missing residual block", lambda r: r["residual_blocks"].pop()),
                ("duplicate residual block", lambda r: r["residual_blocks"].__setitem__(1, copy.deepcopy(r["residual_blocks"][0]))),
                ("missing pivot", lambda r: r["residual_blocks"][0]["pivot_lower_bounds"].pop()),
                ("negative pivot", lambda r: r["residual_blocks"][0]["pivot_lower_bounds"].__setitem__(0, "[-1 +/- 0.1]")),
                ("nonpositive Schur margin", lambda r: r["woodbury_margin"].update(lower="0")),
                ("weak lower bound", lambda r: r["lower_ratio"].update(lower="1.35")),
                ("excessive weight integral", lambda r: r["mu_weight"].update(upper="0.8")),
                ("invalid root enclosure", lambda r: r["weight_poles"][0].update(ball="nan")),
                ("wrong numerical precision", lambda r: r["library"].update(precision_digits=53)),
            ]:
                mutate_result("lb", label, mutation)
            mutate_input("lb", "rho outside range", lambda r: r.update(rho="1"))
            mutate_input("lb", "negative coefficient", lambda r: r["beta"].__setitem__(0, "-1"))
            mutate_input("lb", "zero weight constant", lambda r: r.update(alpha="0"))

        if args.only in ("all", "dual"):
            for label, mutation in [
                ("failed DUAL status", lambda r: r.update(status="failed")),
                ("point grid instead of continuum", lambda r: r["configuration"].update(mode="points")),
                ("missing atoms", lambda r: r["atoms"].pop()),
                ("mismatched atoms", lambda r: r["atoms"][0].update(q="0.5")),
                ("missing interval", lambda r: r["continuum"]["intervals"].pop()),
                ("gap in cover", lambda r: r["continuum"]["intervals"][1].update(left="0.02")),
                ("overlap in cover", lambda r: r["continuum"]["intervals"][1].update(left="0")),
                ("empty interval", lambda r: r["continuum"]["intervals"][0].update(right="0")),
                ("wrong interval width", lambda r: r["continuum"]["intervals"][0].update(width="1")),
                ("only coarse bound", lambda r: r["continuum"]["intervals"][0].update(interval_upper="1.35584699")),
                ("inconsistent polynomial bound", lambda r: r["continuum"]["intervals"][0].update(polynomial_upper="0")),
                ("missing analytic tail", lambda r: r["continuum"].pop("global_tail")),
                ("uncertified tail", lambda r: r["continuum"]["global_tail"].update(certified=False)),
                ("oversized tail", lambda r: r["continuum"]["global_tail"].update(squared_upper="1.4")),
                ("wrong derivative order", lambda r: r["configuration"].update(computed_moment_order=2)),
                ("negative error bound", lambda r: r["continuum"]["intervals"][0].update(largest_simpson_error="-1")),
            ]:
                mutate_result("dual", label, mutation)
            mutate_input("dual", "atom outside (0,1)", lambda r: r["atoms"][0].update(q="1"))
            mutate_input("dual", "weights not normalized", lambda r: r["atoms"][0].update(weight="1"))
            mutate_input("dual", "negative atom weight", lambda r: r["atoms"][0].update(weight="-1"))
    print(f"PASS: {count} malformed or inconsistent inputs rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

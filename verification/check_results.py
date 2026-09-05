#!/usr/bin/env python3
"""Check fresh computation results against the paper's numerical claims.

These checks validate recorded inequalities and their consistency.
They do not replace the Arb recomputation performed by verify.py.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLAIMS = {
    "LB-CERT": {
        "statement": "K_G^C > 1.35584631827168",
        "threshold": "1.35584631827168",
        "precision_digits": 180,
        "minimum_residual_pivot": "1.2259567912e-5",
        "minimum_woodbury_margin": "1.8374949151e-9",
        "maximum_mu_weight": "0.716627735168304",
        "residual_block_count": 132,
        "pivot_count": 570
    },
    "DUAL-CERT": {
        "statement": "K_* < 1.35584697425050",
        "threshold": "1.35584697425050",
        "coarse_threshold": "1.355847",
        "minimum_coarse_margin": "2.57e-8",
        "precision_digits": 80,
        "maximum_moment": 8,
        "derivative_order": 8,
        "panel_count": 600,
        "integration_cutoff": "8",
        "initial_step": "0.01",
        "maximum_relative_step": "0.2",
        "minimum_step": "1e-10",
        "atom_count": 180,
        "interval_count": 98,
        "cover_start": "0",
        "cover_end": "100000",
        "maximum_tail_square": "0.238636"
    }
}
BALL_RE = re.compile(
    r"^\[?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?:\s*\+/-\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))?\s*\]?$"
)


class VerificationError(ValueError):
    pass


def reject_constant(value: str) -> None:
    raise VerificationError(f"nonfinite JSON value: {value}")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"),
                       parse_constant=reject_constant, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise VerificationError(f"{path.name} must contain a JSON object")
    return value


def ball_bounds(value: object) -> tuple[Fraction, Fraction]:
    if not isinstance(value, str):
        raise VerificationError(f"expected an Arb string, received {value!r}")
    if value.strip().startswith("[") != value.strip().endswith("]"):
        raise VerificationError(f"unmatched brackets in Arb enclosure {value!r}")
    match = BALL_RE.fullmatch(value.strip())
    if match is None:
        raise VerificationError(f"cannot parse Arb enclosure {value!r}")
    midpoint = Fraction(match.group(1))
    radius = Fraction(match.group(2) or "0")
    if radius < 0:
        raise VerificationError(f"negative Arb radius in {value!r}")
    return midpoint - radius, midpoint + radius

def record_bounds(record: object, field: str) -> tuple[Fraction, Fraction]:
    if not isinstance(record, dict) or field not in record:
        raise VerificationError(f"missing interval field {field}")
    return ball_bounds(record[field])

def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)

def intervals_overlap(
    first: tuple[Fraction, Fraction],
    second: tuple[Fraction, Fraction],
) -> bool:
    return max(first[0], second[0]) <= min(first[1], second[1])

def require_overlap(
    first: tuple[Fraction, Fraction],
    second: tuple[Fraction, Fraction],
    message: str,
) -> None:
    require(intervals_overlap(first, second), message)

def load_lb_candidate(root: Path) -> dict[str, Any]:
    payload = load_json(root / "verification/data/lower_bound.json")
    for key in ("candidate", "final"):
        if key in payload:
            payload = payload[key]
            break
    require(isinstance(payload, dict), "LB candidate payload is not an object")
    required = ("rho", "beta", "alpha", "eta", "zeta", "delta")
    require(all(key in payload for key in required), "LB candidate is missing parameters")
    beta = payload["beta"]
    zeta = payload["zeta"]
    delta = payload["delta"]
    require(isinstance(beta, list) and len(beta) == 10, "LB candidate must have ten beta values")
    require(isinstance(zeta, list) and len(zeta) == 2, "LB candidate must have two zeta values")
    require(isinstance(delta, list) and len(delta) == 2, "LB candidate must have two delta values")
    rho = Fraction(str(payload["rho"]))
    beta_values = [Fraction(str(value)) for value in beta]
    weight_values = [
        Fraction(str(payload["alpha"])),
        Fraction(str(payload["eta"])),
        *(Fraction(str(value)) for value in zeta),
        *(Fraction(str(value)) for value in delta),
    ]
    require(Fraction(0) < rho < Fraction(1), "LB rho lies outside (0,1)")
    require(all(value > 0 for value in beta_values), "LB beta is not positive")
    require(all(value > 0 for value in weight_values), "LB weight parameter is not positive")
    return {
        "rho": str(payload["rho"]),
        "beta": [str(value) for value in beta],
        "weight": {
            "alpha": str(payload["alpha"]),
            "eta": str(payload["eta"]),
            "zeta1": str(zeta[0]),
            "zeta2": str(zeta[1]),
            "delta1": str(delta[0]),
            "delta2": str(delta[1]),
        },
    }

def verify_exact_dual_input(root: Path) -> dict[str, Any]:
    payload = load_json(root / "verification/data/dual_pair.json")
    atoms = payload.get("atoms")
    require(isinstance(atoms, list), "DUAL atom list is missing")
    claim = CLAIMS["DUAL-CERT"]
    require(len(atoms) == claim["atom_count"], "DUAL atom count mismatch")
    q_values = [Fraction(str(atom["q"])) for atom in atoms]
    weights = [Fraction(str(atom["weight"])) for atom in atoms]
    require(all(Fraction(0) < q < Fraction(1) for q in q_values), "DUAL atom lies outside (0,1)")
    require(all(weight > 0 for weight in weights), "DUAL atom weight is not positive")
    require(sum(weights, Fraction(0)) == Fraction(1), "DUAL weights do not sum exactly to one")
    return payload

def verify_lb(root: Path, results: Path) -> dict[str, Any]:
    claim = CLAIMS["LB-CERT"]
    expected_parameters = load_lb_candidate(root)
    result = load_json(results / "lb.json")
    require(result.get("status") == "passed", "LB-CERT status is not passed")
    require(
        result.get("proof_status") == "directed ball-arithmetic certificate",
        "LB-CERT proof status is incorrect",
    )
    library = result.get("library", {})
    require(isinstance(library, dict), "LB-CERT library record is missing")
    require(library.get("python_flint_version") == "0.8.0", "LB-CERT used the wrong python-flint version")
    require(library.get("precision_digits") == claim["precision_digits"], "LB-CERT precision mismatch")
    parameters = result.get("parameters", {})
    require(isinstance(parameters, dict), "LB-CERT parameter record is missing")
    require(parameters.get("certified_threshold") == claim["threshold"], "LB-CERT threshold mismatch")
    require(parameters.get("interpretation") == "exact terminating decimals", "LB parameter interpretation mismatch")
    for field in ("rho", "beta", "weight"):
        require(parameters.get(field) == expected_parameters[field], f"LB {field} differs from the frozen input")

    mu_bounds = record_bounds(result.get("mu_weight"), "ball")
    scalar_bounds = record_bounds(result.get("scalar_norm_bound"), "ball")
    rho = Fraction(expected_parameters["rho"])
    expected_scalar_bounds = (rho + mu_bounds[0], rho + mu_bounds[1])
    require_overlap(scalar_bounds, expected_scalar_bounds, "LB scalar bound is inconsistent with rho + mu_W")
    require(scalar_bounds[0] > 0, "LB scalar denominator is not positive")

    ratio_bounds = record_bounds(result.get("lower_ratio"), "ball")
    expected_ratio_bounds = (
        (Fraction(1) - rho) / scalar_bounds[1],
        (Fraction(1) - rho) / scalar_bounds[0],
    )
    require_overlap(ratio_bounds, expected_ratio_bounds, "LB ratio is inconsistent with its scalar bound")
    ratio_lower, _ = record_bounds(result.get("lower_ratio"), "lower")
    require(ratio_lower > Fraction(claim["threshold"]), "LB ratio does not exceed the theorem threshold")
    ratio_margin_bounds = record_bounds(result.get("ratio_margin_over_certified_threshold"), "ball")
    expected_ratio_margin = (
        ratio_bounds[0] - Fraction(claim["threshold"]),
        ratio_bounds[1] - Fraction(claim["threshold"]),
    )
    require_overlap(ratio_margin_bounds, expected_ratio_margin, "LB ratio margin is inconsistent")
    require(ratio_margin_bounds[0] > 0, "LB ratio margin is not positive")

    pivot_lower, _ = ball_bounds(result.get("worst_residual_pivot", {}).get("lower_bound"))
    require(pivot_lower > Fraction(claim["minimum_residual_pivot"]), "LB residual-pivot margin is too small")
    woodbury_lower, _ = record_bounds(result.get("woodbury_margin"), "lower")
    require(woodbury_lower > Fraction(claim["minimum_woodbury_margin"]), "LB Woodbury margin is too small")
    xi_bounds = record_bounds(result.get("xi"), "ball")
    woodbury_bounds = record_bounds(result.get("woodbury_margin"), "ball")
    require_overlap(
        woodbury_bounds,
        (Fraction(1) - xi_bounds[1], Fraction(1) - xi_bounds[0]),
        "LB Woodbury margin is inconsistent with 1 - xi",
    )
    cancellation_lower, _ = record_bounds(result.get("cancellation_free_quantity"), "lower")
    require(cancellation_lower > 0, "LB cancellation-free Woodbury quantity is not positive")
    main_pivot_lower, _ = ball_bounds(result.get("main_minimum_pivot_lower_bound"))
    require(main_pivot_lower > 0, "LB main-matrix pivot is not positive")
    _, mu_upper = record_bounds(result.get("mu_weight"), "upper")
    require(mu_upper < Fraction(claim["maximum_mu_weight"]), "LB mu_W upper bound is too large")

    for field in ("weight_poles", "shifted_poles"):
        poles = result.get(field)
        require(isinstance(poles, list) and len(poles) == 3, f"LB {field} must contain three poles")
        for pole in poles:
            pole_lower, _ = record_bounds(pole, "ball")
            require(pole_lower > 0, f"LB {field} contains a nonpositive pole")

    blocks = result.get("residual_blocks")
    require(isinstance(blocks, list), "LB residual block list is missing")
    require(len(blocks) == claim["residual_block_count"], "LB residual block count mismatch")
    expected_blocks = {
        (residual_p, residual_q): len(
            [
                ell
                for ell in range(1, 11)
                if residual_p <= ell + 1 and residual_q <= ell
            ]
        )
        for residual_p in range(12)
        for residual_q in range(11)
    }
    observed_blocks: dict[tuple[int, int], tuple[Fraction, Fraction]] = {}
    pivot_count = 0
    all_pivot_bounds: list[tuple[Fraction, Fraction]] = []
    for block in blocks:
        require(isinstance(block, dict), "LB residual block record is not an object")
        bidegree = block.get("residual_bidegree")
        require(
            isinstance(bidegree, list)
            and len(bidegree) == 2
            and all(type(value) is int for value in bidegree),
            "LB residual bidegree is malformed",
        )
        key = (bidegree[0], bidegree[1])
        require(key in expected_blocks, f"LB has an unexpected residual block {key}")
        require(key not in observed_blocks, f"LB repeats residual block {key}")
        expected_size = expected_blocks[key]
        require(block.get("size") == expected_size, f"LB residual block {key} has the wrong size")
        pivots = block.get("pivot_lower_bounds")
        require(isinstance(pivots, list) and len(pivots) == expected_size, f"LB residual block {key} has the wrong pivot count")
        local_bounds = [ball_bounds(pivot) for pivot in pivots]
        for lower, _ in local_bounds:
            require(lower > 0, "LB contains a nonpositive residual pivot")
        local_minimum = (
            min(bounds[0] for bounds in local_bounds),
            min(bounds[1] for bounds in local_bounds),
        )
        reported_minimum = ball_bounds(block.get("minimum_pivot_lower_bound"))
        require_overlap(reported_minimum, local_minimum, f"LB residual block {key} minimum is inconsistent")
        observed_blocks[key] = local_minimum
        all_pivot_bounds.extend(local_bounds)
        pivot_count += len(pivots)
    require(set(observed_blocks) == set(expected_blocks), "LB residual block set is incomplete")
    require(pivot_count == claim["pivot_count"], "LB pivot count mismatch")
    computed_worst = (
        min(bounds[0] for bounds in all_pivot_bounds),
        min(bounds[1] for bounds in all_pivot_bounds),
    )
    reported_worst = ball_bounds(result.get("worst_residual_pivot", {}).get("lower_bound"))
    require_overlap(reported_worst, computed_worst, "LB worst residual pivot is inconsistent with the block records")
    reported_worst_block = result.get("worst_residual_pivot", {}).get("block")
    require(
        isinstance(reported_worst_block, list)
        and len(reported_worst_block) == 2
        and tuple(reported_worst_block) in observed_blocks,
        "LB worst residual block is malformed",
    )
    require_overlap(
        observed_blocks[tuple(reported_worst_block)],
        computed_worst,
        "LB worst residual block does not contain the recorded worst pivot",
    )

    return {
        "status": "passed",
        "claim": claim["statement"],
        "ratio_lower": str(ratio_lower),
        "worst_residual_pivot_lower": str(pivot_lower),
        "woodbury_margin_lower": str(woodbury_lower),
        "mu_weight_upper": str(mu_upper),
        "residual_block_count": len(blocks),
        "pivot_count": pivot_count,
    }

def verify_dual(root: Path, results: Path) -> dict[str, Any]:
    claim = CLAIMS["DUAL-CERT"]
    candidate = verify_exact_dual_input(root)
    result = load_json(results / "dual.json")
    require(result.get("status") == "completed", "DUAL-CERT status is not completed")
    require(
        result.get("proof_status") == "directed continuum ceiling certificate",
        "DUAL-CERT proof status is incorrect",
    )
    require(result.get("target_squared_ceiling") == claim["coarse_threshold"], "DUAL-CERT cover threshold mismatch")
    library = result.get("library", {})
    require(isinstance(library, dict), "DUAL-CERT library record is missing")
    require(library.get("python_flint_version") == "0.8.0", "DUAL-CERT used the wrong python-flint version")
    configuration = result.get("configuration", {})
    require(isinstance(configuration, dict), "DUAL-CERT configuration record is missing")
    require(configuration.get("precision_digits") == claim["precision_digits"], "DUAL-CERT precision mismatch")
    require(configuration.get("mode") == "continuum", "DUAL-CERT did not run in continuum mode")
    require(configuration.get("maximum_moment") == claim["maximum_moment"], "DUAL maximum moment mismatch")
    require(
        configuration.get("computed_moment_order") == claim["maximum_moment"],
        "DUAL computed moment order mismatch",
    )
    require(configuration.get("derivative_order") == claim["derivative_order"], "DUAL derivative order mismatch")
    require(configuration.get("panel_count") == claim["panel_count"], "DUAL Simpson panel count mismatch")
    require(configuration.get("integration_cutoff") == claim["integration_cutoff"], "DUAL integration cutoff mismatch")
    require(configuration.get("cover_end") == claim["cover_end"], "DUAL configured cover endpoint mismatch")
    require(configuration.get("initial_step") == claim["initial_step"], "DUAL initial step mismatch")
    require(configuration.get("maximum_relative_step") == claim["maximum_relative_step"], "DUAL relative-step cap mismatch")
    require(configuration.get("minimum_step") == claim["minimum_step"], "DUAL minimum step mismatch")
    require(configuration.get("require_global_tail") is True, "DUAL global tail was not required")
    require(configuration.get("points") is None, "DUAL continuum run unexpectedly contains a point configuration")
    require(result.get("atoms") == candidate["atoms"], "DUAL parameters differ from the exact input")
    require(result.get("atom_count") == claim["atom_count"], "DUAL result atom count mismatch")
    weight_sum_lower, weight_sum_upper = record_bounds(result.get("weight_sum"), "ball")
    require(weight_sum_lower <= Fraction(1) <= weight_sum_upper, "DUAL reported weight sum does not enclose one")
    require(result.get("points") == [], "DUAL continuum result unexpectedly contains point records")

    continuum = result.get("continuum")
    require(isinstance(continuum, dict), "DUAL continuum record is missing")
    require(continuum.get("cover_start") == claim["cover_start"], "DUAL cover start mismatch")
    require(continuum.get("cover_end") == claim["cover_end"], "DUAL cover end mismatch")
    require(continuum.get("interval_count") == claim["interval_count"], "DUAL interval count mismatch")
    require(continuum.get("derivative_order") == claim["derivative_order"], "DUAL continuum derivative order mismatch")
    threshold = Fraction(claim["threshold"])
    cover_threshold = Fraction(claim["coarse_threshold"])

    intervals = continuum.get("intervals")
    require(isinstance(intervals, list), "DUAL interval list is missing")
    require(len(intervals) == claim["interval_count"], "DUAL interval list length mismatch")
    expected_left = Fraction(claim["cover_start"])
    interval_upper_bounds: list[tuple[Fraction, Fraction]] = []
    margin_bounds: list[tuple[Fraction, Fraction]] = []
    for interval in intervals:
        require(isinstance(interval, dict), "DUAL interval record is not an object")
        left = Fraction(interval["left"])
        right = Fraction(interval["right"])
        width = Fraction(interval["width"])
        require(left == expected_left, "DUAL continuum cover has a gap or overlap")
        require(right > left, "DUAL continuum interval is empty")
        require(width == right - left, "DUAL interval width is inconsistent with its endpoints")
        upper_bounds = ball_bounds(interval["interval_upper"])
        interval_upper = upper_bounds[1]
        require(interval_upper < threshold, "DUAL interval exceeds the theorem threshold")
        current_margin_bounds = ball_bounds(interval["margin_lower"])
        margin_lower = current_margin_bounds[0]
        require(margin_lower > 0, "DUAL interval margin is not positive")
        require_overlap(
            current_margin_bounds,
            (cover_threshold - upper_bounds[1], cover_threshold - upper_bounds[0]),
            "DUAL interval margin is inconsistent with its upper bound",
        )
        polynomial_bounds = ball_bounds(interval["polynomial_upper"])
        remainder_bounds = ball_bounds(interval["remainder_upper"])
        require(remainder_bounds[0] >= 0, "DUAL Taylor remainder is negative")
        require_overlap(
            upper_bounds,
            (
                polynomial_bounds[0] + remainder_bounds[0],
                polynomial_bounds[1] + remainder_bounds[1],
            ),
            "DUAL interval upper bound is inconsistent with its polynomial and remainder",
        )
        derivative_bounds = ball_bounds(interval["derivative_bound"])
        simpson_bounds = ball_bounds(interval["largest_simpson_error"])
        gaussian_tail_bounds = ball_bounds(interval["largest_gaussian_tail"])
        require(derivative_bounds[0] >= 0, "DUAL derivative bound is negative")
        require(simpson_bounds[0] >= 0, "DUAL Simpson error bound is negative")
        require(gaussian_tail_bounds[0] >= 0, "DUAL Gaussian tail bound is negative")
        interval_upper_bounds.append(upper_bounds)
        margin_bounds.append(current_margin_bounds)
        expected_left = right
    require(expected_left == Fraction(claim["cover_end"]), "DUAL continuum cover has the wrong endpoint")

    observed_maximum = (
        max(bounds[0] for bounds in interval_upper_bounds),
        max(bounds[1] for bounds in interval_upper_bounds),
    )
    reported_maximum = ball_bounds(continuum.get("maximum_interval_upper"))
    require_overlap(reported_maximum, observed_maximum, "DUAL maximum interval summary is inconsistent")
    maximum_upper = observed_maximum[1]
    require(maximum_upper < threshold, "DUAL continuum upper bound does not beat the theorem threshold")
    observed_worst_margin = (
        min(bounds[0] for bounds in margin_bounds),
        min(bounds[1] for bounds in margin_bounds),
    )
    reported_worst_margin = ball_bounds(continuum.get("worst_interval_margin_lower"))
    require_overlap(reported_worst_margin, observed_worst_margin, "DUAL worst-margin summary is inconsistent")
    coarse_margin = Fraction(claim["coarse_threshold"]) - maximum_upper
    require(coarse_margin > Fraction(claim["minimum_coarse_margin"]), "DUAL coarse safety margin is too small")

    tail = continuum.get("global_tail", {})
    require(isinstance(tail, dict), "DUAL global tail record is missing")
    require(tail.get("required") is True and tail.get("certified") is True, "DUAL global tail is not certified")
    require(tail.get("inequality_exponent") == "3/4", "DUAL global tail used the wrong exponent")
    tail_square_bounds = ball_bounds(tail.get("squared_upper"))
    tail_upper = tail_square_bounds[1]
    require(tail_upper < Fraction(claim["maximum_tail_square"]), "DUAL global tail bound is too large")
    require(tail_upper < threshold, "DUAL global tail exceeds the theorem threshold")
    tail_margin_bounds = ball_bounds(tail.get("margin_lower"))
    require(tail_margin_bounds[0] > 0, "DUAL global tail margin is not positive")
    require_overlap(
        tail_margin_bounds,
        (cover_threshold - tail_square_bounds[1], cover_threshold - tail_square_bounds[0]),
        "DUAL global tail margin is inconsistent",
    )
    x_bounds = ball_bounds(tail.get("x_upper"))
    y_bounds = ball_bounds(tail.get("y_upper"))
    require(x_bounds[0] >= 0 and y_bounds[0] >= 0, "DUAL global tail component is negative")
    require_overlap(
        tail_square_bounds,
        (
            x_bounds[0] * x_bounds[0] + y_bounds[0] * y_bounds[0],
            x_bounds[1] * x_bounds[1] + y_bounds[1] * y_bounds[1],
        ),
        "DUAL squared tail is inconsistent with its component bounds",
    )

    return {
        "status": "passed",
        "claim": claim["statement"],
        "maximum_interval_upper": str(maximum_upper),
        "exact_threshold_margin": str(threshold - maximum_upper),
        "coarse_threshold_margin": str(coarse_margin),
        "tail_square_upper": str(tail_upper),
        "atom_count": result["atom_count"],
        "interval_count": continuum["interval_count"],
    }

def verify(root: Path, results: Path, only: str = "all") -> dict[str, Any]:
    checks = {}
    if only in ("all", "lb"):
        checks["LB-CERT"] = verify_lb(root, results)
    if only in ("all", "dual"):
        checks["DUAL-CERT"] = verify_dual(root, results)
    require(bool(checks), "no certificate was selected")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--only", choices=("all", "lb", "dual"), default="all")
    args = parser.parse_args()
    try:
        checks = verify(ROOT, args.results, args.only)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError) as error:
        raise SystemExit(f"FAILED: {error}") from error
    print("PASS: numerical bounds and result consistency (" + ", ".join(checks) + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

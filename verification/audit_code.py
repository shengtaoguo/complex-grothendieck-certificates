#!/usr/bin/env python3
"""Independent structural and formula-level smoke tests for certificate code."""

from __future__ import annotations

import argparse
import ast
from fractions import Fraction
import importlib
import json
import math
from pathlib import Path
import sys
from typing import Any


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def arb_intervals_overlap(first: Any, second: Any) -> bool:
    difference = first - second
    return not (difference.lower() > 0 or difference.upper() < 0)


def direct_radial_product(
    arb_type: Any,
    first_p: int,
    first_q: int,
    second_p: int,
    second_q: int,
) -> list[Any]:
    require(
        first_p - first_q == second_p - second_q,
        "direct radial products require equal angular charge",
    )

    def radial_factor(p_value: int, q_value: int) -> dict[int, Any]:
        normalization = arb_type(math.factorial(p_value) * math.factorial(q_value)).sqrt()
        factor: dict[int, Any] = {}
        for index in range(min(p_value, q_value) + 1):
            coefficient = (
                (-1) ** index
                * math.factorial(index)
                * math.comb(p_value, index)
                * math.comb(q_value, index)
            )
            power = p_value + q_value - 2 * index
            factor[power] = arb_type(coefficient) / normalization
        return factor

    first = radial_factor(first_p, first_q)
    second = radial_factor(second_p, second_q)
    maximum_degree = (
        first_p + first_q + second_p + second_q
    ) // 2
    result = [arb_type(0) for _ in range(maximum_degree + 1)]
    for first_power, first_coefficient in first.items():
        for second_power, second_coefficient in second.items():
            total_power = first_power + second_power
            require(total_power % 2 == 0, "direct radial product has an odd power")
            result[total_power // 2] += first_coefficient * second_coefficient
    return result


def audit_python_sources(root: Path) -> dict[str, int]:
    files = sorted((root / "computations").glob("*.py"))
    files.append(root / "verification/verify_results.py")
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {"parsed_file_count": len(files)}


def audit_lower_bound_code(root: Path, core: Any, wrapper: Any, arb_type: Any) -> dict[str, int]:
    products: set[tuple[int, int, int, int]] = set()
    for residual_p in range(12):
        for residual_q in range(11):
            indices = [
                ell
                for ell in range(1, 11)
                if residual_p <= ell + 1 and residual_q <= ell
            ]
            for ell in indices:
                for other in indices:
                    products.add(
                        (
                            ell + 1 - residual_p,
                            ell - residual_q,
                            other + 1 - residual_p,
                            other - residual_q,
                        )
                    )
    for ell in range(1, 11):
        products.add((1, 0, ell + 1, ell))
        for other in range(1, 11):
            products.add((ell + 1, ell, other + 1, other))

    maximum_degree = 0
    coefficient_count = 0
    for indices in sorted(products):
        observed = core.radial_product_polynomial(*indices)
        expected = direct_radial_product(arb_type, *indices)
        require(len(observed) == len(expected), f"radial product length mismatch for {indices}")
        maximum_degree = max(maximum_degree, len(observed) - 1)
        coefficient_count += len(observed)
        for observed_value, expected_value in zip(observed, expected):
            require(
                arb_intervals_overlap(observed_value, expected_value),
                f"radial product coefficient mismatch for {indices}",
            )
    require(maximum_degree <= 21, "radial product degree exceeds the moment budget")

    candidate = wrapper.load_decimal_candidate(
        root / "computations/weighted_chaos_safe_candidate.json"
    )
    rho = core.exact_decimal(str(candidate["rho"]))
    parameters = {
        "alpha": core.exact_decimal(str(candidate["alpha"])),
        "eta": core.exact_decimal(str(candidate["eta"])),
        "zeta1": core.exact_decimal(str(candidate["zeta"][0])),
        "zeta2": core.exact_decimal(str(candidate["zeta"][1])),
        "delta1": core.exact_decimal(str(candidate["delta"][0])),
        "delta2": core.exact_decimal(str(candidate["delta"][1])),
    }
    denominator, numerator, shifted = core.weight_polynomials(rho, parameters)
    for point_text in ("0", "1/3", "1", "7"):
        point = arb_type(point_text)
        direct_weight = (
            parameters["alpha"]
            + parameters["eta"] * point
            + parameters["zeta1"] * point / (point + parameters["delta1"])
            + parameters["zeta2"] * point / (point + parameters["delta2"])
        )
        denominator_value = core.evaluate_polynomial(denominator, point)
        numerator_value = core.evaluate_polynomial(numerator, point)
        shifted_value = core.evaluate_polynomial(shifted, point)
        require(
            arb_intervals_overlap(numerator_value, denominator_value * direct_weight),
            f"weight polynomial identity failed at {point_text}",
        )
        require(
            arb_intervals_overlap(
                shifted_value,
                numerator_value + 2 * rho * denominator_value,
            ),
            f"shifted-weight polynomial identity failed at {point_text}",
        )

    weight_roots = core.certified_positive_roots(numerator, 180)
    shifted_roots = core.certified_positive_roots(shifted, 180)
    require(len(weight_roots) == 3, "inverse weight must have three certified poles")
    require(len(shifted_roots) == 3, "inverse shifted weight must have three certified poles")
    return {
        "radial_product_case_count": len(products),
        "radial_coefficient_count": coefficient_count,
        "maximum_radial_degree": maximum_degree,
        "weight_pole_count": len(weight_roots),
        "shifted_weight_pole_count": len(shifted_roots),
    }


def audit_dual_certificate_code(root: Path, dual: Any, arb_type: Any) -> dict[str, int]:
    panels = dual.panel_fractions()
    require(len(panels) == 600, "DUAL Simpson panel count is not 600")
    expected_left = Fraction(0)
    widths: dict[Fraction, int] = {}
    for left, right in panels:
        require(left == expected_left and right > left, "DUAL Simpson panels have a gap or overlap")
        width = right - left
        widths[width] = widths.get(width, 0) + 1
        expected_left = right
    require(expected_left == Fraction(8), "DUAL Simpson panels do not cover [0,8]")
    require(
        widths
        == {
            Fraction(1, 200): 200,
            Fraction(1, 100): 200,
            Fraction(1, 40): 200,
        },
        "DUAL Simpson panel widths are incorrect",
    )

    bernstein_bound = dual.bernstein_upper(
        [arb_type(1), arb_type(2), arb_type(-3), arb_type(1)],
        arb_type(1),
    )
    require(
        bernstein_bound.lower() >= arb_type("5/3").upper(),
        "power-to-Bernstein conversion failed its exact polynomial test",
    )

    synthetic_moments = [arb_type(2**order) for order in range(9)]
    synthetic_x_magnitudes = [arb_type(1) for _ in range(9)]
    taylor = dual.taylor_interval_upper(
        arb_type(0),
        arb_type("1/100"),
        synthetic_moments,
        synthetic_x_magnitudes,
        8,
    )
    for index in range(101):
        point = arb_type(f"{index}/10000")
        exact_value = (-2 * point).exp() + point * (-4 * point).exp()
        require(
            exact_value.upper() < taylor["interval_upper"].upper(),
            "Taylor--Bernstein synthetic-function bound failed",
        )

    q_values, weights, _ = dual.load_candidate(
        root / "computations/weighted_chaos_dual_mixture_candidate.json"
    )
    scalar = dual.scalar_integrands(arb_type("1/3"), arb_type(2), q_values, weights, 8)
    series = dual.series_integrands(arb_type("1/3"), arb_type(2), q_values, weights, 8)
    for scalar_value, series_value in zip(scalar, series):
        require(
            arb_intervals_overlap(scalar_value, series_value.coeffs()[0]),
            "DUAL scalar and series integrands disagree at order zero",
        )

    tail = dual.global_tail_upper(arb_type(100000), q_values, weights)
    require(tail["squared_upper"].upper() < arb_type("0.238636"), "DUAL analytic tail smoke test failed")
    return {
        "simpson_panel_count": len(panels),
        "synthetic_taylor_sample_count": 101,
        "atom_count": len(q_values),
        "series_moment_count": len(series),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    sys.path.insert(0, str(root / "computations"))

    flint = importlib.import_module("flint")
    core = importlib.import_module("certify_ten_chaos_arb")
    wrapper = importlib.import_module("certify_weighted_chaos_candidate_arb")
    dual = importlib.import_module("certify_weighted_chaos_dual_mixture_arb")
    require(getattr(flint, "__version__", None) == "0.8.0", "code audit requires python-flint 0.8.0")
    flint.ctx.dps = 180

    report = {
        "schema_version": 1,
        "status": "passed",
        "python_flint_version": flint.__version__,
        "source_checks": audit_python_sources(root),
        "lower_bound_checks": audit_lower_bound_code(root, core, wrapper, flint.arb),
        "dual_certificate_checks": audit_dual_certificate_code(root, dual, flint.arb),
    }
    if arguments.report is not None:
        output = arguments.report if arguments.report.is_absolute() else root / arguments.report
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

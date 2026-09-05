#!/usr/bin/env python3
"""Internal Arb core for the ten-chaos complex lower-bound certificate.

Every displayed decimal parameter is converted to an exact rational before
being embedded in an Arb ball.  The verifier certifies all residual
complements by interval LDL decomposition, certifies the main Woodbury
condition, and proves the installed lower-ratio threshold.  This module has no
standalone candidate; use lower_bound.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
import json
import math
from pathlib import Path


import flint
from flint import arb, arb_mat, arb_poly, ctx


EXPECTED_FLINT_VERSION = "0.8.0"
RUN_ID: str | None = None
CERTIFIED_THRESHOLD_TEXT: str | None = None
RHO_TEXT: str | None = None
BETA_TEXTS: list[str] | None = None
WEIGHT_TEXTS: dict[str, str] | None = None


def installed_candidate() -> tuple[str, str, str, list[str], dict[str, str]]:
    if (
        not isinstance(RUN_ID, str)
        or not isinstance(CERTIFIED_THRESHOLD_TEXT, str)
        or not isinstance(RHO_TEXT, str)
        or not isinstance(BETA_TEXTS, list)
        or not isinstance(WEIGHT_TEXTS, dict)
    ):
        raise RuntimeError(
            "no LB candidate is installed; run "
            "lower_bound.py with an exact candidate JSON"
        )
    if getattr(flint, "__version__", None) != EXPECTED_FLINT_VERSION:
        raise RuntimeError(
            f"LB-CERT requires python-flint {EXPECTED_FLINT_VERSION}, "
            f"found {getattr(flint, '__version__', 'unknown')}"
        )
    return (
        RUN_ID,
        CERTIFIED_THRESHOLD_TEXT,
        RHO_TEXT,
        BETA_TEXTS,
        WEIGHT_TEXTS,
    )


def emit_status(path: Path, **record: object) -> None:
    if not isinstance(RUN_ID, str):
        raise RuntimeError("LB-CERT run ID was not installed")
    payload = dict(record)
    payload["run_id"] = RUN_ID
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def exact_decimal(text: str) -> arb:
    value = Fraction(text)
    return arb(f"{value.numerator}/{value.denominator}")


def exact_integer(value: int) -> arb:
    return arb(value)


def ball_record(value: arb) -> dict[str, str]:
    return {
        "ball": value.str(40),
        "lower": value.lower().str(40),
        "upper": value.upper().str(40),
    }


def add_polynomials(first: list[arb], second: list[arb]) -> list[arb]:
    size = max(len(first), len(second))
    result = [arb(0) for _ in range(size)]
    for index, value in enumerate(first):
        result[index] += value
    for index, value in enumerate(second):
        result[index] += value
    return result


def multiply_polynomials(first: list[arb], second: list[arb]) -> list[arb]:
    result = [arb(0) for _ in range(len(first) + len(second) - 1)]
    for first_index, first_value in enumerate(first):
        for second_index, second_value in enumerate(second):
            result[first_index + second_index] += first_value * second_value
    return result


def scale_polynomial(values: list[arb], scale: arb) -> list[arb]:
    return [scale * value for value in values]


def evaluate_polynomial(values: list[arb], point: arb) -> arb:
    result = arb(0)
    for value in reversed(values):
        result = result * point + value
    return result


def derivative_polynomial(values: list[arb]) -> list[arb]:
    return [exact_integer(index) * values[index] for index in range(1, len(values))]


def weight_polynomials(
    rho: arb,
    parameters: dict[str, arb],
) -> tuple[list[arb], list[arb], list[arb]]:
    alpha = parameters["alpha"]
    eta = parameters["eta"]
    zeta1 = parameters["zeta1"]
    zeta2 = parameters["zeta2"]
    delta1 = parameters["delta1"]
    delta2 = parameters["delta2"]
    first = [delta1, arb(1)]
    second = [delta2, arb(1)]
    denominator = multiply_polynomials(first, second)
    numerator = multiply_polynomials([alpha, eta], denominator)
    numerator = add_polynomials(
        numerator,
        scale_polynomial([arb(0), delta2, arb(1)], zeta1),
    )
    numerator = add_polynomials(
        numerator,
        scale_polynomial([arb(0), delta1, arb(1)], zeta2),
    )
    shifted = add_polynomials(
        numerator,
        scale_polynomial(denominator, 2 * rho),
    )
    return denominator, numerator, shifted


def certified_positive_roots(
    denominator: list[arb],
    precision_digits: int,
) -> list[arb]:
    tolerance_digits = max(40, precision_digits - 20)
    roots = arb_poly(denominator).complex_roots(
        tol=arb(f"1e-{tolerance_digits}"),
        maxprec=max(1000, precision_digits * 8),
    )
    expected_count = len(denominator) - 1
    if len(roots) != expected_count:
        raise ArithmeticError(
            f"expected {expected_count} roots, received {len(roots)}"
        )
    lambdas: list[arb] = []
    for root in roots:
        if not root.imag.contains(0):
            raise ArithmeticError(f"root is not certified real: {root}")
        value = -root.real
        if not value.lower() > 0:
            raise ArithmeticError(f"pole is not certified positive: {value}")
        lambdas.append(value)
    lambdas.sort(key=lambda value: float(value.mid()))
    for first, second in zip(lambdas, lambdas[1:]):
        if not first.upper() < second.lower():
            raise ArithmeticError(
                f"real pole intervals are not disjoint: {first}, {second}"
            )
    return lambdas


def rational_moments(
    numerator: list[arb],
    denominator: list[arb],
    maximum_degree: int,
    precision_digits: int,
) -> tuple[list[arb], list[arb], list[arb]]:
    lambdas = certified_positive_roots(denominator, precision_digits)
    derivative = derivative_polynomial(denominator)
    residues = [
        evaluate_polynomial(numerator, -value)
        / evaluate_polynomial(derivative, -value)
        for value in lambdas
    ]
    moments = [arb(0) for _ in range(maximum_degree + 1)]
    for value, residue in zip(lambdas, residues):
        current = value.exp() * value.expint(1)
        moments[0] += residue * current
        for degree in range(maximum_degree):
            current = exact_integer(math.factorial(degree)) - value * current
            moments[degree + 1] += residue * current
    return moments, lambdas, residues


def radial_product_polynomial(
    first_p: int,
    first_q: int,
    second_p: int,
    second_q: int,
) -> list[arb]:
    first_charge = first_p - first_q
    second_charge = second_p - second_q
    if first_charge != second_charge:
        raise ValueError("radial products require equal angular charge")
    maximum_degree = (
        first_p + first_q + second_p + second_q
    ) // 2
    result = [arb(0) for _ in range(maximum_degree + 1)]
    normalization = exact_integer(
        math.factorial(first_p)
        * math.factorial(first_q)
        * math.factorial(second_p)
        * math.factorial(second_q)
    ).sqrt()
    for first_j in range(min(first_p, first_q) + 1):
        first_coefficient = (
            (-1) ** first_j
            * math.factorial(first_j)
            * math.comb(first_p, first_j)
            * math.comb(first_q, first_j)
        )
        first_power = first_p + first_q - 2 * first_j
        for second_j in range(min(second_p, second_q) + 1):
            second_coefficient = (
                (-1) ** second_j
                * math.factorial(second_j)
                * math.comb(second_p, second_j)
                * math.comb(second_q, second_j)
            )
            second_power = second_p + second_q - 2 * second_j
            total_power = first_power + second_power
            if total_power % 2:
                raise ArithmeticError("unexpected odd radial product power")
            result[total_power // 2] += (
                exact_integer(first_coefficient * second_coefficient)
                / normalization
            )
    return result


def integrate_polynomial(
    polynomial: list[arb],
    moments: list[arb],
) -> arb:
    result = arb(0)
    for degree, coefficient in enumerate(polynomial):
        result += coefficient * moments[degree]
    return result


def ldl_pivots(entries: list[list[arb]]) -> list[arb]:
    size = len(entries)
    lower = [[arb(0) for _ in range(size)] for _ in range(size)]
    diagonal: list[arb] = []
    for row in range(size):
        lower[row][row] = arb(1)
        pivot = entries[row][row]
        for index in range(row):
            pivot -= lower[row][index] ** 2 * diagonal[index]
        if not pivot.lower() > 0:
            raise ArithmeticError(
                f"LDL pivot is not certified positive at row {row}: {pivot}"
            )
        diagonal.append(pivot)
        for next_row in range(row + 1, size):
            numerator = entries[next_row][row]
            for index in range(row):
                numerator -= (
                    lower[next_row][index]
                    * lower[row][index]
                    * diagonal[index]
                )
            lower[next_row][row] = numerator / pivot
    return diagonal


def as_arb_matrix(entries: list[list[arb]]) -> arb_mat:
    return arb_mat(entries)


def certify(
    precision_digits: int,
    status_path: Path,
) -> dict[str, object]:
    run_id, threshold_text, rho_text, beta_texts, weight_texts = (
        installed_candidate()
    )
    ctx.dps = precision_digits
    ctx.threads = 1
    rho = exact_decimal(rho_text)
    beta = [exact_decimal(value) for value in beta_texts]
    parameters = {
        key: exact_decimal(value) for key, value in weight_texts.items()
    }
    weight_denominator, weight_numerator, shifted_numerator = (
        weight_polynomials(rho, parameters)
    )
    inverse_weight, weight_poles, _ = rational_moments(
        weight_denominator,
        weight_numerator,
        21,
        precision_digits,
    )
    inverse_shifted, shifted_poles, _ = rational_moments(
        weight_denominator,
        shifted_numerator,
        21,
        precision_digits,
    )
    emit_status(
        status_path,
        state="running",
        phase="moments",
        completed=1,
        total=4,
    )

    alpha = parameters["alpha"]
    eta = parameters["eta"]
    zeta1 = parameters["zeta1"]
    zeta2 = parameters["zeta2"]
    delta1 = parameters["delta1"]
    delta2 = parameters["delta2"]
    mu_weight = (
        alpha
        + eta
        + zeta1 * (1 - delta1 * delta1.exp() * delta1.expint(1))
        + zeta2 * (1 - delta2 * delta2.exp() * delta2.expint(1))
    )

    block_records: list[dict[str, object]] = []
    worst_pivot_lower: arb | None = None
    worst_pivot_block: tuple[int, int] | None = None
    for residual_p in range(12):
        for residual_q in range(11):
            indices = [
                ell
                for ell in range(1, 11)
                if residual_p <= ell + 1 and residual_q <= ell
            ]
            if not indices:
                continue
            matrix = [
                [arb(0) for _ in indices]
                for _ in indices
            ]
            for row, ell in enumerate(indices):
                for column, other in enumerate(indices):
                    polynomial = radial_product_polynomial(
                        ell + 1 - residual_p,
                        ell - residual_q,
                        other + 1 - residual_p,
                        other - residual_q,
                    )
                    matrix[row][column] = (
                        (beta[ell - 1] * beta[other - 1]).sqrt()
                        * integrate_polynomial(polynomial, inverse_weight)
                    )
            complement = [
                [
                    (arb(1) if row == column else arb(0))
                    - matrix[row][column]
                    for column in range(len(indices))
                ]
                for row in range(len(indices))
            ]
            pivots = ldl_pivots(complement)
            minimum_lower = min(pivot.lower() for pivot in pivots)
            if worst_pivot_lower is None or minimum_lower < worst_pivot_lower:
                worst_pivot_lower = minimum_lower
                worst_pivot_block = (residual_p, residual_q)
            block_records.append(
                {
                    "residual_bidegree": [residual_p, residual_q],
                    "size": len(indices),
                    "pivot_lower_bounds": [
                        pivot.lower().str(30) for pivot in pivots
                    ],
                    "minimum_pivot_lower_bound": minimum_lower.str(30),
                }
            )
    emit_status(
        status_path,
        state="running",
        phase="residual-blocks",
        completed=2,
        total=4,
        worst_pivot_block=list(worst_pivot_block or ()),
        worst_pivot_lower=(
            worst_pivot_lower.str(25)
            if worst_pivot_lower is not None
            else None
        ),
    )

    size = len(beta)
    r_value = inverse_shifted[1]
    s_vector = [arb(0) for _ in range(size)]
    gram = [[arb(0) for _ in range(size)] for _ in range(size)]
    for ell in range(1, size + 1):
        polynomial = radial_product_polynomial(1, 0, ell + 1, ell)
        s_vector[ell - 1] = integrate_polynomial(
            polynomial,
            inverse_shifted,
        )
        for other in range(1, size + 1):
            polynomial = radial_product_polynomial(
                ell + 1,
                ell,
                other + 1,
                other,
            )
            gram[ell - 1][other - 1] = integrate_polynomial(
                polynomial,
                inverse_shifted,
            )
    main_entries = [
        [
            gram[row][column]
            + (
                1 / beta[row]
                if row == column
                else arb(0)
            )
            for column in range(size)
        ]
        for row in range(size)
    ]
    main_pivots = ldl_pivots(main_entries)
    main_matrix = as_arb_matrix(main_entries)
    s_matrix = arb_mat([[value] for value in s_vector])
    solved = main_matrix.solve(s_matrix)
    inner = arb(0)
    for index, value in enumerate(s_vector):
        inner += value * solved[index, 0]
    xi = r_value - inner
    woodbury_margin = 1 - xi
    determinant = main_matrix.det()
    cancellation_free = determinant * woodbury_margin
    if not woodbury_margin.lower() > 0:
        raise ArithmeticError(
            f"Woodbury margin is not certified positive: {woodbury_margin}"
        )
    if not cancellation_free.lower() > 0:
        raise ArithmeticError(
            "cancellation-free Woodbury quantity is not positive: "
            f"{cancellation_free}"
        )
    emit_status(
        status_path,
        state="running",
        phase="woodbury",
        completed=3,
        total=4,
        woodbury_margin_lower=woodbury_margin.lower().str(25),
    )

    scalar_bound = rho + mu_weight
    ratio = (1 - rho) / scalar_bound
    threshold = exact_decimal(threshold_text)
    ratio_margin = ratio - threshold
    if not ratio_margin.lower() > 0:
        raise ArithmeticError(
            f"ratio margin is not certified positive: {ratio_margin}"
        )

    return {
        "run_id": run_id,
        "status": "passed",
        "role": "directed Arb verification of the ten-chaos unrestricted complex lower certificate",
        "proof_status": "directed ball-arithmetic certificate",
        "library": {
            "python_flint_version": getattr(flint, "__version__", "unknown"),
            "precision_digits": precision_digits,
        },
        "parameters": {
            "rho": rho_text,
            "beta": beta_texts,
            "weight": weight_texts,
            "certified_threshold": threshold_text,
            "interpretation": "exact terminating decimals",
        },
        "weight_poles": [ball_record(value) for value in weight_poles],
        "shifted_poles": [ball_record(value) for value in shifted_poles],
        "mu_weight": ball_record(mu_weight),
        "scalar_norm_bound": ball_record(scalar_bound),
        "lower_ratio": ball_record(ratio),
        "ratio_margin_over_certified_threshold": ball_record(ratio_margin),
        "worst_residual_pivot": {
            "block": list(worst_pivot_block or ()),
            "lower_bound": (
                worst_pivot_lower.str(40)
                if worst_pivot_lower is not None
                else None
            ),
        },
        "residual_blocks": block_records,
        "main_minimum_pivot_lower_bound": min(
            pivot.lower() for pivot in main_pivots
        ).str(40),
        "xi": ball_record(xi),
        "woodbury_margin": ball_record(woodbury_margin),
        "cancellation_free_quantity": ball_record(cancellation_free),
    }


def main() -> None:
    raise SystemExit(
        "This is an internal library. Run "
        "lower_bound.py with an exact candidate JSON."
    )


if __name__ == "__main__":
    main()

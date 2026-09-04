#!/usr/bin/env python3
"""Directed Arb audits for the bounded scalar-radial dual mixture.

The atomic parameters are interpreted as exact terminating decimals.  At
each requested squared radius, composite Simpson quadrature is evaluated in
Arb arithmetic.  Its error is enclosed using interval fourth derivatives
computed by truncated Arb power series on every panel; the Gaussian tail is
bounded analytically.  Point mode certifies individual radii.  Continuum mode
uses Taylor--Bernstein interval bounds followed by an analytic global tail.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import time
import traceback
from typing import Callable


import flint
from flint import arb, arb_series, ctx


DEFAULT_RUN_ID = "R20260808-CGC-SCALAR-DUAL-MIXTURE-ARB-POINT-001"
EXPECTED_FLINT_VERSION = "0.8.0"


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


def exact_decimal(text: str) -> arb:
    value = Fraction(text)
    return arb(f"{value.numerator}/{value.denominator}")


def exact_fraction(value: Fraction) -> arb:
    return arb(f"{value.numerator}/{value.denominator}")


def ball_record(value: arb, digits: int = 40) -> dict[str, str]:
    return {
        "ball": value.str(digits),
        "lower": value.lower().str(digits),
        "upper": value.upper().str(digits),
        "radius": value.rad().str(digits),
    }


def parse_decimal_list(text: str) -> list[str]:
    values = [value.strip() for value in text.split(",") if value.strip()]
    if not values:
        raise argparse.ArgumentTypeError("expected comma-separated decimals")
    for value in values:
        Fraction(value)
    return values


def load_candidate(path: Path) -> tuple[list[arb], list[arb], dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"), parse_float=str)
    records = payload.get("atoms")
    if not isinstance(records, list) or not records:
        raise ValueError("candidate has no atoms list")
    q_fractions = [Fraction(str(record["q"])) for record in records]
    weight_fractions = [Fraction(str(record["weight"])) for record in records]
    if not all(Fraction(0) < value < Fraction(1) for value in q_fractions):
        raise ValueError("every atom must satisfy 0 < q < 1")
    if not all(value > 0 for value in weight_fractions):
        raise ValueError("every atom weight must be positive")
    if sum(weight_fractions, Fraction(0)) != Fraction(1):
        raise ValueError("atom weights do not sum exactly to one")
    q_values = [exact_fraction(value) for value in q_fractions]
    weights = [exact_fraction(value) for value in weight_fractions]
    return q_values, weights, payload


def panel_fractions() -> list[tuple[Fraction, Fraction]]:
    specifications = (
        (Fraction(0), Fraction(1, 4), Fraction(1, 200)),
        (Fraction(1, 4), Fraction(1), Fraction(1, 200)),
        (Fraction(1), Fraction(3), Fraction(1, 100)),
        (Fraction(3), Fraction(8), Fraction(1, 40)),
    )
    panels: list[tuple[Fraction, Fraction]] = []
    for start, stop, step in specifications:
        left = start
        while left < stop:
            right = min(stop, left + step)
            panels.append((left, right))
            left = right
    return panels


def scalar_integrands(
    v_value: arb,
    squared_radius: arb,
    q_values: list[arb],
    weights: list[arb],
    maximum_moment: int,
) -> list[arb]:
    gaussian_parameter = (-(v_value * v_value)).exp()
    totals = [arb(0) for _ in range(maximum_moment + 1)]
    for q_value, weight in zip(q_values, weights):
        denominator = arb(1) - q_value * gaussian_parameter
        local_rate = q_value * gaussian_parameter / denominator
        base = (
            weight
            * gaussian_parameter
            / (denominator * denominator)
            * (-(squared_radius * local_rate)).exp()
        )
        power = arb(1)
        for moment in range(maximum_moment + 1):
            totals[moment] += base * power
            power *= local_rate
    return totals


def series_integrands(
    v_interval: arb,
    squared_radius: arb,
    q_values: list[arb],
    weights: list[arb],
    maximum_moment: int,
) -> list[arb_series]:
    variable = arb_series([v_interval, arb(1)], prec=5)
    gaussian_parameter = (-(variable * variable)).exp()
    totals = [arb_series([arb(0)], prec=5) for _ in range(maximum_moment + 1)]
    for q_value, weight in zip(q_values, weights):
        denominator = arb(1) - q_value * gaussian_parameter
        local_rate = q_value * gaussian_parameter / denominator
        base = (
            weight
            * gaussian_parameter
            / (denominator * denominator)
            * (-(squared_radius * local_rate)).exp()
        )
        power = arb_series([arb(1)], prec=5)
        for moment in range(maximum_moment + 1):
            totals[moment] += base * power
            power *= local_rate
    return totals


def certified_b_moments(
    squared_radius: arb,
    q_values: list[arb],
    weights: list[arb],
    maximum_moment: int,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[arb], list[arb], list[arb]]:
    panels = panel_fractions()
    approximations = [arb(0) for _ in range(maximum_moment + 1)]
    error_bounds = [arb(0) for _ in range(maximum_moment + 1)]
    for panel_index, (left_fraction, right_fraction) in enumerate(panels, start=1):
        midpoint_fraction = (left_fraction + right_fraction) / 2
        width_fraction = right_fraction - left_fraction
        left = exact_fraction(left_fraction)
        midpoint = exact_fraction(midpoint_fraction)
        right = exact_fraction(right_fraction)
        width = exact_fraction(width_fraction)
        left_values = scalar_integrands(
            left,
            squared_radius,
            q_values,
            weights,
            maximum_moment,
        )
        midpoint_values = scalar_integrands(
            midpoint,
            squared_radius,
            q_values,
            weights,
            maximum_moment,
        )
        right_values = scalar_integrands(
            right,
            squared_radius,
            q_values,
            weights,
            maximum_moment,
        )
        v_interval = arb(
            exact_fraction(midpoint_fraction),
            exact_fraction(width_fraction / 2),
        )
        derivative_series = series_integrands(
            v_interval,
            squared_radius,
            q_values,
            weights,
            maximum_moment,
        )
        width_fifth_over_120 = width**5 / 120
        for moment in range(maximum_moment + 1):
            approximations[moment] += width / 6 * (
                left_values[moment]
                + 4 * midpoint_values[moment]
                + right_values[moment]
            )
            coefficient_four = derivative_series[moment].coeffs()[4]
            error_bounds[moment] += (
                width_fifth_over_120 * abs(coefficient_four).upper()
            )
        if progress is not None:
            progress(panel_index, len(panels))

    cutoff = arb(8)
    cutoff_parameter = (-(cutoff * cutoff)).exp()
    q_maximum = max(value.upper() for value in q_values)
    denominator_minimum = arb(1) - q_maximum * cutoff_parameter
    normalization = arb(2) / arb.pi().sqrt()
    results = []
    tail_bounds = []
    for moment in range(maximum_moment + 1):
        exponent = moment + 1
        gaussian_tail = cutoff_parameter**exponent / (
            2 * exponent * cutoff
        )
        tail = (
            q_maximum**moment
            * gaussian_tail
            / denominator_minimum ** (moment + 2)
        )
        tail_bounds.append(normalization * tail)
        total_error = error_bounds[moment] + tail
        enclosed = approximations[moment] + arb(0, total_error)
        results.append(normalization * enclosed)
        error_bounds[moment] = normalization * error_bounds[moment]
    return results, error_bounds, tail_bounds


def x_value(
    squared_radius: arb,
    q_values: list[arb],
    weights: list[arb],
) -> arb:
    result = arb(0)
    for q_value, weight in zip(q_values, weights):
        rate = q_value / (arb(1) - q_value)
        result -= weight * rate * (-(squared_radius * rate)).exp()
    return result


def x_derivative_magnitudes(
    squared_radius: arb,
    q_values: list[arb],
    weights: list[arb],
    maximum_order: int,
) -> list[arb]:
    totals = [arb(0) for _ in range(maximum_order + 1)]
    for q_value, weight in zip(q_values, weights):
        rate = q_value / (arb(1) - q_value)
        base = weight * rate * (-(squared_radius * rate)).exp()
        power = arb(1)
        for order in range(maximum_order + 1):
            totals[order] += base * power
            power *= rate
    return totals


def bernstein_upper(power_coefficients: list[arb], width: arb) -> arb:
    degree = len(power_coefficients) - 1
    scaled = [
        coefficient * width**order
        for order, coefficient in enumerate(power_coefficients)
    ]
    bernstein = []
    for index in range(degree + 1):
        value = arb(0)
        for order in range(index + 1):
            value += (
                exact_fraction(
                    Fraction(math.comb(index, order), math.comb(degree, order))
                )
                * scaled[order]
            )
        bernstein.append(value)
    return max(value.upper() for value in bernstein)


def taylor_interval_upper(
    left: arb,
    right: arb,
    b_moments: list[arb],
    x_magnitudes: list[arb],
    derivative_order: int,
) -> dict[str, arb]:
    if len(b_moments) <= derivative_order or len(x_magnitudes) <= derivative_order:
        raise ValueError("Taylor certificate lacks derivative moments")
    x_coefficients = [
        ((-1) ** (order + 1)) * x_magnitudes[order] / math.factorial(order)
        for order in range(derivative_order)
    ]
    f_coefficients = [
        ((-1) ** order) * b_moments[order] / math.factorial(order)
        for order in range(derivative_order)
    ]
    x_series = arb_series(x_coefficients, prec=derivative_order)
    f_series = arb_series(f_coefficients, prec=derivative_order)
    radius_series = arb_series([left, arb(1)], prec=derivative_order)
    g_series = x_series * x_series + radius_series * f_series * f_series
    coefficients = g_series.coeffs()
    while len(coefficients) < derivative_order:
        coefficients.append(arb(0))
    width = right - left
    polynomial_upper = bernstein_upper(coefficients, width)

    x_square_derivative_bound = arb(0)
    for order in range(derivative_order + 1):
        x_square_derivative_bound += (
            math.comb(derivative_order, order)
            * x_magnitudes[order]
            * x_magnitudes[derivative_order - order]
        )

    def f_square_derivative_bound(order: int) -> arb:
        total = arb(0)
        for index in range(order + 1):
            total += (
                math.comb(order, index)
                * b_moments[index]
                * b_moments[order - index]
            )
        return total

    f_square_top = f_square_derivative_bound(derivative_order)
    f_square_previous = f_square_derivative_bound(derivative_order - 1)
    derivative_bound = (
        x_square_derivative_bound
        + right * f_square_top
        + derivative_order * f_square_previous
    )
    remainder_bound = (
        derivative_bound
        * width**derivative_order
        / math.factorial(derivative_order)
    )
    return {
        "polynomial_upper": polynomial_upper,
        "derivative_bound": derivative_bound.upper(),
        "remainder_bound": remainder_bound.upper(),
        "interval_upper": polynomial_upper + remainder_bound.upper(),
    }


def fractional_power(value: arb, exponent: Fraction) -> arb:
    return (exact_fraction(exponent) * value.log()).exp()


def global_tail_upper(
    start: arb,
    q_values: list[arb],
    weights: list[arb],
) -> dict[str, arb]:
    exponent = Fraction(3, 4)
    mixture_factor = arb(0)
    for q_value, weight in zip(q_values, weights):
        mixture_factor += (
            weight
            * fractional_power(q_value, -exponent)
            * fractional_power(arb(1) - q_value, exponent - 2)
        )
    constant = (
        fractional_power(exact_fraction(exponent) / arb(1).exp(), exponent)
        / fractional_power(arb(1) - exact_fraction(exponent), Fraction(1, 2))
        * mixture_factor
    )
    y_upper = constant * fractional_power(
        start,
        Fraction(1, 2) - exponent,
    )
    x_upper = -x_value(start, q_values, weights)
    return {
        "x_upper": x_upper.upper(),
        "y_upper": y_upper.upper(),
        "squared_upper": (x_upper * x_upper + y_upper * y_upper).upper(),
        "mixture_factor": mixture_factor,
        "constant": constant,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-id",
        default=os.environ.get("CGC_DUAL_MIXTURE_ARB_RUN_ID", DEFAULT_RUN_ID),
    )
    parser.add_argument(
        "--candidate-json",
        type=Path,
        default=Path(
            os.environ.get(
                "CGC_DUAL_MIXTURE_ARB_CANDIDATE",
                "weighted_chaos_dual_mixture_candidate.json",
            )
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("points", "continuum"),
        default=os.environ.get("CGC_DUAL_MIXTURE_ARB_MODE", "points"),
    )
    parser.add_argument(
        "--points",
        type=parse_decimal_list,
        default=parse_decimal_list(
            os.environ.get(
                "CGC_DUAL_MIXTURE_ARB_POINTS",
                "0,0.00931008757053271,0.7303788021041172",
            )
        ),
    )
    parser.add_argument(
        "--maximum-moment",
        type=int,
        default=int(os.environ.get("CGC_DUAL_MIXTURE_ARB_MAX_MOMENT", "2")),
    )
    parser.add_argument(
        "--precision-digits",
        type=int,
        default=int(os.environ.get("CGC_DUAL_MIXTURE_ARB_PRECISION", "100")),
    )
    parser.add_argument(
        "--threshold",
        default=os.environ.get("CGC_DUAL_MIXTURE_ARB_THRESHOLD", ""),
    )
    parser.add_argument(
        "--derivative-order",
        type=int,
        default=int(os.environ.get("CGC_DUAL_MIXTURE_ARB_DERIVATIVE_ORDER", "8")),
    )
    parser.add_argument(
        "--cover-end",
        default=os.environ.get("CGC_DUAL_MIXTURE_ARB_COVER_END", "2"),
    )
    parser.add_argument(
        "--initial-step",
        default=os.environ.get("CGC_DUAL_MIXTURE_ARB_INITIAL_STEP", "0.01"),
    )
    parser.add_argument(
        "--maximum-relative-step",
        default=os.environ.get("CGC_DUAL_MIXTURE_ARB_MAX_RELATIVE_STEP", "0.2"),
    )
    parser.add_argument(
        "--minimum-step",
        default=os.environ.get("CGC_DUAL_MIXTURE_ARB_MINIMUM_STEP", "1e-10"),
    )
    parser.add_argument(
        "--maximum-intervals",
        type=int,
        default=int(os.environ.get("CGC_DUAL_MIXTURE_ARB_MAX_INTERVALS", "10000")),
    )
    parser.add_argument(
        "--require-global-tail",
        action="store_true",
        default=os.environ.get("CGC_DUAL_MIXTURE_ARB_REQUIRE_GLOBAL", "0") == "1",
    )
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--startup-delay", type=float, default=0.0)
    arguments = parser.parse_args()
    if arguments.maximum_moment < 0:
        raise ValueError("maximum moment must be nonnegative")
    if getattr(flint, "__version__", None) != EXPECTED_FLINT_VERSION:
        raise RuntimeError(
            f"DUAL-CERT requires python-flint {EXPECTED_FLINT_VERSION}, "
            f"found {getattr(flint, '__version__', 'unknown')}"
        )
    if (
        arguments.mode == "continuum"
        and arguments.maximum_moment != arguments.derivative_order
    ):
        raise ValueError(
            "--maximum-moment and --derivative-order must agree in continuum mode"
        )

    arguments.status.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    emit_status(
        arguments.status,
        arguments.run_id,
        state="running",
        phase="startup",
        completed=0,
        total=(len(arguments.points) + 1 if arguments.mode == "points" else "unknown"),
        elapsed_seconds=0.0,
        estimated_remaining_seconds="unknown",
    )
    if arguments.startup_delay:
        time.sleep(arguments.startup_delay)

    try:
        ctx.dps = arguments.precision_digits
        q_values, weights, candidate_payload = load_candidate(
            arguments.candidate_json
        )
        threshold_text = arguments.threshold or str(
            candidate_payload["target_squared_ceiling"]
        )
        threshold = exact_decimal(threshold_text)
        point_records: list[dict[str, object]] = []
        continuum_record: dict[str, object] | None = None

        if arguments.mode == "points":
            for point_index, point_text in enumerate(arguments.points, start=1):
                squared_radius = exact_decimal(point_text)
                last_heartbeat = [0.0]

                def report_panels(completed: int, total: int) -> None:
                    now = time.monotonic()
                    if now - last_heartbeat[0] < 5.0 and completed < total:
                        return
                    last_heartbeat[0] = now
                    emit_status(
                        arguments.status,
                        arguments.run_id,
                        state="running",
                        phase="simpson-panels",
                        completed=completed,
                        total=total,
                        point=point_text,
                        point_index=point_index,
                        point_total=len(arguments.points),
                        elapsed_seconds=now - started,
                        estimated_remaining_seconds="unknown",
                    )

                moments, simpson_errors, tail_bounds = certified_b_moments(
                    squared_radius,
                    q_values,
                    weights,
                    arguments.maximum_moment,
                    progress=report_panels,
                )
                local_x = x_value(squared_radius, q_values, weights)
                squared_value = local_x * local_x + squared_radius * moments[0] ** 2
                margin = threshold - squared_value
                point_records.append(
                    {
                        "x": point_text,
                        "x_function": ball_record(local_x),
                        "b_moments": [ball_record(value) for value in moments],
                        "simpson_error_bounds": [
                            value.upper().str(30) for value in simpson_errors
                        ],
                        "gaussian_tail_bounds": [
                            value.upper().str(30) for value in tail_bounds
                        ],
                        "squared_value": ball_record(squared_value),
                        "margin_below_target": ball_record(margin),
                        "margin_is_positive": bool(margin.lower() > 0),
                    }
                )
                emit_status(
                    arguments.status,
                    arguments.run_id,
                    state="running",
                    phase="point-certified",
                    completed=point_index,
                    total=len(arguments.points) + 1,
                    point=point_text,
                    margin_lower=margin.lower().str(20),
                    elapsed_seconds=time.monotonic() - started,
                    estimated_remaining_seconds="unknown",
                )
            role = "directed pointwise Arb audit of the bounded scalar-radial dual"
            proof_status = (
                "directed pointwise ball arithmetic only; the continuum "
                "supremum is not certified by this run"
            )
            terminal_total = len(arguments.points) + 1
        else:
            if arguments.derivative_order < 2:
                raise ValueError("continuum mode needs derivative order at least two")
            cover_end = Fraction(arguments.cover_end)
            step = Fraction(arguments.initial_step)
            maximum_relative_step = Fraction(arguments.maximum_relative_step)
            minimum_step = Fraction(arguments.minimum_step)
            if (
                cover_end <= 0
                or step <= 0
                or maximum_relative_step <= 0
                or minimum_step <= 0
            ):
                raise ValueError("continuum cover parameters must be positive")
            left_fraction = Fraction(0)
            intervals: list[dict[str, object]] = []
            maximum_interval_upper: arb | None = None
            worst_margin_lower: arb | None = None

            while left_fraction < cover_end:
                if len(intervals) >= arguments.maximum_intervals:
                    raise RuntimeError("continuum cover exceeded the interval limit")
                left = exact_fraction(left_fraction)
                interval_index = len(intervals) + 1
                last_heartbeat = [0.0]

                def report_cover_panels(completed: int, total: int) -> None:
                    now = time.monotonic()
                    if now - last_heartbeat[0] < 5.0 and completed < total:
                        return
                    last_heartbeat[0] = now
                    emit_status(
                        arguments.status,
                        arguments.run_id,
                        state="running",
                        phase="continuum-simpson-panels",
                        completed=completed,
                        total=total,
                        interval_index=interval_index,
                        interval_left=str(left_fraction),
                        cover_end=str(cover_end),
                        elapsed_seconds=now - started,
                        estimated_remaining_seconds="unknown",
                    )

                moments, simpson_errors, tail_bounds = certified_b_moments(
                    left,
                    q_values,
                    weights,
                    arguments.derivative_order,
                    progress=report_cover_panels,
                )
                x_magnitudes = x_derivative_magnitudes(
                    left,
                    q_values,
                    weights,
                    arguments.derivative_order,
                )
                relative_cap = maximum_relative_step * (1 + left_fraction)
                trial_step = min(step, relative_cap, cover_end - left_fraction)
                while True:
                    if trial_step < minimum_step:
                        raise ArithmeticError(
                            f"Taylor cover failed above {left_fraction} at minimum step"
                        )
                    right_fraction = left_fraction + trial_step
                    certificate = taylor_interval_upper(
                        left,
                        exact_fraction(right_fraction),
                        moments,
                        x_magnitudes,
                        arguments.derivative_order,
                    )
                    margin = threshold - certificate["interval_upper"]
                    if margin.lower() > 0:
                        break
                    trial_step /= 2

                interval_record = {
                    "left": str(left_fraction),
                    "right": str(right_fraction),
                    "width": str(trial_step),
                    "interval_upper": certificate["interval_upper"].upper().str(30),
                    "margin_lower": margin.lower().str(30),
                    "polynomial_upper": certificate["polynomial_upper"].str(30),
                    "remainder_upper": certificate["remainder_bound"].str(30),
                    "derivative_bound": certificate["derivative_bound"].str(30),
                    "largest_simpson_error": max(
                        value.upper() for value in simpson_errors
                    ).str(20),
                    "largest_gaussian_tail": max(
                        value.upper() for value in tail_bounds
                    ).str(20),
                }
                intervals.append(interval_record)
                interval_upper = certificate["interval_upper"].upper()
                margin_lower = margin.lower()
                maximum_interval_upper = (
                    interval_upper
                    if maximum_interval_upper is None
                    else max(maximum_interval_upper, interval_upper)
                )
                worst_margin_lower = (
                    margin_lower
                    if worst_margin_lower is None
                    else min(worst_margin_lower, margin_lower)
                )
                left_fraction = right_fraction
                step = trial_step * Fraction(3, 2)
                emit_status(
                    arguments.status,
                    arguments.run_id,
                    state="running",
                    phase="continuum-interval-certified",
                    completed=len(intervals),
                    total="unknown",
                    interval_right=str(right_fraction),
                    cover_end=str(cover_end),
                    margin_lower=margin_lower.str(20),
                    elapsed_seconds=time.monotonic() - started,
                    estimated_remaining_seconds="unknown",
                )

            tail = global_tail_upper(
                exact_fraction(cover_end),
                q_values,
                weights,
            )
            tail_margin = threshold - tail["squared_upper"]
            tail_certified = bool(tail_margin.lower() > 0)
            if arguments.require_global_tail and not tail_certified:
                raise ArithmeticError("analytic global tail bound exceeds the target")
            continuum_record = {
                "cover_start": "0",
                "cover_end": str(cover_end),
                "interval_count": len(intervals),
                "derivative_order": arguments.derivative_order,
                "maximum_interval_upper": (
                    maximum_interval_upper.str(30)
                    if maximum_interval_upper is not None
                    else None
                ),
                "worst_interval_margin_lower": (
                    worst_margin_lower.str(30)
                    if worst_margin_lower is not None
                    else None
                ),
                "intervals": intervals,
                "global_tail": {
                    "required": arguments.require_global_tail,
                    "certified": tail_certified,
                    "squared_upper": tail["squared_upper"].str(30),
                    "margin_lower": tail_margin.lower().str(30),
                    "x_upper": tail["x_upper"].str(30),
                    "y_upper": tail["y_upper"].str(30),
                    "inequality_exponent": "3/4",
                },
            }
            global_complete = arguments.require_global_tail and tail_certified
            role = "directed Arb Taylor cover of the bounded scalar-radial dual"
            proof_status = (
                "directed continuum ceiling certificate"
                if global_complete
                else "directed finite-interval cover only; global tail not required"
            )
            terminal_total = len(intervals) + 1

        source_path = Path(__file__).resolve()
        computed_moment_order = (
            arguments.derivative_order
            if arguments.mode == "continuum"
            else arguments.maximum_moment
        )
        result = {
            "run_id": arguments.run_id,
            "status": "completed",
            "role": role,
            "proof_status": proof_status,
            "configuration": {
                "candidate_json": bundle_relative_path(arguments.candidate_json),
                "candidate_sha256": hashlib.sha256(
                    arguments.candidate_json.read_bytes()
                ).hexdigest(),
                "mode": arguments.mode,
                "points": arguments.points if arguments.mode == "points" else None,
                "maximum_moment": arguments.maximum_moment,
                "computed_moment_order": computed_moment_order,
                "derivative_order": arguments.derivative_order,
                "cover_end": arguments.cover_end,
                "initial_step": arguments.initial_step,
                "maximum_relative_step": arguments.maximum_relative_step,
                "minimum_step": arguments.minimum_step,
                "require_global_tail": arguments.require_global_tail,
                "precision_digits": arguments.precision_digits,
                "panel_count": len(panel_fractions()),
                "integration_cutoff": "8",
            },
            "library": {
                "python_flint_version": flint.__version__,
            },
            "target_squared_ceiling": threshold_text,
            "atom_count": len(q_values),
            "weight_sum": ball_record(sum(weights, arb(0))),
            "points": point_records,
            "continuum": continuum_record,
            "source": {
                "path": bundle_relative_path(source_path),
                "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            },
            "elapsed_seconds": time.monotonic() - started,
        }
        arguments.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        emit_status(
            arguments.status,
            arguments.run_id,
            state="complete",
            phase="done",
            completed=terminal_total,
            total=terminal_total,
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
            phase="exception",
            completed=0,
            total=(len(arguments.points) + 1 if arguments.mode == "points" else "unknown"),
            elapsed_seconds=time.monotonic() - started,
            estimated_remaining_seconds=0.0,
            error=repr(error),
            traceback=traceback.format_exc(),
        )
        raise


if __name__ == "__main__":
    main()

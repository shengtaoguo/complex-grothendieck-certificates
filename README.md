# Complex Grothendieck Certificates

This repository contains the computations accompanying
*[An Improved Lower Bound for the Complex Grothendieck Constant](https://arxiv.org/abs/2609.07000)*.
They verify two results:

- **Lower-bound computation:** the matrix and Schur inequalities giving
  $K_G^{\mathbb C}>1.35584631827168$.
- **Pointwise-bound computation:** the uniform inequality giving
  $\mathcal K_*<1.35584697425050$ for the paper's restricted optimization
  problem. This is **not** an upper bound for the complex Grothendieck constant.

## Run

Use Python 3.11 and run from the repository root:

```sh
python3 -m pip install -r verification/requirements.txt
python3 verification/verify.py
```

The command runs both computations using Arb interval arithmetic,
checks the paper's strict bounds, and tests that malformed or inconsistent
results are rejected. Success prints `VERIFIED:`; failures exit with a
nonzero status. Results and progress logs are written to a new directory
under `replay-results/`.

The computations run one at a time, with one numerical thread,
using `python-flint==0.8.0`. The full Windows test run took about 27 minutes;
the lower-bound computation alone takes seconds. No TeX, optimizer, or
saved search results are needed.

To run just one computation, use `--only lb` or `--only dual`.

## Files

```text
verification/
├── verify.py                 # runs both computations and their checks
├── requirements.txt          # Python dependency
├── check_results.py          # strict bounds and consistency checks
├── test_checks.py            # rejection of damaged results
├── test_formulas.py          # supplementary formula checks
├── computations/
│   ├── lower_bound.py        # lower-bound computation
│   ├── hermite.py            # Hermite integrals, matrices, and LDL decomposition
│   └── dual_bound.py         # pointwise-bound computation
└── data/
    ├── lower_bound.json      # exact multiplier and weight parameters
    └── dual_pair.json        # exact 180-pair dual input
```

## Paper Claims and Scripts

| Paper result | Computation | What is checked |
| --- | --- | --- |
| Proposition 4.1; Appendix A.1 | [Lower-bound computation](verification/computations/lower_bound.py), [Hermite calculations](verification/computations/hermite.py) | All 132 residual blocks and 570 positive pivots, the Schur condition, and the lower-bound ratio. |
| Proposition 5.5; Appendix A.2 | [Pointwise-bound computation](verification/computations/dual_bound.py) | Exact normalization of the 180 pairs, a gap-free cover of $[0,10^5]$, and the analytic tail bound. |
| Both computations | [Formula checks](verification/test_formulas.py) | Radial Hermite coefficients, rational-weight identities, quadrature panels, and Taylor--Bernstein formulas. |

Input decimals are treated as exact rational numbers. Arb then encloses the
integrals and matrix calculations with rigorous error bounds, using
180-digit precision for the lower-bound computation and 80-digit precision
for the pointwise-bound computation.

The operator reduction and coefficient-matching argument are proved in the
paper. These scripts verify their numerical hypotheses; they do not prove
the analytic reductions or determine the exact Grothendieck constant.

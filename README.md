# Certificates for a complex Grothendieck lower bound - DRAFT

**DRAFT RELEASE - NOT FOR SUBMISSION.** The arXiv link below is a placeholder.

**CERTIFICATE REPLAY PENDING.** The two result files and `SHA256SUMS` will be
added after the external replay. Verification is expected to fail until then.

This repository contains the certificates for the following two results:

> The complex Grothendieck constant satisfies
> $K_G^{\mathbb C}>1.35584631827168$.

> The restricted optimization value in Theorem 5.2 of the paper satisfies
> $\mathcal K_*<1.35584697425050$.

The paper reduces the first result to finitely many matrix inequalities and
one scalar Schur inequality. LB-CERT checks those inequalities by directed
ball arithmetic. The paper reduces the second result to a uniform bound for
a pair of radial functions. DUAL-CERT checks that bound on the whole
half-line.

Manuscript: <https://arxiv.org/abs/XXXX.XXXXXv1>

No manuscript source or PDF is included in this certificate.

## Verification

Once the frozen result files are present, Python 3.10 or newer is sufficient;
no external package is needed. Verification is single-process and does not
require TeX or paper-build software. Run

```sh
python3 verification/verify.py
```

from the repository root. A successful run prints a line beginning
`VERIFIED:` and exits with status `0`.

For an optional integrity check of the complete repository snapshot, run

```sh
python3 verification/verify_checksums.py
```

## Files

```text
complex-grothendieck-certificates/
├── artifacts/
│   ├── lb/result.json                    # frozen LB-CERT result
│   ├── dual/result.json                  # frozen DUAL-CERT result
│   └── external-run-environment.json     # accepted external replay
├── computations/
│   ├── weighted_chaos_safe_candidate.json
│   ├── certify_weighted_chaos_candidate_arb.py
│   ├── certify_ten_chaos_arb.py
│   ├── weighted_chaos_dual_mixture_candidate.json
│   └── certify_weighted_chaos_dual_mixture_arb.py
├── claims/release-spec.json              # thresholds and source hashes
├── verification/
│   ├── verify.py                         # command-line entry point
│   ├── verify_results.py                 # certificate checker
│   ├── verify_checksums.py               # optional integrity checker
│   ├── audit_code.py                     # formula-level checks
│   ├── code-audit.json
│   ├── frozen-result-check.json
│   ├── path-portability.json
│   └── verification-report.json          # accepted verification result
├── repository-manifest.json              # claim and artifact metadata
└── SHA256SUMS                            # repository file hashes
```

Only `verification/verify.py` is intended to be run directly. The verification
flow is

```text
verify.py -> verify_results.py -> {LB-CERT result, DUAL-CERT result}
                                -> exact inputs and source hashes
```

## Certificate identity

### LB-CERT

The exact input is `computations/weighted_chaos_safe_candidate.json`. It fixes
$\rho$, ten coefficients $\beta_1,\ldots,\beta_{10}$, and a two-pole radial
weight $W$. The checker verifies

$$
I-\mathcal M^{p,q}(W)\succ0
\quad\text{for all 132 residual blocks},
$$

by checking 570 interval $LDL^*$ pivots. It also verifies

$$
1-S>1.8374949151\times10^{-9},
\qquad
\mu_W<0.716627735168304,
$$

and

$$
\frac{1-\rho}{\rho+\mu_W}>1.35584631827168.
$$

The smallest certified pivot lower bound is greater than
$1.2259567912\times10^{-5}$. This is a pivot bound in the fixed elimination
order, not a lower bound for the smallest eigenvalue.

In `artifacts/lb/result.json`, the field `xi` is the paper's scalar $S$, and
`woodbury_margin` is $1-S$. The analytic argument in the paper turns these
checks into the lower bound for $K_G^{\mathbb C}$.

### DUAL-CERT

The exact input is
`computations/weighted_chaos_dual_mixture_candidate.json`. It records 180
pairs $(c_j,q_j)$ with

$$
c_j>0,
\qquad
0<q_j<1,
\qquad
\sum_{j=1}^{180}c_j=1.
$$

These pairs define the radial functions $X$ and $Y$ in Proposition 5.5. The
checker verifies

$$
\sup_{s\ge0}\bigl(X(s)^2+Y(s)^2\bigr)
<1.35584697425050.
$$

It covers $0\le s\le10^5$ by 98 adjacent intervals, using validated Simpson
quadrature and Taylor--Bernstein bounds. The remaining half-line is handled by
the analytic tail estimate recorded in the paper.

This certificate bounds $\mathcal K_*$, not the unrestricted complex
Grothendieck constant.

## Certificate format

Each certificate has an exact input file and a frozen result file. Decimal
parameters in the input files are interpreted as rational numbers before ball
arithmetic begins.

The principal files are:

| File | Contents |
| --- | --- |
| `computations/weighted_chaos_safe_candidate.json` | Exact LB-CERT parameters. |
| `artifacts/lb/result.json` | Root balls, residual pivots, Schur data, and the final ratio. |
| `computations/weighted_chaos_dual_mixture_candidate.json` | The 180 exact atoms used by DUAL-CERT. |
| `artifacts/dual/result.json` | The 98 interval bounds and the global tail bound. |
| `claims/release-spec.json` | Required thresholds and SHA-256 hashes of the inputs and producers. |
| `repository-manifest.json` | The two claims, their certificate files, and the verification commands. |

The result files store outward-rounded Arb balls as decimal strings. The
checker reads their lower and upper endpoints and verifies the strict
inequalities needed by the paper. It also checks that the source hashes inside
the result files match `claims/release-spec.json`.

## Verification checks

The checker verifies the computational layer of the argument. It uses the
analytic theorems in the paper as mathematical inputs rather than attempting
to prove them. It checks:

1. the repository schema, source hashes, and certificate thresholds;
2. all 132 LB-CERT residual blocks and all 570 pivots;
3. the Schur margin, radial-weight integral, and lower-bound ratio;
4. exact normalization of the 180 DUAL-CERT atoms;
5. all 98 adjacent continuum intervals and their strict margins;
6. the analytic tail bound;
7. the accepted Python and python-flint versions and the external result
   hashes;
8. the complete repository inventory and `SHA256SUMS`.

The repository verifies the finished certificates. It does not rerun the
numerical searches that found the two inputs, and it does not require an
optimizer or the discarded search data.

## Full recomputation

Full recomputation requires Python 3.11 and `python-flint==0.8.0`. Install the
pinned version with

```sh
python3 -m pip install -r environment/requirements.txt
```

Run the formula checks:

```sh
python3 verification/audit_code.py --root . --report verification/code-audit.json
```

Run LB-CERT:

```sh
python3 computations/certify_weighted_chaos_candidate_arb.py \
  --run-id CGC-SUBMISSION-LB-REPRO \
  --parameters-json computations/weighted_chaos_safe_candidate.json \
  --threshold 1.35584631827168 \
  --precision-digits 180 \
  --status artifacts/lb/status.jsonl \
  --output artifacts/lb/result.json
```

Run DUAL-CERT:

```sh
python3 computations/certify_weighted_chaos_dual_mixture_arb.py \
  --run-id CGC-SUBMISSION-DUAL-REPRO \
  --candidate-json computations/weighted_chaos_dual_mixture_candidate.json \
  --mode continuum --maximum-moment 8 --precision-digits 80 \
  --threshold 1.35584697425050 --derivative-order 8 \
  --cover-end 100000 --initial-step 0.01 \
  --maximum-relative-step 0.2 --minimum-step 1e-10 \
  --maximum-intervals 10000 --require-global-tail \
  --status artifacts/dual/status.jsonl \
  --output artifacts/dual/result.json
```

These commands overwrite the result paths, so use a disposable copy. Check the
new results with

```sh
python3 verification/verify_results.py --root . --only all
```

The accepted replay used Python 3.11.9 with python-flint 0.8.0 on Windows.

## Provenance

This draft was prepared from commit
`9436cab3ae87b0584e4729842bcb4908d9a01ae5`. The exact source hashes are in
`claims/release-spec.json`. Finalization keeps the result JSON files unchanged
and records their hashes in `verification/path-portability.json`.

A final release must use the versioned arXiv URL and pass

```sh
python3 verification/verify_results.py \
  --root . --only all --audit-bundle --require-final
```

## License

See `LICENSE-NOTICE.md`.

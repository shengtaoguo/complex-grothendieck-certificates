# Certificates for a lower bound on the complex Grothendieck constant - DRAFT

**DRAFT RELEASE - NOT FOR SUBMISSION.** The arXiv link below is a placeholder.

**CERTIFICATE REPLAY PENDING.** The two result files and `SHA256SUMS` will be
added after the external replay. Verification is expected to fail until then.

This repository accompanies *An Improved Lower Bound for the Complex
Grothendieck Constant*. It contains the files for two computer-assisted
statements:

- **LB-CERT:** `K_G^C > 1.35584631827168`.
- **DUAL-CERT:** `K_* < 1.35584697425050`, where `K_*` is the restricted
  optimization value in Theorem 5.2.

The analytic arguments are in the paper. The programs here check the numerical
parts of Propositions 4.1 and 5.5.

Manuscript: <https://arxiv.org/abs/XXXX.XXXXXv1>

No manuscript source or PDF is included in this certificate.

## Verification

Once the frozen result files are present, Python 3.10 or newer is sufficient;
no external package is needed. Run

```sh
python3 verification/verify.py
```

from the repository root. A successful run prints a line beginning `VERIFIED:`
and exits with status `0`. This checks the two result files, their inputs and
source hashes, the recorded external replay, and the repository inventory. It
does not rerun Arb.

To check only the file hashes, run

```sh
python3 verification/verify_checksums.py
```

## Files

- `artifacts/lb/result.json` is the frozen LB-CERT result.
- `artifacts/dual/result.json` is the frozen DUAL-CERT result.
- `computations/` contains the exact inputs and Arb programs.
- `verification/verify.py` is the main verification command.
- `verification/verify_results.py` checks the mathematical result files.
- `verification/audit_code.py` checks the formulas used by the Arb programs.
- `verification/verification-report.json` records the accepted replay.
- `repository-manifest.json` identifies the claims and their files.
- `SHA256SUMS` covers the complete repository snapshot.

## LB-CERT

The exact multiplier and radial-weight parameters are in
`computations/weighted_chaos_safe_candidate.json`. LB-CERT checks 132 residual
blocks through 570 interval `LDL^*` pivots, proves the Schur condition `S < 1`,
and checks the final ratio.

In the result file, `xi` is the paper's scalar `S`, and `woodbury_margin` is
`1-S`. Together with the analytic argument in the paper, the certificate gives

```text
K_G^C > 1.35584631827168.
```

## DUAL-CERT

The exact 180-atom input is in
`computations/weighted_chaos_dual_mixture_candidate.json`. DUAL-CERT checks its
normalization, a gap-free 98-interval cover of `[0, 100000]`, the validated
quadrature and Taylor bounds, and the analytic tail. Together with the dual
argument in the paper, it gives

```text
K_* < 1.35584697425050.
```

This is a bound for the restricted optimization problem in Theorem 5.2, not an
upper bound for the complex Grothendieck constant.

## Recomputing the certificates

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
`9a1c6263c69787343f27a623f0496dd2c9c91d42`. The exact source hashes are in
`claims/release-spec.json`. Finalization keeps the result JSON files unchanged
and records their hashes in `verification/path-portability.json`.

A final release must use the versioned arXiv URL and pass

```sh
python3 verification/verify_results.py \
  --root . --only all --audit-bundle --require-final
```

The numerical searches used to find the two candidates are not part of the
certificate.

## License

See `LICENSE-NOTICE.md`.

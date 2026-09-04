# Certificates for an improved lower bound for the complex Grothendieck constant - DRAFT

**DRAFT RELEASE - NOT FOR SUBMISSION.** The arXiv URL below is a placeholder. Replace it with the exact versioned arXiv URL and rebuild this archive before submission.

**CERTIFICATE REPLAY PENDING.** This prepared repository does not yet contain the two frozen result files or `SHA256SUMS`. The primary verification command is expected to fail until the external replay and finalization complete.

This repository contains the directed certificates for the two
computer-assisted propositions in *An Improved Lower Bound for the Complex
Grothendieck Constant*:

> **LB-CERT:** `K_G^C > 1.35584631827168`.

> **DUAL-CERT:** `K_* < 1.35584697425050`, where `K_*` is the restricted
> parameter-optimization value defined in Theorem 5.2 of the paper.

The temporary manuscript reference is <https://arxiv.org/abs/XXXX.XXXXXv1>.
No manuscript source or PDF is included in this certificate.

The paper proves the analytic reductions. This repository verifies the exact
finite inputs and all directed numerical inequalities used by Propositions 4.1
and 5.5. It does not prove the analytic reductions, an exact value of
`K_G^C`, or an unrestricted upper bound.

## Verification

Frozen-certificate verification uses only Python 3.10 or newer and the standard
library. From the repository root, run

```sh
python3 verification/verify.py
```

A successful run prints a line beginning `VERIFIED:` and exits with status
`0`. It verifies both certificate result files, their exact inputs and source
hashes, the claim--artifact map, the complete repository inventory, and the
accepted external-replay record. It does not rerun Arb.

For the optional integrity-only check, run

```sh
python3 verification/verify_checksums.py
```

## Files

```text
.
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
├── claims/release-spec.json              # exact thresholds and source hashes
├── verification/
│   ├── verify.py                         # primary command-line entry point
│   ├── verify_results.py                 # frozen certificate checker
│   ├── verify_checksums.py               # optional integrity checker
│   ├── audit_code.py                     # independent formula-level audit
│   ├── code-audit.json
│   ├── frozen-result-check.json
│   ├── path-portability.json
│   └── verification-report.json
├── repository-manifest.json              # claim and artifact metadata
└── SHA256SUMS                            # complete file-hash inventory
```

The verification flow is

```text
verification/verify.py
        |
        v
verification/verify_results.py
        |--------------------------|
        v                          v
artifacts/lb/result.json    artifacts/dual/result.json
        |                          |
        v                          v
exact LB inputs             exact 180-atom input
```

## How the certificates enter the paper

The two artifacts have different logical roles:

1. **LB-CERT** checks all finite hypotheses of Proposition 4.1: 132 residual
   block complements through 570 interval `LDL^*` pivots, the Schur condition
   `S < 1`, the radial-weight mean, and the strict final ratio. The paper's
   analytic results then imply `K_G^C > 1.35584631827168`.
2. **DUAL-CERT** checks the exact normalization of 180 positive atoms, a
   gap-free 98-interval cover of `[0, 100000]`, validated quadrature and
   Taylor--Bernstein bounds, and the analytic tail. The paper's dual lemma then
   implies only `K_* < 1.35584697425050`.

In LB-CERT, the result field `xi` is the paper's Schur scalar `S`, and
`woodbury_margin` is `1-S`. DUAL-CERT is not an upper bound for the
unrestricted complex Grothendieck constant.

## Full recomputation

Full recomputation requires Python 3.11 and `python-flint==0.8.0`; the accepted
replay used Python 3.11.9 on Windows. Install the pinned dependency with

```sh
python3 -m pip install -r environment/requirements.txt
```

Then use a disposable copy of the repository because these commands replace
the frozen result files. Run LB-CERT with

```sh
python3 computations/certify_weighted_chaos_candidate_arb.py \
  --run-id CGC-SUBMISSION-LB-REPRO \
  --parameters-json computations/weighted_chaos_safe_candidate.json \
  --threshold 1.35584631827168 \
  --precision-digits 180 \
  --status artifacts/lb/status.jsonl \
  --output artifacts/lb/result.json
```

Run DUAL-CERT from the repository root:

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

Run the independent formula-level audit with

```sh
python3 verification/audit_code.py --root . --report verification/code-audit.json
```

The accepted replay used one CPU worker. LB-CERT completed in seconds and
DUAL-CERT in about eleven minutes on the recorded machine. After recomputation,
check the newly produced mathematical results with

```sh
python3 verification/verify_results.py --root . --only all
```

The primary `verification/verify.py` command is intentionally stricter: it
audits the frozen repository inventory and accepted external-result hashes, so
it should be run on an unchanged repository snapshot.

## What the checker verifies

The frozen-result checker verifies:

1. the release schema, exact thresholds, source digests, and claim--artifact
   links;
2. every LB-CERT residual block and pivot, the Schur enclosure, the weight
   integral, and the strict lower-bound ratio;
3. the exact DUAL-CERT atom normalization, all 98 adjacent cover intervals,
   their strict margins, and the global tail;
4. the accepted Python/python-flint environment and byte-identical external
   and bundled result hashes;
5. the exact repository inventory, path portability, and `SHA256SUMS` entries.

The checker verifies the finished certificates. It does not rerun the
floating-point searches that found either candidate.

## Release status and provenance

The computation sources were staged from Git commit `1919a63486143f26be51a992071d3d8298571022`. Every material
input and verifier is independently identified by SHA-256 in
`claims/release-spec.json`. The producers emit repository-relative provenance
paths, and finalization never edits a result JSON.

The lower-level release gate is

```sh
python3 verification/verify_results.py \
  --root . --only all --audit-bundle --require-final
```

It deliberately exits nonzero for a draft repository. The primary
`verification/verify.py` command still verifies the mathematical certificate
content of a correctly marked draft and reports its release status explicitly.
Process logs, status streams, orchestration scripts, caches, and manuscript
files are excluded from the repository.

## License and redistribution

See `LICENSE-NOTICE.md`. No redistribution license beyond applicable law is
asserted by this release.

#!/usr/bin/env python3
"""Verify the frozen LB-CERT and DUAL-CERT results without recomputing Arb data."""

from __future__ import annotations

import argparse
from decimal import Decimal, getcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any


getcontext().prec = 100
BALL_RE = re.compile(
    r"^\[?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?:\s*\+/-\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))?\s*\]?$"
)
ARXIV_URL_RE = re.compile(
    r"^https://arxiv\.org/abs/[0-9]{4}\.[0-9]{4,5}v[1-9][0-9]*$"
)
ARXIV_PLACEHOLDER_URL = "https://arxiv.org/abs/XXXX.XXXXXv1"
DRAFT_NOTICE = "DRAFT RELEASE - NOT FOR SUBMISSION"
DRAFT_BLOCKING_ISSUES = [
    "Release status is draft.",
    "The manuscript URL is an arXiv placeholder.",
]
PORTABLE_PATH_SCOPE = (
    "producer results were repository-relative and remained byte-identical to the Windows-recorded hashes"
)
EXPECTED_PORTABLE_PATHS = {
    "LB-CERT": {
        "source.parameters_path": "computations/weighted_chaos_safe_candidate.json",
        "source.path": "computations/certify_weighted_chaos_candidate_arb.py",
        "source.verifier_path": "computations/certify_ten_chaos_arb.py",
    },
    "DUAL-CERT": {
        "configuration.candidate_json": "computations/weighted_chaos_dual_mixture_candidate.json",
        "source.path": "computations/certify_weighted_chaos_dual_mixture_arb.py",
    },
}
CHECKSUM_RE = re.compile(r"^([0-9a-f]{64})  (.+)$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
REQUIRED_BUNDLE_FILES = {
    ".gitattributes",
    ".gitignore",
    "README.md",
    "SHA256SUMS",
    "repository-manifest.json",
    "claims/release-spec.json",
    "verification/verification-report.json",
    "verification/verify.py",
    "verification/verify_checksums.py",
    "verification/verify_results.py",
}
FORBIDDEN_NAMES = {
    ".DS_Store",
    ".env",
    ".git",
    ".hg",
    ".svn",
    "__MACOSX",
    "__pycache__",
    "node_modules",
    "venv",
}
PORTABILITY_PATTERNS = (
    ("file URI", re.compile(rb"file:(?:/{2,3}|\\{2})", re.IGNORECASE)),
    (
        "machine-local POSIX path",
        re.compile(
            rb"(?<![A-Za-z0-9._:/-])/(?:Users|home|Volumes|private/tmp|"
            rb"var/folders|tmp)/[A-Za-z0-9._~+@%=:,/-]+"
        ),
    ),
    (
        "machine-local Windows path",
        re.compile(rb"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\{2}[A-Za-z0-9._-]+[\\/])"),
    ),
    (
        "home-directory expansion",
        re.compile(
            rb"(?<![A-Za-z0-9_])(?:~[\\/]|\$(?:HOME|USERPROFILE)[\\/]|"
            rb"\$\{(?:HOME|USERPROFILE)\}[\\/]|%(?:USERPROFILE|HOMEPATH)%[\\/])"
        ),
    ),
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("possible API credential", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("possible GitHub credential", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
)


class VerificationError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VerificationError(f"{path} must contain a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(value: object, *, allow_dot: bool = False) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in ("\x00", "\n", "\r", "\\", ":"))
    ):
        return None
    if value == ".":
        return value if allow_dot else None
    if value.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", value):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def require_bundle_path(
    root: Path,
    value: object,
    field: str,
    *,
    directory: bool = False,
    must_exist: bool = True,
) -> str:
    normalized = safe_relative_path(value, allow_dot=directory)
    require(normalized is not None, f"{field} is not a safe repository-relative path")
    assert normalized is not None
    target = root if normalized == "." else root / normalized
    try:
        target.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise VerificationError(f"{field} escapes the bundle root") from exc
    if must_exist:
        if directory:
            require(target.is_dir() and not target.is_symlink(), f"{field} is not a bundled directory")
        else:
            require(target.is_file() and not target.is_symlink(), f"{field} is not a bundled file")
    return normalized


def inspect_bundle_tree(root: Path) -> tuple[str, ...]:
    require(root.is_dir() and not root.is_symlink(), "bundle root is not a regular directory")
    files: list[str] = []
    casefolded: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        require(safe_relative_path(relative) is not None, f"unsafe bundle member path: {relative}")
        folded = relative.casefold()
        require(
            folded not in casefolded or casefolded[folded] == relative,
            f"case-insensitive path collision: {relative} and {casefolded.get(folded)}",
        )
        casefolded[folded] = relative
        require(
            not any(part in FORBIDDEN_NAMES or part.startswith("._") for part in PurePosixPath(relative).parts),
            f"forbidden metadata or cache path: {relative}",
        )
        require(not path.is_symlink(), f"symlink is not allowed in the certificate: {relative}")
        if path.is_file():
            files.append(relative)
        else:
            require(path.is_dir(), f"special filesystem entry is not allowed: {relative}")
    return tuple(files)


def scan_bundle_contents(root: Path, files: tuple[str, ...]) -> None:
    for relative in files:
        data = (root / relative).read_bytes()
        sample = data[:8192]
        if b"\x00" in sample:
            continue
        controls = sum(byte < 32 and byte not in {9, 10, 12, 13} for byte in sample)
        if sample and controls / len(sample) >= 0.02:
            continue
        for description, pattern in PORTABILITY_PATTERNS:
            require(pattern.search(data) is None, f"{description} found in {relative}")


def require_string(value: object, field: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{field} must be a nonempty string")
    assert isinstance(value, str)
    return value


def require_string_list(value: object, field: str) -> list[str]:
    require(
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item for item in value)
        and len(value) == len(set(value)),
        f"{field} must contain unique nonempty strings",
    )
    assert isinstance(value, list)
    return value


def require_command(value: object, field: str) -> list[str]:
    require(
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item for item in value),
        f"{field} must be a nonempty string array",
    )
    assert isinstance(value, list)
    return value


def validate_manifest_command(
    root: Path,
    record: object,
    field: str,
    *,
    outputs_may_be_missing: bool,
) -> dict[str, Any]:
    require(isinstance(record, dict), f"{field} must be an object")
    assert isinstance(record, dict)
    require_bundle_path(root, record.get("cwd"), f"{field}.cwd", directory=True)
    require_command(record.get("command"), f"{field}.command")
    for index, value in enumerate(require_string_list(record.get("inputs"), f"{field}.inputs")):
        require_bundle_path(root, value, f"{field}.inputs[{index}]")
    if "outputs" in record:
        for index, value in enumerate(require_string_list(record.get("outputs"), f"{field}.outputs")):
            require_bundle_path(
                root,
                value,
                f"{field}.outputs[{index}]",
                must_exist=not outputs_may_be_missing,
            )
    if "expected_exit" in record:
        require(
            isinstance(record.get("expected_exit"), int)
            and not isinstance(record.get("expected_exit"), bool),
            f"{field}.expected_exit must be an integer",
        )
    return record


def validate_certificate_manifest(
    root: Path,
    files: tuple[str, ...],
    spec: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = load_json(root / "repository-manifest.json")
    require(manifest.get("schema_version") == 1, "manifest schema_version must equal 1")
    require(manifest.get("bundle_type") == "standalone-certificate", "manifest bundle_type is incorrect")
    require(
        manifest.get("repository_type") == "certificate-only-companion",
        "manifest repository_type is incorrect",
    )
    require(manifest.get("release_id") == spec.get("release_id"), "manifest and release-spec IDs differ")
    release_status = require_string(manifest.get("release_status"), "manifest.release_status")
    require(release_status in {"draft", "final"}, "manifest release_status must be draft or final")
    require(manifest.get("version") == "4", "manifest version must equal 4")
    require_string(manifest.get("title"), "manifest.title")
    require(
        isinstance(manifest.get("computation_source_commit"), str)
        and re.fullmatch(r"[0-9a-f]{40}", manifest["computation_source_commit"]) is not None,
        "manifest computation_source_commit is not a Git object ID",
    )
    require(manifest.get("material_sources_match_commit") is True, "material source gate was not recorded")
    require(
        manifest.get("certificate_status") == "passed",
        "manifest certificate_status is not passed",
    )
    require("paper" not in manifest, "a standalone certificate must not contain a bundled-paper manifest")

    manuscript = manifest.get("manuscript")
    require(isinstance(manuscript, dict), "manifest.manuscript must be an object")
    assert isinstance(manuscript, dict)
    require(manuscript.get("included") is False, "the manuscript must be declared external")
    require(
        manuscript.get("title")
        == "An Improved Lower Bound for the Complex Grothendieck Constant",
        "manifest manuscript title is incorrect",
    )
    manuscript_url = require_string(manuscript.get("url"), "manifest.manuscript.url")
    if release_status == "draft":
        require(
            manuscript_url == ARXIV_PLACEHOLDER_URL,
            "draft manuscript URL is not the explicit arXiv placeholder",
        )
    else:
        require(
            ARXIV_URL_RE.fullmatch(manuscript_url) is not None,
            "final manuscript URL is not a versioned arXiv abstract URL",
        )
    readme = (root / "README.md").read_text(encoding="utf-8")
    require(f"<{manuscript_url}>" in readme, "README does not contain the manifest manuscript URL")
    require(
        "No manuscript source or PDF is included in this certificate." in readme,
        "README does not disclose the certificate-only scope",
    )
    if release_status == "draft":
        require(DRAFT_NOTICE in readme, "draft README does not display the required submission warning")
    else:
        require(DRAFT_NOTICE not in readme, "final README contains a draft submission warning")
        require(ARXIV_PLACEHOLDER_URL not in readme, "final README contains the arXiv placeholder")

    inventory = require_string_list(manifest.get("file_inventory"), "manifest.file_inventory")
    require(inventory == sorted(inventory), "manifest file_inventory is not sorted")
    require(set(inventory) == set(files), "manifest file_inventory differs from the exact archive tree")
    require(REQUIRED_BUNDLE_FILES <= set(files), "the certificate is missing a required root or verification file")
    require(
        not any(relative == "paper" or relative.startswith("paper/") for relative in files),
        "the standalone certificate contains a manuscript file",
    )

    claims_value = manifest.get("claims")
    require(isinstance(claims_value, list) and bool(claims_value), "manifest claims must be nonempty")
    claims: dict[str, dict[str, Any]] = {}
    assert isinstance(claims_value, list)
    for index, claim in enumerate(claims_value):
        require(isinstance(claim, dict), f"manifest.claims[{index}] must be an object")
        assert isinstance(claim, dict)
        claim_id = require_string(claim.get("id"), f"manifest.claims[{index}].id")
        require(IDENTIFIER_RE.fullmatch(claim_id) is not None, f"invalid claim ID: {claim_id}")
        require(claim_id not in claims, f"duplicate claim ID: {claim_id}")
        require_string(claim.get("manuscript_location"), f"manifest.claims[{index}].manuscript_location")
        require_string(claim.get("statement"), f"manifest.claims[{index}].statement")
        require_string(claim.get("logical_role"), f"manifest.claims[{index}].logical_role")
        require_string_list(claim.get("artifacts"), f"manifest.claims[{index}].artifacts")
        claims[claim_id] = claim
    require(set(claims) == {"CLAIM-LB", "CLAIM-RESTRICTED-DUAL"}, "manifest must contain exactly the two certificate claims")
    require(
        claims["CLAIM-LB"]["statement"] == spec["claims"]["LB-CERT"]["statement"],
        "main lower-bound claim differs from the release specification",
    )
    require(
        claims["CLAIM-RESTRICTED-DUAL"]["statement"]
        == spec["claims"]["DUAL-CERT"]["statement"],
        "restricted dual claim differs from the release specification",
    )

    artifacts_value = manifest.get("artifacts")
    require(isinstance(artifacts_value, list) and bool(artifacts_value), "manifest artifacts must be nonempty")
    artifacts: dict[str, dict[str, Any]] = {}
    assert isinstance(artifacts_value, list)
    for index, artifact in enumerate(artifacts_value):
        field = f"manifest.artifacts[{index}]"
        require(isinstance(artifact, dict), f"{field} must be an object")
        assert isinstance(artifact, dict)
        artifact_id = require_string(artifact.get("id"), f"{field}.id")
        require(IDENTIFIER_RE.fullmatch(artifact_id) is not None, f"invalid artifact ID: {artifact_id}")
        require(artifact_id not in artifacts, f"duplicate artifact ID: {artifact_id}")
        artifact_path = require_bundle_path(root, artifact.get("path"), f"{field}.path")
        require_string(artifact.get("role"), f"{field}.role")
        claim_ids = require_string_list(artifact.get("claims"), f"{field}.claims")
        provenance = artifact.get("provenance")
        require(isinstance(provenance, dict) and bool(provenance), f"{field}.provenance must be nonempty")
        assert isinstance(provenance, dict)
        for name, value in provenance.items():
            require_bundle_path(root, value, f"{field}.provenance.{name}")
        validate_manifest_command(
            root,
            artifact.get("producer"),
            f"{field}.producer",
            outputs_may_be_missing=True,
        )
        verifier = validate_manifest_command(
            root,
            artifact.get("verifier"),
            f"{field}.verifier",
            outputs_may_be_missing=False,
        )
        require(verifier.get("expected_exit") == 0, f"{field}.verifier expected exit is not zero")
        require(artifact_path in verifier.get("inputs", []), f"{field}.verifier does not read its artifact")
        require(all(claim_id in claims for claim_id in claim_ids), f"{field} names an unknown claim")
        artifacts[artifact_id] = artifact

    require(set(artifacts) == {"LB-CERT", "DUAL-CERT"}, "manifest must contain exactly LB-CERT and DUAL-CERT")
    for claim_id, claim in claims.items():
        for artifact_id in claim["artifacts"]:
            require(artifact_id in artifacts, f"claim {claim_id} names an unknown artifact")
            require(claim_id in artifacts[artifact_id]["claims"], f"claim/artifact link is not bidirectional")
    for artifact_id, artifact in artifacts.items():
        for claim_id in artifact["claims"]:
            require(artifact_id in claims[claim_id]["artifacts"], f"artifact/claim link is not bidirectional")
        producer_command = artifact["producer"]["command"]
        require(
            producer_command.count("--run-id") == 1,
            f"{artifact_id} producer command must contain exactly one run ID",
        )
        run_id_index = producer_command.index("--run-id") + 1
        require(run_id_index < len(producer_command), f"{artifact_id} producer run ID is missing")
        result = load_json(root / artifact["path"])
        require(
            result.get("run_id") == producer_command[run_id_index],
            f"{artifact_id} frozen run ID differs from its producer command",
        )

    environment = manifest.get("environment")
    require(isinstance(environment, dict), "manifest.environment must be an object")
    assert isinstance(environment, dict)
    require_string(environment.get("description"), "manifest.environment.description")
    for index, value in enumerate(require_string_list(environment.get("files"), "manifest.environment.files")):
        require_bundle_path(root, value, f"manifest.environment.files[{index}]")
    require_bundle_path(root, manifest.get("verification_report"), "manifest.verification_report")
    repository_verifier = validate_manifest_command(
        root,
        manifest.get("repository_verifier"),
        "manifest.repository_verifier",
        outputs_may_be_missing=False,
    )
    require(
        repository_verifier.get("command") == ["python3", "verification/verify.py"],
        "manifest repository verifier is not the supported entry point",
    )
    require(
        repository_verifier.get("expected_exit") == 0,
        "manifest repository verifier expected exit is not zero",
    )
    require(
        repository_verifier.get("expected_output_prefix") == "VERIFIED:",
        "manifest repository verifier output prefix is incorrect",
    )
    require(
        manifest.get("checksum_inventory") == "SHA256SUMS",
        "manifest checksum inventory is incorrect",
    )
    bundle_audit = manifest.get("bundle_audit")
    require(isinstance(bundle_audit, dict), "manifest.bundle_audit must be an object")
    assert isinstance(bundle_audit, dict)
    require_bundle_path(root, bundle_audit.get("cwd"), "manifest.bundle_audit.cwd", directory=True)
    expected_bundle_audit = [
        "python3",
        "verification/verify_results.py",
        "--root",
        ".",
        "--only",
        "all",
        "--audit-bundle",
    ]
    if release_status == "final":
        expected_bundle_audit.append("--require-final")
    require(
        bundle_audit.get("command") == expected_bundle_audit,
        "manifest bundle-audit command is not the supported entry point",
    )
    require(bundle_audit.get("expected_exit") == 0, "manifest bundle-audit expected exit is not zero")
    return manifest, artifacts


def validate_verification_report(
    root: Path,
    manifest: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    report = load_json(root / manifest["verification_report"])
    require(report.get("schema_version") == 1, "verification report schema_version must equal 1")
    require(report.get("status") == "passed", "verification report status is not passed")
    require(
        report.get("certificate_checks_status") == "passed",
        "verification report certificate checks are not passed",
    )
    require(
        report.get("release_status") == manifest.get("release_status"),
        "verification report and manifest release statuses differ",
    )
    submission_ready = manifest["release_status"] == "final"
    require(
        report.get("submission_ready") is submission_ready,
        "verification report submission readiness is inconsistent",
    )
    expected_blocking_issues = [] if submission_ready else DRAFT_BLOCKING_ISSUES
    require(
        report.get("blocking_issues") == expected_blocking_issues,
        "verification report release blockers are incorrect",
    )
    limitations = report.get("limitations")
    require(isinstance(limitations, list), "verification report limitations must be an array")
    require("paper_build" not in report, "standalone certificate report must not contain a paper build")
    manuscript = report.get("manuscript_reference")
    require(isinstance(manuscript, dict), "verification report manuscript reference is missing")
    assert isinstance(manuscript, dict)
    require(manuscript.get("included") is False, "verification report says the manuscript is included")
    require(manuscript.get("url") == manifest["manuscript"]["url"], "report and manifest manuscript URLs differ")

    checks_value = report.get("artifact_checks")
    require(isinstance(checks_value, list), "verification report artifact_checks must be an array")
    checks: dict[str, dict[str, Any]] = {}
    assert isinstance(checks_value, list)
    for check in checks_value:
        require(isinstance(check, dict), "verification report contains a malformed artifact check")
        assert isinstance(check, dict)
        artifact_id = require_string(check.get("artifact_id"), "verification report artifact_id")
        require(artifact_id not in checks and artifact_id in artifacts, f"invalid artifact check ID: {artifact_id}")
        verifier = artifacts[artifact_id]["verifier"]
        require(check.get("status") == "passed", f"artifact check {artifact_id} did not pass")
        require(check.get("exit_code") == verifier.get("expected_exit"), f"artifact check {artifact_id} exit mismatch")
        require(check.get("cwd") == verifier.get("cwd"), f"artifact check {artifact_id} cwd mismatch")
        require(check.get("command") == verifier.get("command"), f"artifact check {artifact_id} command mismatch")
        checks[artifact_id] = check
    require(set(checks) == set(artifacts), "verification report does not cover every artifact exactly once")

    relocation = report.get("relocation_test")
    require(isinstance(relocation, dict), "verification report relocation test is missing")
    assert isinstance(relocation, dict)
    require(
        relocation.get("status") == "passed"
        and relocation.get("isolated") is True
        and isinstance(relocation.get("environment"), str)
        and bool(relocation["environment"].strip())
        and isinstance(relocation.get("method"), str)
        and bool(relocation["method"].strip()),
        "verification report relocation test is incomplete",
    )
    recomputation = report.get("full_recomputation")
    require(isinstance(recomputation, dict), "verification report full recomputation is missing")
    assert isinstance(recomputation, dict)
    environment = load_json(root / "artifacts/external-run-environment.json")
    require(recomputation.get("status") == "passed", "full recomputation did not pass")
    for field in (
        "run_id",
        "machine",
        "operating_system",
        "python_version",
        "python_flint_version",
        "requested_cores",
        "maximum_aggregate_memory_gib",
        "certificate_result_sha256",
        "started",
        "completed",
    ):
        require(recomputation.get(field) == environment.get(field), f"full recomputation {field} mismatch")
    require(recomputation.get("machine") == "windows", "accepted full recomputation was not run on Windows")
    require(recomputation.get("python_version") == "3.11.9", "accepted Python version is incorrect")
    require(recomputation.get("python_flint_version") == "0.8.0", "accepted python-flint version is incorrect")
    require(
        environment.get("certificate_result_sha256")
        == {
            "LB-CERT": sha256_file(root / "artifacts/lb/result.json"),
            "DUAL-CERT": sha256_file(root / "artifacts/dual/result.json"),
        },
        "Windows result hashes do not identify the bundled certificate results",
    )
    for field in ("code_audit", "path_portability", "result_check"):
        require_bundle_path(root, recomputation.get(field), f"verification report full_recomputation.{field}")
    require(
        recomputation.get("external_result_check_performed_during_finalization")
        is True,
        "external result check was not recorded",
    )
    require(
        recomputation.get("commands")
        == [
            artifacts[artifact_id]["producer"]["command"]
            for artifact_id in ("LB-CERT", "DUAL-CERT")
        ],
        "full recomputation commands differ from the manifest producers",
    )

    code_audit = load_json(root / recomputation["code_audit"])
    require(code_audit.get("status") == "passed", "formula-level code audit is not passed")
    require(code_audit.get("python_flint_version") == "0.8.0", "formula-level audit used the wrong python-flint")
    portability = load_json(root / recomputation["path_portability"])
    require(portability.get("status") == "passed", "path portability record is not passed")
    require(portability.get("scope") == PORTABLE_PATH_SCOPE, "portable-path audit scope is incorrect")
    require(portability.get("normalization_applied") is False, "result JSON was modified after production")
    expected_changed_fields = {"LB-CERT": [], "DUAL-CERT": []}
    require(
        portability.get("verified_changed_fields") == expected_changed_fields,
        "path-portability changed-field record is incorrect",
    )
    require(
        portability.get("verified_paths") == EXPECTED_PORTABLE_PATHS,
        "portable provenance paths are incorrect",
    )
    for field in ("external_result_sha256", "bundled_result_sha256"):
        hashes = portability.get(field)
        require(
            isinstance(hashes, dict)
            and set(hashes) == {"LB-CERT", "DUAL-CERT"}
            and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes.values()),
            f"portable-path audit {field} is malformed",
        )
    require(
        portability["external_result_sha256"] == portability["bundled_result_sha256"],
        "external and bundled result hashes differ",
    )
    require(
        portability["bundled_result_sha256"]
        == {
            "LB-CERT": sha256_file(root / "artifacts/lb/result.json"),
            "DUAL-CERT": sha256_file(root / "artifacts/dual/result.json"),
        },
        "portable-path audit hashes do not identify the bundled artifacts",
    )
    exclusions = portability.get("excluded_transient_records")
    require(isinstance(exclusions, list) and bool(exclusions), "transient-file exclusion record is missing")
    for exclusion in exclusions:
        require(isinstance(exclusion, dict), "transient-file exclusion record is malformed")
        assert isinstance(exclusion, dict)
        excluded_path = require_string(exclusion.get("path"), "transient exclusion path")
        require(safe_relative_path(excluded_path) is not None, "transient exclusion path is unsafe")
        require(excluded_path not in set(manifest["file_inventory"]), "excluded transient file remains in inventory")
        require(
            isinstance(exclusion.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", exclusion["sha256"]) is not None,
            "transient exclusion digest is malformed",
        )
        require_string(exclusion.get("reason"), "transient exclusion reason")
    result_check = load_json(root / recomputation["result_check"])
    require(result_check.get("status") == "passed", "frozen-result check is not passed")
    require(set(result_check.get("checks", {})) == {"LB-CERT", "DUAL-CERT"}, "frozen-result check is incomplete")


def validate_checksums(root: Path, files: tuple[str, ...]) -> int:
    lines = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    checksums: dict[str, str] = {}
    order: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        match = CHECKSUM_RE.fullmatch(line)
        require(match is not None, f"invalid SHA256SUMS line {line_number}")
        assert match is not None
        digest, relative = match.groups()
        require(safe_relative_path(relative) is not None, f"unsafe checksum path: {relative}")
        require(relative != "SHA256SUMS", "SHA256SUMS must not hash itself")
        require(relative not in checksums, f"duplicate checksum entry: {relative}")
        checksums[relative] = digest
        order.append(relative)
    require(order == sorted(order), "SHA256SUMS entries are not sorted")
    expected = set(files) - {"SHA256SUMS"}
    require(set(checksums) == expected, "SHA256SUMS does not cover the exact file inventory")
    for relative, digest in checksums.items():
        require(sha256_file(root / relative) == digest, f"SHA-256 mismatch for {relative}")
    return len(checksums)


def audit_bundle(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    files = inspect_bundle_tree(root)
    scan_bundle_contents(root, files)
    manifest, artifacts = validate_certificate_manifest(root, files, spec)
    validate_verification_report(root, manifest, artifacts)
    checksum_count = validate_checksums(root, files)
    return {
        "status": "passed",
        "certificate_checks_status": "passed",
        "bundle_type": manifest["bundle_type"],
        "release_status": manifest["release_status"],
        "submission_ready": manifest["release_status"] == "final",
        "file_count": len(files),
        "checksum_count": checksum_count,
        "manuscript_included": False,
        "manuscript_url": manifest["manuscript"]["url"],
        "artifact_ids": sorted(artifacts),
    }


def ball_bounds(value: object) -> tuple[Decimal, Decimal]:
    if not isinstance(value, str):
        raise VerificationError(f"expected an Arb string, received {value!r}")
    match = BALL_RE.fullmatch(value.strip())
    if match is None:
        raise VerificationError(f"cannot parse Arb enclosure {value!r}")
    midpoint = Decimal(match.group(1))
    radius = Decimal(match.group(2) or "0")
    if radius < 0:
        raise VerificationError(f"negative Arb radius in {value!r}")
    return midpoint - radius, midpoint + radius


def record_bounds(record: object, field: str) -> tuple[Decimal, Decimal]:
    if not isinstance(record, dict) or field not in record:
        raise VerificationError(f"missing interval field {field}")
    return ball_bounds(record[field])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def intervals_overlap(
    first: tuple[Decimal, Decimal],
    second: tuple[Decimal, Decimal],
) -> bool:
    return max(first[0], second[0]) <= min(first[1], second[1])


def require_overlap(
    first: tuple[Decimal, Decimal],
    second: tuple[Decimal, Decimal],
    message: str,
) -> None:
    require(intervals_overlap(first, second), message)


def load_lb_candidate(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    payload = load_json(root / spec["files"]["lb_input"]["path"])
    require(
        payload.get("proof_status")
        == "exact candidate input used by LB-CERT; certification status is determined by the paired result artifact",
        "LB candidate status metadata is stale",
    )
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


def verify_file_hashes(root: Path, spec: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for artifact_id, record in spec["files"].items():
        path = root / record["path"]
        require(path.is_file(), f"missing required file {record['path']}")
        digest = sha256_file(path)
        require(
            digest == record["sha256"],
            f"SHA-256 mismatch for {record['path']}: {digest}",
        )
        observed[artifact_id] = digest
    return observed


def verify_lb(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    claim = spec["claims"]["LB-CERT"]
    expected_parameters = load_lb_candidate(root, spec)
    result = load_json(root / "artifacts/lb/result.json")
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

    source = result.get("source", {})
    require(isinstance(source, dict), "LB-CERT source record is missing")
    files = spec["files"]
    require(source.get("sha256") == files["lb_wrapper"]["sha256"], "LB wrapper digest mismatch in result")
    require(source.get("verifier_sha256") == files["lb_core"]["sha256"], "LB core digest mismatch in result")
    require(source.get("parameters_sha256") == files["lb_input"]["sha256"], "LB input digest mismatch in result")

    mu_bounds = record_bounds(result.get("mu_weight"), "ball")
    scalar_bounds = record_bounds(result.get("scalar_norm_bound"), "ball")
    rho = Decimal(expected_parameters["rho"])
    expected_scalar_bounds = (rho + mu_bounds[0], rho + mu_bounds[1])
    require_overlap(scalar_bounds, expected_scalar_bounds, "LB scalar bound is inconsistent with rho + mu_W")
    require(scalar_bounds[0] > 0, "LB scalar denominator is not positive")

    ratio_bounds = record_bounds(result.get("lower_ratio"), "ball")
    expected_ratio_bounds = (
        (Decimal(1) - rho) / scalar_bounds[1],
        (Decimal(1) - rho) / scalar_bounds[0],
    )
    require_overlap(ratio_bounds, expected_ratio_bounds, "LB ratio is inconsistent with its scalar bound")
    ratio_lower, _ = record_bounds(result.get("lower_ratio"), "lower")
    require(ratio_lower > Decimal(claim["threshold"]), "LB ratio does not exceed the theorem threshold")
    ratio_margin_bounds = record_bounds(result.get("ratio_margin_over_certified_threshold"), "ball")
    expected_ratio_margin = (
        ratio_bounds[0] - Decimal(claim["threshold"]),
        ratio_bounds[1] - Decimal(claim["threshold"]),
    )
    require_overlap(ratio_margin_bounds, expected_ratio_margin, "LB ratio margin is inconsistent")
    require(ratio_margin_bounds[0] > 0, "LB ratio margin is not positive")

    pivot_lower, _ = ball_bounds(result.get("worst_residual_pivot", {}).get("lower_bound"))
    require(pivot_lower > Decimal(claim["minimum_residual_pivot"]), "LB residual-pivot margin is too small")
    woodbury_lower, _ = record_bounds(result.get("woodbury_margin"), "lower")
    require(woodbury_lower > Decimal(claim["minimum_woodbury_margin"]), "LB Woodbury margin is too small")
    xi_bounds = record_bounds(result.get("xi"), "ball")
    woodbury_bounds = record_bounds(result.get("woodbury_margin"), "ball")
    require_overlap(
        woodbury_bounds,
        (Decimal(1) - xi_bounds[1], Decimal(1) - xi_bounds[0]),
        "LB Woodbury margin is inconsistent with 1 - xi",
    )
    cancellation_lower, _ = record_bounds(result.get("cancellation_free_quantity"), "lower")
    require(cancellation_lower > 0, "LB cancellation-free Woodbury quantity is not positive")
    main_pivot_lower, _ = ball_bounds(result.get("main_minimum_pivot_lower_bound"))
    require(main_pivot_lower > 0, "LB main-matrix pivot is not positive")
    _, mu_upper = record_bounds(result.get("mu_weight"), "upper")
    require(mu_upper < Decimal(claim["maximum_mu_weight"]), "LB mu_W upper bound is too large")

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
    observed_blocks: dict[tuple[int, int], tuple[Decimal, Decimal]] = {}
    pivot_count = 0
    all_pivot_bounds: list[tuple[Decimal, Decimal]] = []
    for block in blocks:
        require(isinstance(block, dict), "LB residual block record is not an object")
        bidegree = block.get("residual_bidegree")
        require(
            isinstance(bidegree, list)
            and len(bidegree) == 2
            and all(isinstance(value, int) for value in bidegree),
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
        "result_sha256": sha256_file(root / "artifacts/lb/result.json"),
    }


def verify_exact_dual_input(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    payload = load_json(root / spec["files"]["dual_input"]["path"])
    require(
        payload.get("proof_status")
        == "exact candidate input used by DUAL-CERT; certification status is determined by the paired result artifact",
        "DUAL candidate status metadata is stale",
    )
    require(
        payload.get("target_squared_ceiling") == spec["claims"]["DUAL-CERT"]["threshold"],
        "DUAL candidate target differs from the release threshold",
    )
    require(
        payload.get("buffered_squared_ceiling")
        == spec["claims"]["DUAL-CERT"]["coarse_threshold"],
        "DUAL candidate buffered ceiling differs from the release specification",
    )
    atoms = payload.get("atoms")
    require(isinstance(atoms, list), "DUAL atom list is missing")
    claim = spec["claims"]["DUAL-CERT"]
    require(len(atoms) == claim["atom_count"], "DUAL atom count mismatch")
    q_values = [Fraction(str(atom["q"])) for atom in atoms]
    weights = [Fraction(str(atom["weight"])) for atom in atoms]
    require(all(Fraction(0) < q < Fraction(1) for q in q_values), "DUAL atom lies outside (0,1)")
    require(all(weight > 0 for weight in weights), "DUAL atom weight is not positive")
    require(sum(weights, Fraction(0)) == Fraction(1), "DUAL weights do not sum exactly to one")
    return payload


def verify_dual(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    claim = spec["claims"]["DUAL-CERT"]
    verify_exact_dual_input(root, spec)
    result = load_json(root / "artifacts/dual/result.json")
    require(result.get("status") == "completed", "DUAL-CERT status is not completed")
    require(
        result.get("proof_status") == "directed continuum ceiling certificate",
        "DUAL-CERT proof status is incorrect",
    )
    require(result.get("target_squared_ceiling") == claim["threshold"], "DUAL-CERT threshold mismatch")
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
    require(configuration.get("candidate_sha256") == spec["files"]["dual_input"]["sha256"], "DUAL input digest mismatch in result")
    source = result.get("source", {})
    require(isinstance(source, dict), "DUAL-CERT source record is missing")
    require(source.get("sha256") == spec["files"]["dual_verifier"]["sha256"], "DUAL verifier digest mismatch in result")
    require(result.get("atom_count") == claim["atom_count"], "DUAL result atom count mismatch")
    weight_sum_lower, weight_sum_upper = record_bounds(result.get("weight_sum"), "ball")
    require(weight_sum_lower <= Decimal(1) <= weight_sum_upper, "DUAL reported weight sum does not enclose one")
    require(result.get("points") == [], "DUAL continuum result unexpectedly contains point records")

    continuum = result.get("continuum")
    require(isinstance(continuum, dict), "DUAL continuum record is missing")
    require(continuum.get("cover_start") == claim["cover_start"], "DUAL cover start mismatch")
    require(continuum.get("cover_end") == claim["cover_end"], "DUAL cover end mismatch")
    require(continuum.get("interval_count") == claim["interval_count"], "DUAL interval count mismatch")
    require(continuum.get("derivative_order") == claim["derivative_order"], "DUAL continuum derivative order mismatch")
    threshold = Decimal(claim["threshold"])

    intervals = continuum.get("intervals")
    require(isinstance(intervals, list), "DUAL interval list is missing")
    require(len(intervals) == claim["interval_count"], "DUAL interval list length mismatch")
    expected_left = Fraction(claim["cover_start"])
    interval_upper_bounds: list[tuple[Decimal, Decimal]] = []
    margin_bounds: list[tuple[Decimal, Decimal]] = []
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
            (threshold - upper_bounds[1], threshold - upper_bounds[0]),
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
    coarse_margin = Decimal(claim["coarse_threshold"]) - maximum_upper
    require(coarse_margin > Decimal(claim["minimum_coarse_margin"]), "DUAL coarse safety margin is too small")

    tail = continuum.get("global_tail", {})
    require(isinstance(tail, dict), "DUAL global tail record is missing")
    require(tail.get("required") is True and tail.get("certified") is True, "DUAL global tail is not certified")
    require(tail.get("inequality_exponent") == "3/4", "DUAL global tail used the wrong exponent")
    tail_square_bounds = ball_bounds(tail.get("squared_upper"))
    tail_upper = tail_square_bounds[1]
    require(tail_upper < Decimal(claim["maximum_tail_square"]), "DUAL global tail bound is too large")
    require(tail_upper < threshold, "DUAL global tail exceeds the theorem threshold")
    tail_margin_bounds = ball_bounds(tail.get("margin_lower"))
    require(tail_margin_bounds[0] > 0, "DUAL global tail margin is not positive")
    require_overlap(
        tail_margin_bounds,
        (threshold - tail_square_bounds[1], threshold - tail_square_bounds[0]),
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
        "result_sha256": sha256_file(root / "artifacts/dual/result.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--only", choices=("all", "LB-CERT", "DUAL-CERT"), default="all")
    parser.add_argument("--audit-bundle", action="store_true")
    parser.add_argument("--require-final", action="store_true")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    if arguments.require_final and not arguments.audit_bundle:
        parser.error("--require-final requires --audit-bundle")
    root = arguments.root.resolve()
    spec = load_json(root / "claims/release-spec.json")
    observed_hashes = verify_file_hashes(root, spec)
    checks: dict[str, Any] = {}
    if arguments.only in ("all", "LB-CERT"):
        checks["LB-CERT"] = verify_lb(root, spec)
    if arguments.only in ("all", "DUAL-CERT"):
        checks["DUAL-CERT"] = verify_dual(root, spec)
    report = {
        "schema_version": 1,
        "status": "passed",
        "certificate_checks_status": "passed",
        "release_id": spec["release_id"],
        "verified_file_hashes": observed_hashes,
        "checks": checks,
    }
    if arguments.audit_bundle:
        require(arguments.only == "all", "--audit-bundle requires --only all")
        report["bundle_audit"] = audit_bundle(root, spec)
    release_gate_failed = bool(
        arguments.require_final
        and not report.get("bundle_audit", {}).get("submission_ready")
    )
    if arguments.require_final:
        report["release_gate"] = {
            "required_release_status": "final",
            "status": "failed" if release_gate_failed else "passed",
        }
    if arguments.report is not None:
        output = arguments.report if arguments.report.is_absolute() else root / arguments.report
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if release_gate_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

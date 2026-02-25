from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from seedpipe.tools.contracts import TinySchemaValidator, ValidationIssue, load_schema_store, resolve_contract
from seedpipe.tools.diff import diff_manifests
from seedpipe.tools.runner import run_fixture_allow_failure, run_fixture_once

ALLOWED_TYPES = {
    "contract_validation_failed",
    "contract_missing_schema",
    "contract_missing_artifact",
    "determinism_mismatch",
    "resume_mismatch",
    "resume_incomplete",
}


class Verifier:
    def __init__(self, fixture: str, max_errors: int = 20) -> None:
        self.fixture_dir = Path("seedpipe/fixtures/phase1") / fixture
        self.contracts_dir = Path("seedpipe/spec/phase1/contracts")
        self.defects_dir = Path("defects")
        self.max_errors = max_errors
        self.schemas, self.artifact_map = load_schema_store(self.contracts_dir)
        self.validator = TinySchemaValidator(self.schemas)
        self.failures = 0

    def emit_defect(self, defect: dict[str, Any]) -> None:
        d_type = defect["type"]
        assert d_type in ALLOWED_TYPES
        scope = defect.get("location", {}).get("stage_id") or "global"
        material = json.dumps({"type": d_type, "location": defect.get("location", {}), "message": defect.get("message", "")}, sort_keys=True)
        short_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]
        self.defects_dir.mkdir(parents=True, exist_ok=True)
        path = self.defects_dir / f"{d_type}__{scope}__{short_hash}.json"
        path.write_text(json.dumps(defect, indent=2, sort_keys=True) + "\n")
        self.failures += 1

    def mk_defect(self, defect_type: str, location: dict[str, Any], message: str, hint: str, evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "defect_version": "phase1-v0",
            "type": defect_type,
            "severity": "error",
            "location": location,
            "message": message,
            "hint": hint,
            "evidence": evidence,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def _iter_artifacts(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        refs = list(manifest.get("inputs", []))
        for stage in manifest.get("stage_outputs", []):
            for out in stage.get("outputs", []):
                ref = dict(out)
                ref["_stage_id"] = stage.get("stage_id")
                refs.append(ref)
        for out in manifest.get("final_outputs", []):
            refs.append(out)
        return refs

    def _validate_data(self, data: Any, schema_id: str, pointer_base: str = "") -> list[ValidationIssue]:
        schema = self.schemas.get(schema_id)
        if schema is None:
            return [ValidationIssue(pointer=pointer_base or "/", message=f"unknown schema id {schema_id}")]
        return self.validator.validate(data, schema, pointer_base)

    def contract_test(self, manifest: dict[str, Any], manifest_path: Path) -> None:
        manifest_schema = "seedpipe://spec/phase1/contracts/manifest.schema.json"
        issues = self._validate_data(manifest, manifest_schema, "")
        if issues:
            issue = issues[0]
            self.emit_defect(
                self.mk_defect(
                    "contract_validation_failed",
                    {"stage_id": "global", "artifact_name": "manifest.json", "path": str(manifest_path), "pointer": issue.pointer},
                    "Manifest failed contract validation.",
                    "Inspect manifest fields against manifest.schema.json.",
                    {"schema_id": manifest_schema, "error_summary": issue.message, "validator": "tiny-schema-v1"},
                )
            )

        for ref in self._iter_artifacts(manifest):
            name = ref.get("name", "")
            stage_id = ref.get("_stage_id", ref.get("produced_by", {}).get("stage_id", "global"))
            artifact_path = Path(ref.get("path", ""))
            if not artifact_path.is_absolute():
                artifact_path = Path.cwd() / artifact_path
            location = {"run_id": manifest.get("run_id", ""), "stage_id": stage_id, "artifact_name": name, "path": str(artifact_path)}
            if not artifact_path.exists():
                self.emit_defect(
                    self.mk_defect(
                        "contract_missing_artifact",
                        location,
                        "Artifact referenced by manifest does not exist.",
                        "Ensure the stage committed the artifact to the expected path.",
                        {"artifact_ref": ref},
                    )
                )
                continue

            resolved = resolve_contract(name, self.artifact_map, ref.get("schema_version", ""))
            if resolved is None or not resolved[1]:
                self.emit_defect(
                    self.mk_defect(
                        "contract_missing_schema",
                        location,
                        "No contract schema mapping was found for artifact.",
                        "Add artifact mapping to artifact_contracts.yaml or set schema_version to known schema id.",
                        {"artifact_name": name, "schema_version": ref.get("schema_version")},
                    )
                )
                continue

            kind, schema_name_or_id = resolved
            schema_id = schema_name_or_id
            if not schema_id.startswith("seedpipe://"):
                schema = json.loads((self.contracts_dir / schema_id).read_text())
                schema_id = schema["$id"]

            if kind == "json":
                try:
                    payload = json.loads(artifact_path.read_text())
                except json.JSONDecodeError as exc:
                    self.emit_defect(self.mk_defect("contract_validation_failed", location | {"pointer": "/"}, "Artifact is not valid JSON.", "Fix the artifact writer to emit valid JSON.", {"error_summary": str(exc), "schema_id": schema_id, "validator": "tiny-schema-v1"}))
                    continue
                issues = self._validate_data(payload, schema_id, "")[: self.max_errors]
            else:
                issues = []
                for idx, line in enumerate(artifact_path.read_text().splitlines()):
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError as exc:
                        issues.append(ValidationIssue(pointer=f"/{idx}", message=f"invalid JSONL row: {exc}"))
                        if len(issues) >= self.max_errors:
                            break
                        continue
                    row_issues = self._validate_data(payload, schema_id, f"/{idx}")
                    issues.extend(row_issues)
                    if len(issues) >= self.max_errors:
                        break
            if issues:
                first = issues[0]
                self.emit_defect(
                    self.mk_defect(
                        "contract_validation_failed",
                        location | {"pointer": first.pointer},
                        "Artifact failed contract validation.",
                        "Inspect artifact bytes and schema_version mapping for this artifact.",
                        {
                            "schema_id": schema_id,
                            "validator": "tiny-schema-v1",
                            "error_summary": first.message,
                            "error_details": [{"pointer": i.pointer, "message": i.message} for i in issues],
                        },
                    )
                )

    def determinism_test(self) -> None:
        run_a = run_fixture_once(self.fixture_dir, "determinism")
        run_b = run_fixture_once(self.fixture_dir, "determinism")
        self.contract_test(run_a.manifest, run_a.manifest_path)
        self.contract_test(run_b.manifest, run_b.manifest_path)
        diff = diff_manifests(run_a.manifest, run_b.manifest)
        if not diff["equal"]:
            self.emit_defect(
                self.mk_defect(
                    "determinism_mismatch",
                    {"stage_id": "global"},
                    "Determinism check failed: repeated fixture runs diverged.",
                    "Compare artifact hashes and semantic manifest fields to find non-deterministic behavior.",
                    diff,
                )
            )

    def resume_test(self) -> None:
        golden = run_fixture_once(self.fixture_dir, "resume")
        crash_env = {"SEEDPIPE_CRASH_AT": "stage:validate:before_commit", "SEEDPIPE_CRASH_ONCE": "1"}
        code, workspace, output = run_fixture_allow_failure(self.fixture_dir, "resume", env_overrides=crash_env)
        if code == 0:
            self.emit_defect(self.mk_defect("resume_incomplete", {"stage_id": "validate"}, "Crash-injected run unexpectedly succeeded.", "Ensure crash injection is wired and triggers once during resume test.", {"output": output}))
            return
        try:
            resumed = run_fixture_once(self.fixture_dir, "resume", workdir=workspace)
        except RuntimeError as exc:
            self.emit_defect(self.mk_defect("resume_incomplete", {"stage_id": "global"}, "Resume rerun did not complete.", "Inspect resume mechanics and partial state handling.", {"error": str(exc), "crash_output": output}))
            return
        self.contract_test(golden.manifest, golden.manifest_path)
        self.contract_test(resumed.manifest, resumed.manifest_path)
        diff = diff_manifests(golden.manifest, resumed.manifest)
        if not diff["equal"]:
            self.emit_defect(self.mk_defect("resume_mismatch", {"stage_id": "global"}, "Resume run completed but output diverges from golden run.", "Check atomic stage commits and idempotent behavior on rerun.", diff))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 1 deterministic verifier")
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--max-errors-per-artifact", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    verifier = Verifier(args.fixture, max_errors=args.max_errors_per_artifact)
    try:
        verifier.determinism_test()
        verifier.resume_test()
    except Exception:
        return 2
    return 0 if verifier.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

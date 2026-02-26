from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


ArtifactKind = Literal["json", "jsonl"]
DefectType = Literal[
    "contract_validation_failed",
    "contract_missing_schema",
    "contract_missing_artifact",
    "determinism_mismatch",
    "resume_mismatch",
    "resume_incomplete",
]


class ProducedBy(TypedDict, total=False):
    stage_id: str


class ArtifactRef(TypedDict, total=False):
    name: str
    path: str
    schema_version: str
    produced_by: ProducedBy
    _stage_id: NotRequired[str]


class StageOutputsEntry(TypedDict, total=False):
    stage_id: str
    outputs: list[ArtifactRef]


class Manifest(TypedDict, total=False):
    run_id: str
    inputs: list[ArtifactRef]
    stage_outputs: list[StageOutputsEntry]
    final_outputs: list[ArtifactRef]


class DefectLocation(TypedDict, total=False):
    run_id: str
    stage_id: str
    artifact_name: str
    path: str
    pointer: str


class Defect(TypedDict):
    defect_version: str
    type: DefectType
    severity: str
    location: DefectLocation
    message: str
    hint: str
    evidence: dict[str, Any]
    created_at: str

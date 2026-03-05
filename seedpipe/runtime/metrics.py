from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from seedpipe.tools.contracts import RecursiveSchemaValidator


MetricName = Literal["latency", "cost", "success_count", "failure_count", "quality_rating"]
MetricUnit = Literal["ms", "USD", "count", "1-5"]
Severity = Literal["error", "warning"]

_ALLOWED_METRIC_NAMES: set[str] = {"latency", "cost", "success_count", "failure_count", "quality_rating"}
_ALLOWED_METRIC_UNITS: set[str] = {"ms", "USD", "count", "1-5"}
_ALLOWED_FINDING_SEVERITY: set[str] = {"error", "warning"}


@dataclass(frozen=True)
class MetricRecord:
    function_id: str
    metric_name: MetricName
    value: float
    unit: MetricUnit
    timestamp: str
    run_id: str
    producer: str

    def __post_init__(self) -> None:
        if not isinstance(self.function_id, str) or not self.function_id.strip():
            raise ValueError("function_id must be a non-empty string")
        if str(self.metric_name) not in _ALLOWED_METRIC_NAMES:
            raise ValueError(f"metric_name must be one of {sorted(_ALLOWED_METRIC_NAMES)}")
        if not isinstance(self.value, (int, float)):
            raise ValueError("value must be numeric")
        if str(self.unit) not in _ALLOWED_METRIC_UNITS:
            raise ValueError(f"unit must be one of {sorted(_ALLOWED_METRIC_UNITS)}")
        if not isinstance(self.timestamp, str) or not self.timestamp.strip():
            raise ValueError("timestamp must be a non-empty string")
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(self.producer, str) or not self.producer.strip():
            raise ValueError("producer must be a non-empty string")
        # Validate that timestamp is parseable (accepts ISO 8601 with optional Z suffix).
        try:
            dt.datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"timestamp must be ISO 8601 parseable: {self.timestamp}") from exc

    @classmethod
    def from_execution(
        cls,
        function_id: str,
        metric_name: MetricName,
        value: float,
        unit: MetricUnit,
        run_id: str,
        producer: str,
    ) -> MetricRecord:
        return cls(
            function_id=function_id,
            metric_name=metric_name,
            value=float(value),
            unit=unit,
            timestamp=dt.datetime.now().isoformat(),
            run_id=run_id,
            producer=producer
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MetricRecord:
        return cls(
            function_id=str(payload.get("function_id", "")),
            metric_name=str(payload.get("metric_name", "")),  # type: ignore[arg-type]
            value=float(payload.get("value", 0.0)),
            unit=str(payload.get("unit", "")),  # type: ignore[arg-type]
            timestamp=str(payload.get("timestamp", "")),
            run_id=str(payload.get("run_id", "")),
            producer=str(payload.get("producer", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "function_id": self.function_id,
            "metric_name": self.metric_name,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "producer": self.producer
        }


@dataclass(frozen=True)
class GovernanceFinding:
    finding_id: str
    policy_id: str
    severity: Severity
    metric_name: str | None
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.finding_id, str) or not self.finding_id.strip():
            raise ValueError("finding_id must be a non-empty string")
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise ValueError("policy_id must be a non-empty string")
        if str(self.severity) not in _ALLOWED_FINDING_SEVERITY:
            raise ValueError(f"severity must be one of {sorted(_ALLOWED_FINDING_SEVERITY)}")
        if self.metric_name is not None and (not isinstance(self.metric_name, str) or not self.metric_name.strip()):
            raise ValueError("metric_name must be None or a non-empty string")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be a non-empty string")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GovernanceFinding:
        metric_name = payload.get("metric_name")
        metric_name_value = str(metric_name) if metric_name is not None else None
        return cls(
            finding_id=str(payload.get("finding_id", "")),
            policy_id=str(payload.get("policy_id", "")),
            severity=str(payload.get("severity", "")),  # type: ignore[arg-type]
            metric_name=metric_name_value,
            message=str(payload.get("message", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "finding_id": self.finding_id,
            "policy_id": self.policy_id,
            "severity": self.severity,
            "message": self.message
        }
        if self.metric_name:
            result["metric_name"] = self.metric_name
        return result


@dataclass(frozen=True)
class FunctionMetricStatus:
    function_id: str
    eligible_for_comparison: bool
    last_updated_at: str
    policy_id: str
    max_age_seconds: int
    findings: tuple[GovernanceFinding, ...] = field(default_factory=tuple)
    metrics_present: dict[str, bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.function_id, str) or not self.function_id.strip():
            raise ValueError("function_id must be a non-empty string")
        if not isinstance(self.eligible_for_comparison, bool):
            raise ValueError("eligible_for_comparison must be a boolean")
        if not isinstance(self.last_updated_at, str) or not self.last_updated_at.strip():
            raise ValueError("last_updated_at must be a non-empty string")
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise ValueError("policy_id must be a non-empty string")
        if not isinstance(self.max_age_seconds, int) or self.max_age_seconds < 0:
            raise ValueError("max_age_seconds must be an integer >= 0")
        if any(not isinstance(item, GovernanceFinding) for item in self.findings):
            raise ValueError("findings must contain GovernanceFinding values")
        if not isinstance(self.metrics_present, dict):
            raise ValueError("metrics_present must be an object")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FunctionMetricStatus:
        findings_payload = payload.get("findings", [])
        findings: tuple[GovernanceFinding, ...] = ()
        if isinstance(findings_payload, list):
            findings = tuple(
                GovernanceFinding.from_dict(item)
                for item in findings_payload
                if isinstance(item, dict)
            )
        metrics_present_raw = payload.get("metrics_present", {})
        metrics_present: dict[str, bool | None] = {}
        if isinstance(metrics_present_raw, dict):
            for key, value in metrics_present_raw.items():
                if isinstance(key, str):
                    metrics_present[key] = value if isinstance(value, bool) or value is None else None
        return cls(
            function_id=str(payload.get("function_id", "")),
            eligible_for_comparison=bool(payload.get("eligible_for_comparison", False)),
            last_updated_at=str(payload.get("last_updated_at", "")),
            policy_id=str(payload.get("policy_id", "")),
            max_age_seconds=int(payload.get("max_age_seconds", 0)),
            findings=findings,
            metrics_present=metrics_present,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "function_id": self.function_id,
            "eligible_for_comparison": self.eligible_for_comparison,
            "last_updated_at": self.last_updated_at,
            "policy_id": self.policy_id,
            "max_age_seconds": self.max_age_seconds,
            "findings": [f.to_dict() for f in self.findings],
            "metrics_present": self.metrics_present
        }


class MetricsValidator:
    def __init__(self):
        schema_path = self._resolve_schema_path()
        if not schema_path.exists():
            raise FileNotFoundError(f"metrics contract schema not found in expected locations")
        with schema_path.open() as f:
            self.schema = json.load(f)
        self._validator = RecursiveSchemaValidator()

    @staticmethod
    def _resolve_schema_path() -> Path:
        module_root = Path(__file__).resolve().parents[2]
        candidates = [
            module_root / "docs" / "specs" / "phase1" / "contracts" / "metrics_contract.schema.json",
            Path("docs/specs/phase1/contracts/metrics_contract.schema.json"),
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]

    def validate(self, record: dict[str, Any]) -> list[str]:
        return self._validator.validate(record, self.schema)


class MetricsEmitter:
    def __init__(self, run_id: str, producer: str):
        self.run_id = run_id
        self.producer = producer
        self.metrics_dir = Path("artifacts") / "metrics"
        self.metrics_dir.mkdir(parents=True, exist_ok=True)

    def emit(self, record: MetricRecord) -> Path:
        record_dict = record.to_dict()
        filename = f"{record.function_id}__{record.metric_name}__{self.run_id}.jsonl"
        path = self.metrics_dir / filename
        
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record_dict, sort_keys=True) + "\n")
        
        return path


class MetricsGovernanceChecker:
    def __init__(self, max_age_seconds: int = 3600):
        self.max_age_seconds = max_age_seconds
        self.required_metrics = ["latency", "cost", "success_count", "failure_count", "quality_rating"]
        self._empty_timestamp = "1970-01-01T00:00:00+00:00"

    def check(self, function_id: str, metrics_dir: Path | None = None) -> FunctionMetricStatus:
        if not metrics_dir or not metrics_dir.exists():
            return FunctionMetricStatus(
                function_id=function_id,
                eligible_for_comparison=False,
                last_updated_at=self._empty_timestamp,
                policy_id="FR-016",
                max_age_seconds=self.max_age_seconds,
                findings=[GovernanceFinding(
                    finding_id=f"{function_id}_no_metrics_dir",
                    policy_id="FR-016",
                    severity="error",
                    metric_name=None,
                    message=f"No metrics directory found for function {function_id}"
                )],
                metrics_present={m: False for m in self.required_metrics}
            )

        now = dt.datetime.now()
        latest_timestamp = None
        present_metrics: dict[str, bool | None] = {m: False for m in self.required_metrics}

        if metrics_dir.exists():
            for metric_file in metrics_dir.glob(f"{function_id}__*.jsonl"):
                with metric_file.open() as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            metric_name = record.get("metric_name")
                            timestamp_str = record.get("timestamp", "")
                            
                            if metric_name and metric_name in self.required_metrics:
                                present_metrics[metric_name] = True

                            if timestamp_str:
                                try:
                                    ts = dt.datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                                    if latest_timestamp is None or ts > latest_timestamp:
                                        latest_timestamp = ts
                                except ValueError:
                                    pass
                        except json.JSONDecodeError:
                            continue

        findings: list[GovernanceFinding] = []
        missing_metrics = [m for m in self.required_metrics if not present_metrics.get(m)]
        
        for metric_name in missing_metrics:
            findings.append(GovernanceFinding(
                finding_id=f"{function_id}_missing_{metric_name}",
                policy_id="FR-010",
                severity="error",
                metric_name=metric_name,
                message=f"Required metric dimension '{metric_name}' is missing"
            ))

        stale_findings: list[GovernanceFinding] = []
        if latest_timestamp and self.max_age_seconds > 0:
            age = (now - latest_timestamp.replace(tzinfo=None)).total_seconds()
            if age > self.max_age_seconds:
                stale_findings.append(GovernanceFinding(
                    finding_id=f"{function_id}_stale_metrics",
                    policy_id="FR-009",
                    severity="error",
                    metric_name=None,
                    message=f"Metrics are stale (age={age:.0f}s exceeds max_age={self.max_age_seconds}s)"
                ))

        eligible = len(missing_metrics) == 0 and len(stale_findings) == 0
        
        return FunctionMetricStatus(
            function_id=function_id,
            eligible_for_comparison=eligible,
            last_updated_at=latest_timestamp.isoformat() if latest_timestamp else self._empty_timestamp,
            policy_id="FR-016",
            max_age_seconds=self.max_age_seconds,
            findings=findings + stale_findings,
            metrics_present=present_metrics
        )

    def check_all_functions(self, function_ids: list[str], metrics_dir: Path) -> dict[str, FunctionMetricStatus]:
        return {fid: self.check(fid, metrics_dir) for fid in function_ids}

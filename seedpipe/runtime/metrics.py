from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Literal


MetricName = Literal["latency", "cost", "success_count", "failure_count", "quality_rating"]
MetricUnit = Literal["ms", "USD", "count", "1-5"]


class MetricRecord:
    function_id: str
    metric_name: MetricName
    value: float
    unit: MetricUnit
    timestamp: str
    run_id: str
    producer: str

    def __init__(self, function_id: str, metric_name: Literal["latency", "cost", "success_count", "failure_count", "quality_rating"], value: float, unit: Literal["ms", "USD", "count", "1-5"], timestamp: str, run_id: str, producer: str):
        self.function_id = function_id
        self.metric_name = metric_name
        self.value = value
        self.unit = unit
        self.timestamp = timestamp
        self.run_id = run_id
        self.producer = producer

    @classmethod
    def from_execution(cls, function_id: str, metric_name: Literal["latency", "cost", "success_count", "failure_count", "quality_rating"], value: float, unit: Literal["ms", "USD", "count", "1-5"], run_id: str, producer: str) -> MetricRecord:
        return cls(
            function_id=function_id,
            metric_name=metric_name,
            value=value,
            unit=unit,
            timestamp=dt.datetime.now().isoformat(),
            run_id=run_id,
            producer=producer
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


class GovernanceFinding:
    def __init__(self, finding_id: str, policy_id: str, severity: Literal["error", "warning"], metric_name: str | None, message: str):
        self.finding_id = finding_id
        self.policy_id = policy_id
        self.severity = severity
        self.metric_name = metric_name
        self.message = message

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


class FunctionMetricStatus:
    def __init__(self, function_id: str, eligible_for_comparison: bool, last_updated_at: str, policy_id: str, max_age_seconds: int, findings: list[GovernanceFinding] | None = None, metrics_present: dict[str, bool | None] | None = None):
        self.function_id = function_id
        self.eligible_for_comparison = eligible_for_comparison
        self.last_updated_at = last_updated_at
        self.policy_id = policy_id
        self.max_age_seconds = max_age_seconds
        self.findings = findings or []
        self.metrics_present = metrics_present or {}

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

    @staticmethod
    def _resolve_schema_path() -> Path:
        module_root = Path(__file__).resolve().parents[2]
        candidates = [
            module_root / "docs" / "specs" / "phase1" / "contracts" / "metrics_contract.schema.json",
            module_root / "docs" / "specs" / "phase1" / "contracts" / "metrics_contract.json",
            Path("docs/specs/phase1/contracts/metrics_contract.schema.json"),
            Path("docs/specs/phase1/contracts/metrics_contract.json"),
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]

    def validate(self, record: dict[str, Any]) -> list[str]:
        return self._validate_against_schema(record, self.schema, [])

    def _validate_against_schema(self, data: Any, schema: dict[str, Any], path: list[str]) -> list[str]:
        issues = []
        if "type" in schema:
            expected_type = schema["type"]
            if expected_type == "string" and not isinstance(data, str):
                path_str = ".".join(path) if path else "root"
                issues.append(f"{path_str}: expected string, got {type(data).__name__}")
            elif expected_type == "number" and not isinstance(data, (int, float)):
                path_str = ".".join(path) if path else "root"
                issues.append(f"{path_str}: expected number, got {type(data).__name__}")
            elif expected_type == "integer" and not isinstance(data, int):
                path_str = ".".join(path) if path else "root"
                issues.append(f"{path_str}: expected integer, got {type(data).__name__}")
            elif expected_type == "boolean" and not isinstance(data, bool):
                path_str = ".".join(path) if path else "root"
                issues.append(f"{path_str}: expected boolean, got {type(data).__name__}")
            elif expected_type == "array" and not isinstance(data, list):
                path_str = ".".join(path) if path else "root"
                issues.append(f"{path_str}: expected array, got {type(data).__name__}")
            elif expected_type == "object" and not isinstance(data, dict):
                path_str = ".".join(path) if path else "root"
                issues.append(f"{path_str}: expected object, got {type(data).__name__}")

        if "enum" in schema and data not in schema["enum"]:
            path_str = ".".join(path) if path else "root"
            issues.append(f"{path_str}: value {data!r} not in enum {schema['enum']}")

        if isinstance(data, dict) and "properties" in schema:
            for prop_name, prop_schema in schema["properties"].items():
                if prop_name in data:
                    issues.extend(self._validate_against_schema(data[prop_name], prop_schema, path + [prop_name]))

        if isinstance(data, dict) and "required" in schema:
            for req_field in schema["required"]:
                if req_field not in data:
                    path_str = ".".join(path) if path else "root"
                    issues.append(f"{path_str}: missing required field '{req_field}'")

        return issues


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

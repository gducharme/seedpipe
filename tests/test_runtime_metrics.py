from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from seedpipe.runtime.metrics import (
    FunctionMetricStatus,
    GovernanceFinding,
    MetricRecord,
    MetricsEmitter,
    MetricsGovernanceChecker,
    MetricsValidator,
)


class MetricRecordTests(unittest.TestCase):
    def test_record_creation(self) -> None:
        record = MetricRecord(
            function_id="bg-removal",
            metric_name="latency",
            value=150.5,
            unit="ms",
            timestamp="2026-03-01T12:00:00",
            run_id="run-123",
            producer="agent-v1"
        )
        self.assertEqual(record.function_id, "bg-removal")
        self.assertEqual(record.metric_name, "latency")
        self.assertEqual(record.value, 150.5)

    def test_from_execution(self) -> None:
        record = MetricRecord.from_execution(
            function_id="image-classify",
            metric_name="cost",
            value=0.02,
            unit="USD",
            run_id="run-456",
            producer="challenger-agent"
        )
        self.assertEqual(record.function_id, "image-classify")
        self.assertEqual(record.metric_name, "cost")
        self.assertIsNotNone(record.timestamp)

    def test_to_dict(self) -> None:
        record = MetricRecord(
            function_id="test-func",
            metric_name="quality_rating",
            value=4.2,
            unit="1-5",
            timestamp="2026-03-01T10:00:00",
            run_id="run-test",
            producer="evaluator"
        )
        d = record.to_dict()
        self.assertEqual(d["function_id"], "test-func")
        self.assertEqual(d["value"], 4.2)


class MetricsValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        pass

    def test_valid_record(self) -> None:
        validator = MetricsValidator()
        record = {
            "function_id": "bg-removal",
            "metric_name": "latency",
            "value": 100,
            "unit": "ms",
            "timestamp": "2026-03-01T12:00:00",
            "run_id": "run-1",
            "producer": "agent"
        }
        issues = validator.validate(record)
        self.assertEqual(issues, [])

    def test_missing_required_field(self) -> None:
        validator = MetricsValidator()
        record = {
            "function_id": "bg-removal",
            "metric_name": "latency",
            # missing value
            "unit": "ms",
            "timestamp": "2026-03-01T12:00:00",
            "run_id": "run-1",
            "producer": "agent"
        }
        issues = validator.validate(record)
        self.assertTrue(any("missing required field 'value'" in i for i in issues))

    def test_invalid_metric_name(self) -> None:
        validator = MetricsValidator()
        record = {
            "function_id": "bg-removal",
            "metric_name": "unknown_metric",
            "value": 100,
            "unit": "ms",
            "timestamp": "2026-03-01T12:00:00",
            "run_id": "run-1",
            "producer": "agent"
        }
        issues = validator.validate(record)
        self.assertTrue(any("not in enum" in i for i in issues))

    def test_invalid_unit(self) -> None:
        validator = MetricsValidator()
        record = {
            "function_id": "bg-removal",
            "metric_name": "latency",
            "value": 100,
            "unit": "seconds",
            "timestamp": "2026-03-01T12:00:00",
            "run_id": "run-1",
            "producer": "agent"
        }
        issues = validator.validate(record)
        self.assertTrue(any("not in enum" in i for i in issues))


class MetricsEmitterTests(unittest.TestCase):
    def test_emit_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import os
            prev_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                Path("artifacts").mkdir()

                emitter = MetricsEmitter(run_id="run-1", producer="test-agent")
                record = MetricRecord(
                    function_id="bg-removal",
                    metric_name="latency",
                    value=150.5,
                    unit="ms",
                    timestamp="2026-03-01T12:00:00",
                    run_id="run-1",
                    producer="test-agent"
                )
                path = emitter.emit(record)

                self.assertTrue(path.exists())
                content = path.read_text()
                data = json.loads(content.strip())
                self.assertEqual(data["function_id"], "bg-removal")
            finally:
                os.chdir(prev_cwd)


class GovernanceFindingTests(unittest.TestCase):
    def test_finding_to_dict(self) -> None:
        finding = GovernanceFinding(
            finding_id="test-finding",
            policy_id="FR-010",
            severity="error",
            metric_name="cost",
            message="Cost metric missing"
        )
        d = finding.to_dict()
        self.assertEqual(d["finding_id"], "test-finding")
        self.assertEqual(d["severity"], "error")


class FunctionMetricStatusTests(unittest.TestCase):
    def test_status_to_dict(self) -> None:
        status = FunctionMetricStatus(
            function_id="bg-removal",
            eligible_for_comparison=True,
            last_updated_at="2026-03-01T12:00:00",
            policy_id="FR-016",
            max_age_seconds=3600,
            findings=[],
            metrics_present={"latency": True, "cost": True}
        )
        d = status.to_dict()
        self.assertTrue(d["eligible_for_comparison"])


class MetricsGovernanceCheckerTests(unittest.TestCase):
    def test_check_missing_metrics_dir(self) -> None:
        checker = MetricsGovernanceChecker(max_age_seconds=3600)
        status = checker.check("bg-removal", metrics_dir=None)

        self.assertFalse(status.eligible_for_comparison)
        self.assertEqual(len(status.findings), 1)
        self.assertTrue(any("no_metrics_dir" in f.finding_id for f in status.findings))

    def test_check_missing_metric_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import os
            prev_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                metrics_dir = Path(tmp) / "artifacts" / "metrics"
                metrics_dir.mkdir(parents=True)

                checker = MetricsGovernanceChecker(max_age_seconds=3600)
                status = checker.check("bg-removal", metrics_dir=metrics_dir)

                self.assertFalse(status.eligible_for_comparison)
                missing_count = len([f for f in status.findings if "missing" in f.finding_id])
                self.assertEqual(missing_count, 5)
            finally:
                os.chdir(prev_cwd)

    def test_check_eligible_with_all_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import os
            prev_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                metrics_dir = Path(tmp) / "artifacts" / "metrics"
                metrics_dir.mkdir(parents=True)

                # Write all required metrics
                for metric_name, value, unit in [
                    ("latency", 150.5, "ms"),
                    ("cost", 0.02, "USD"),
                    ("success_count", 98, "count"),
                    ("failure_count", 2, "count"),
                    ("quality_rating", 4.5, "1-5")
                ]:
                    record = MetricRecord.from_execution(
                        function_id="bg-removal",
                        metric_name=metric_name,
                        value=value,
                        unit=unit,
                        run_id="run-test",
                        producer="test-agent"
                    )
                    path = Path(f"{metrics_dir}/bg-removal__{metric_name}__run-test.jsonl")
                    with path.open("w") as f:
                        f.write(json.dumps(record.to_dict()) + "\n")

                checker = MetricsGovernanceChecker(max_age_seconds=3600)
                status = checker.check("bg-removal", metrics_dir=metrics_dir)

                self.assertTrue(status.eligible_for_comparison)
                self.assertEqual(len([f for f in status.findings if "missing" in str(f.finding_id)]), 0)
            finally:
                os.chdir(prev_cwd)

    def test_check_stale_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import os
            prev_cwd = Path.cwd()
            os.chdir(tmp)
            try:
                metrics_dir = Path(tmp) / "artifacts" / "metrics"
                metrics_dir.mkdir(parents=True)

                old_timestamp = (dt.datetime.now() - dt.timedelta(hours=2)).isoformat()
                record = MetricRecord.from_execution(
                    function_id="bg-removal",
                    metric_name="latency",
                    value=150.5,
                    unit="ms",
                    run_id="run-test",
                    producer="test-agent"
                )
                record.timestamp = old_timestamp

                with (metrics_dir / "bg-removal__latency__run-test.jsonl").open("w") as f:
                    f.write(json.dumps(record.to_dict()) + "\n")

                checker = MetricsGovernanceChecker(max_age_seconds=3600)
                status = checker.check("bg-removal", metrics_dir=metrics_dir)

                self.assertFalse(status.eligible_for_comparison)
                self.assertTrue(any("stale" in f.finding_id for f in status.findings))
            finally:
                os.chdir(prev_cwd)


if __name__ == "__main__":
    unittest.main()

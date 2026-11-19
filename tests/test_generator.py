import importlib.util
import os
from pathlib import Path

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

import boto3
from moto import mock_aws

spec = importlib.util.spec_from_file_location(
    "generator_handler",
    Path(__file__).resolve().parents[1] / "src" / "generator" / "handler.py",
)
gen_handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen_handler)


def test_generate_batch_rows_produces_12_inverters():
    rows = gen_handler.generate_batch_rows(timestamp_str="2026-11-19 12:00:00", inject_faults=True)
    assert len(rows) == 12
    scenarios = {r["expected_scenario"] for r in rows}
    assert "ZERO_POWER" in scenarios
    assert "HIGH_TEMPERATURE" in scenarios


@mock_aws
def test_generator_lambda_uploads_unique_csv_to_s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("TELEMETRY_BUCKET", "solar-gen-test")

    s3 = boto3.client("s3", region_name="ap-south-1")
    s3.create_bucket(
        Bucket="solar-gen-test",
        CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
    )
    monkeypatch.setattr(gen_handler, "_s3", s3)

    result = gen_handler.handler({}, None)
    assert result["rows"] == 12
    assert result["key"].startswith("telemetry/telemetry_")
    assert result["key"].endswith(".csv")

    objects = s3.list_objects_v2(Bucket="solar-gen-test", Prefix="telemetry/")["Contents"]
    assert len(objects) == 1
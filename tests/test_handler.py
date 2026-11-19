import os
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

import boto3
from moto import mock_aws

import handler


def test_ignores_non_telemetry_keys():
    ev = {"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": "processed/x.csv"}}}]}
    assert handler.handler(ev, None) == {"processed": []}


def test_ignores_non_csv():
    ev = {"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": "telemetry/x.txt"}}}]}
    assert handler.handler(ev, None) == {"processed": []}


@mock_aws
def test_end_to_end_s3_lambda_dynamodb_idempotency_and_recovery(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("INCIDENTS_TABLE", "incidents-e2e")

    s3 = boto3.client("s3", region_name="ap-south-1")
    s3.create_bucket(
        Bucket="solar-e2e-bucket",
        CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
    )

    dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
    table = dynamodb.create_table(
        TableName="incidents-e2e",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    sns = boto3.client("sns", region_name="ap-south-1")
    topic_arn = sns.create_topic(Name="solar-e2e-alerts")["TopicArn"]
    monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)

    # Swap module-level clients to use Moto mocks cleanly
    monkeypatch.setattr(handler, "_s3", s3)
    monkeypatch.setattr(handler, "_sns", sns)
    monkeypatch.setattr(handler, "_dynamodb", dynamodb)

    header = "timestamp,site_id,inverter_id,ac_power_kw,dc_voltage_v,inverter_temp_c,ghi_w_m2,energy_kwh_interval,expected_scenario\n"
    fault_csv = header + (
        "2026-10-01 10:00:00,SITE-101,INV-01,0.1,600,45,750,0.0,ZERO_POWER\n"
        "2026-10-01 10:05:00,SITE-101,INV-01,0.2,600,46,760,0.0,ZERO_POWER\n"
    )
    s3.put_object(Bucket="solar-e2e-bucket", Key="telemetry/batch1.csv", Body=fault_csv.encode("utf-8"))

    event1 = {"Records": [{"s3": {"bucket": {"name": "solar-e2e-bucket"}, "object": {"key": "telemetry/batch1.csv"}}}]}
    res1 = handler.handler(event1, None)["processed"][0]

    assert res1["incidents"] == 2
    assert res1["normalized_incidents"] == 1
    assert res1["stored"] == 2
    assert res1["duplicates"] == 0

    # Replay the exact same S3 event -> must detect 2 duplicates and keep count at 2
    res_replay = handler.handler(event1, None)["processed"][0]
    assert res_replay["stored"] == 0
    assert res_replay["duplicates"] == 2

    items = table.scan()["Items"]
    incidents = [i for i in items if i["record_type"] == "INCIDENT"]
    assert len(incidents) == 1
    assert int(incidents[0]["occurrence_count"]) == 2
    assert incidents[0]["status"] == "NEW"

    # Upload healthy readings in batch2 -> incident must automatically close
    healthy_csv = header + (
        "2026-10-01 10:10:00,SITE-101,INV-01,78.0,610,45,750,6.5,NORMAL\n"
        "2026-10-01 10:15:00,SITE-101,INV-01,80.0,612,45,760,6.6,NORMAL\n"
    )
    s3.put_object(Bucket="solar-e2e-bucket", Key="telemetry/batch2.csv", Body=healthy_csv.encode("utf-8"))
    event2 = {"Records": [{"s3": {"bucket": {"name": "solar-e2e-bucket"}, "object": {"key": "telemetry/batch2.csv"}}}]}
    res2 = handler.handler(event2, None)["processed"][0]

    assert res2["closed"] == 1
    updated_incident = [i for i in table.scan()["Items"] if i["record_type"] == "INCIDENT"][0]
    assert updated_incident["status"] == "CLOSED"
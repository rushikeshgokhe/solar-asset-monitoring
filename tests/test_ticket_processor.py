import importlib.util
import json
import os
from pathlib import Path

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

import boto3
from moto import mock_aws

spec = importlib.util.spec_from_file_location(
    "ticket_handler",
    Path(__file__).resolve().parents[1] / "src" / "ticket_processor" / "handler.py",
)
ticket_handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ticket_handler)


SAMPLE_MSG = {
    "incident_id": "inc-999",
    "site_id": "SITE-101",
    "inverter_id": "INV-01",
    "incident_type": "ZERO_POWER",
    "severity": "HIGH",
    "first_detected": "2026-10-01 10:00:00",
    "last_detected": "2026-10-01 10:15:00",
    "occurrence_count": 4,
    "status": "OPEN",
}


@mock_aws
def test_creates_jira_ticket_once_and_skips_duplicate_sqs_delivery(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("INCIDENTS_TABLE", "incidents-jira-test")

    dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
    table = dynamodb.create_table(
        TableName="incidents-jira-test",
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
    table.put_item(
        Item={
            "pk": "SITE-101#INV-01",
            "sk": "INCIDENT#ZERO_POWER#2026-10-01 10:00:00",
            "record_type": "INCIDENT",
            "incident_id": "inc-999",
            "status": "OPEN",
        }
    )

    monkeypatch.setattr(ticket_handler, "_dynamodb", dynamodb)
    created_calls = []
    comment_calls = []

    def fake_create(inc):
        created_calls.append(inc["incident_id"])
        return "SOLAR-101"

    def fake_comment(ticket_key, inc):
        comment_calls.append((ticket_key, inc["status"]))

    monkeypatch.setattr(ticket_handler, "create_jira_issue", fake_create)
    monkeypatch.setattr(ticket_handler, "comment_jira_issue", fake_comment)

    sqs_event = {"Records": [{"body": json.dumps(SAMPLE_MSG)}]}

    # 1st SQS message -> creates Jira ticket SOLAR-101 and saves ID in DynamoDB
    res1 = ticket_handler.handler(sqs_event, None)["processed"][0]
    assert res1 == {"action": "created", "jira_ticket_id": "SOLAR-101"}
    assert len(created_calls) == 1

    # 2nd duplicate SQS delivery -> sees jira_ticket_id in DynamoDB and skips creation!
    res2 = ticket_handler.handler(sqs_event, None)["processed"][0]
    assert res2 == {"action": "duplicate_skipped", "jira_ticket_id": "SOLAR-101"}
    assert len(created_calls) == 1

    # 3rd message when incident closes -> adds recovery comment to existing Jira ticket
    closed_msg = {**SAMPLE_MSG, "status": "CLOSED"}
    res3 = ticket_handler.handler({"Records": [{"body": json.dumps(closed_msg)}]}, None)["processed"][0]
    assert res3 == {"action": "updated_closed", "jira_ticket_id": "SOLAR-101"}
    assert comment_calls == [("SOLAR-101", "CLOSED")]
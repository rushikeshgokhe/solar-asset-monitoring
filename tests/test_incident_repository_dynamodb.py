import boto3
import pytest
from moto import mock_aws

from incident_repository import (
    evaluate_and_persist_recovery,
    find_active_incident,
    persist_correlated_batch,
    store_event_and_update_incident,
    update_incident_status,
)


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        dynamodb.create_table(
            TableName="incidents-test",
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
        yield dynamodb.Table("incidents-test")


INCIDENT = {
    "incident_id": "abc123",
    "site_id": "SITE-104",
    "inverter_id": "INV-03",
    "incident_type": "ZERO_POWER",
    "severity": "HIGH",
    "first_detected": "2026-10-01 11:00:00",
    "last_detected": "2026-10-01 11:10:00",
    "occurrence_count": 3,
    "status": "NEW",
}


def make_event(timestamp, site_id="SITE-104", inverter_id="INV-03", incident_type="ZERO_POWER"):
    return {
        "timestamp": timestamp,
        "site_id": site_id,
        "inverter_id": inverter_id,
        "incident_type": incident_type,
        "severity": "HIGH",
        "detail": "test",
    }


def items_of_type(table, record_type):
    return [
        item for item in table.scan()["Items"]
        if item["record_type"] == record_type
    ]


def test_new_event_is_stored_and_counted(table):
    stored = store_event_and_update_incident(
        table, make_event("2026-10-01 11:00:00"), INCIDENT, "telemetry/a.csv"
    )
    assert stored is True
    assert len(items_of_type(table, "EVENT")) == 1
    incidents = items_of_type(table, "INCIDENT")
    assert len(incidents) == 1
    assert int(incidents[0]["occurrence_count"]) == 1


def test_duplicate_event_does_not_increase_count(table):
    event = make_event("2026-10-01 11:00:00")
    assert store_event_and_update_incident(table, event, INCIDENT, "telemetry/a.csv") is True
    assert store_event_and_update_incident(table, event, INCIDENT, "telemetry/a.csv") is False
    incidents = items_of_type(table, "INCIDENT")
    assert int(incidents[0]["occurrence_count"]) == 1


def test_replaying_a_whole_batch_changes_nothing(table):
    timestamps = [
        "2026-10-01 11:00:00",
        "2026-10-01 11:05:00",
        "2026-10-01 11:10:00",
    ]
    first_pass = [
        store_event_and_update_incident(table, make_event(t), INCIDENT, "telemetry/a.csv")
        for t in timestamps
    ]
    second_pass = [
        store_event_and_update_incident(table, make_event(t), INCIDENT, "telemetry/a.csv")
        for t in timestamps
    ]
    assert first_pass == [True, True, True]
    assert second_pass == [False, False, False]
    assert len(items_of_type(table, "EVENT")) == 3
    assert int(items_of_type(table, "INCIDENT")[0]["occurrence_count"]) == 3


def test_out_of_order_event_does_not_move_last_detected_backwards(table):
    assert store_event_and_update_incident(
        table, make_event("2026-10-01 11:10:00"), INCIDENT, "telemetry/b.csv"
    ) is True
    assert store_event_and_update_incident(
        table, make_event("2026-10-01 11:05:00"), INCIDENT, "telemetry/a.csv"
    ) is True

    incident = items_of_type(table, "INCIDENT")[0]
    assert incident["last_detected"] == "2026-10-01 11:10:00"
    assert int(incident["occurrence_count"]) == 2


def test_cross_batch_correlation_reuses_active_incident(table):
    batch_1 = [make_event("2026-10-01 10:00:00")]
    batch_2 = [make_event("2026-10-01 10:05:00"), make_event("2026-10-01 10:10:00")]

    res1 = persist_correlated_batch(table, batch_1, "telemetry/b1.csv")
    res2 = persist_correlated_batch(table, batch_2, "telemetry/b2.csv")

    assert res1["stored_events"] == 1
    assert res2["stored_events"] == 2

    incidents = items_of_type(table, "INCIDENT")
    assert len(incidents) == 1
    assert int(incidents[0]["occurrence_count"]) == 3
    assert incidents[0]["first_detected"] == "2026-10-01 10:00:00"
    assert incidents[0]["last_detected"] == "2026-10-01 10:10:00"
    assert incidents[0]["status"] == "OPEN"


def test_lifecycle_recovery_closure_and_new_episode_on_reoccurrence(table):
    persist_correlated_batch(
        table,
        [make_event("2026-10-01 10:00:00")],
        "telemetry/b1.csv",
    )
    active = find_active_incident(table, "SITE-104", "INV-03", "ZERO_POWER")
    assert active is not None

    # 1 healthy reading -> RECOVERY_DETECTED
    one_healthy = [
        {
            "timestamp": "2026-10-01 10:05:00",
            "site_id": "SITE-104",
            "inverter_id": "INV-03",
            "ghi_w_m2": 600.0,
            "ac_power_kw": 75.0,
            "inverter_temp_c": 45.0,
        }
    ]
    recovering = evaluate_and_persist_recovery(table, active, one_healthy, required_readings=2)
    assert recovering["status"] == "RECOVERY_DETECTED"

    # 2 consecutive healthy readings -> CLOSED
    two_healthy = one_healthy + [
        {
            "timestamp": "2026-10-01 10:10:00",
            "site_id": "SITE-104",
            "inverter_id": "INV-03",
            "ghi_w_m2": 650.0,
            "ac_power_kw": 80.0,
            "inverter_temp_c": 46.0,
        }
    ]
    closed = evaluate_and_persist_recovery(table, recovering, two_healthy, required_readings=2)
    assert closed["status"] == "CLOSED"
    assert find_active_incident(table, "SITE-104", "INV-03", "ZERO_POWER") is None

    # Fault returns after closure -> brand-new incident episode
    persist_correlated_batch(
        table,
        [make_event("2026-10-01 12:00:00")],
        "telemetry/b3.csv",
    )
    all_incidents = sorted(items_of_type(table, "INCIDENT"), key=lambda x: x["first_detected"])
    assert len(all_incidents) == 2
    assert all_incidents[0]["status"] == "CLOSED"
    assert all_incidents[1]["status"] == "NEW"
    assert all_incidents[0]["incident_id"] != all_incidents[1]["incident_id"]

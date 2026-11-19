from src.processor.incident_repository import build_event_item
import pytest

from src.processor.incident_repository import build_incident_item


def make_incident():
    return {
        "incident_id": "abc123456789",
        "site_id": "SITE-104",
        "inverter_id": "INV-03",
        "incident_type": "ZERO_POWER",
        "severity": "HIGH",
        "first_detected": "2026-10-01 11:00:00",
        "last_detected": "2026-10-01 11:55:00",
        "occurrence_count": 12,
        "source": "telemetry_rules",
        "status": "NEW",
    }


def test_build_incident_item():
    item = build_incident_item(make_incident())

    assert item["pk"] == "SITE-104#INV-03"
    assert item["record_type"] == "INCIDENT"
    assert item["occurrence_count"] == 12


def test_incident_sort_key_contains_episode_start():
    item = build_incident_item(make_incident())

    assert item["sk"] == (
        "INCIDENT#ZERO_POWER#2026-10-01 11:00:00"
    )


def test_missing_required_field():
    incident = make_incident()
    del incident["severity"]

    with pytest.raises(ValueError):
        build_incident_item(incident)


def test_invalid_occurrence_count():
    incident = make_incident()
    incident["occurrence_count"] = 0

    with pytest.raises(ValueError):
        build_incident_item(incident)


def test_invalid_timestamp_order():
    incident = make_incident()
    incident["last_detected"] = "2026-10-01 10:00:00"

    with pytest.raises(ValueError):
        build_incident_item(incident)
def make_event():
    return {
        "timestamp": "2026-10-01 11:00:00",
        "site_id": "SITE-104",
        "inverter_id": "INV-03",
        "incident_type": "ZERO_POWER",
        "severity": "HIGH",
        "detail": "ghi=500 W/m2, ac_power=0.0 kW",
    }


def test_build_event_item():
    item = build_event_item(
        make_event(),
        "telemetry/batch1.csv",
    )

    assert item["pk"] == "SITE-104#INV-03"
    assert item["sk"] == "2026-10-01 11:00:00#ZERO_POWER"
    assert item["record_type"] == "EVENT"
    assert item["source_key"] == "telemetry/batch1.csv"


def test_event_item_rejects_missing_field():
    event = make_event()
    del event["severity"]

    with pytest.raises(ValueError):
        build_event_item(event, "telemetry/batch1.csv")

from src.processor.incident_repository import find_active_incident


class FakeQueryTable:
    def __init__(self, items):
        self.items = items
        self.query_arguments = None

    def query(self, **kwargs):
        self.query_arguments = kwargs
        return {"Items": self.items}


def test_find_active_incident_returns_latest_open_incident():
    existing = {
        "pk": "SITE-104#INV-03",
        "sk": "INCIDENT#ZERO_POWER#2026-10-01 11:00:00",
        "incident_id": "abc123",
        "status": "OPEN",
    }

    table = FakeQueryTable([existing])

    result = find_active_incident(
        table, "SITE-104", "INV-03", "ZERO_POWER"
    )

    assert result["incident_id"] == "abc123"
    assert table.query_arguments["ScanIndexForward"] is False
    assert table.query_arguments["Limit"] == 1


def test_find_active_incident_does_not_reuse_resolved_incident():
    existing = {
        "pk": "SITE-104#INV-03",
        "sk": "INCIDENT#ZERO_POWER#2026-10-01 11:00:00",
        "incident_id": "abc123",
        "status": "RESOLVED",
    }

    table = FakeQueryTable([existing])

    result = find_active_incident(
        table, "SITE-104", "INV-03", "ZERO_POWER"
    )

    assert result is None


def test_find_active_incident_returns_none_when_no_incident_exists():
    table = FakeQueryTable([])

    result = find_active_incident(
        table, "SITE-104", "INV-03", "ZERO_POWER"
    )

    assert result is None

from src.processor.incident_repository import reuse_incident_identity


def test_reuse_incident_identity_preserves_existing_id_and_start():
    new_incident = make_incident()
    new_incident["incident_id"] = "new123"
    new_incident["first_detected"] = "2026-10-01 12:00:00"
    new_incident["status"] = "NEW"

    existing = {
        "incident_id": "original123",
        "first_detected": "2026-10-01 11:00:00",
        "status": "OPEN",
    }

    result = reuse_incident_identity(new_incident, existing)

    assert result["incident_id"] == "original123"
    assert result["first_detected"] == "2026-10-01 11:00:00"
    assert result["status"] == "OPEN"


def test_reuse_incident_identity_does_not_modify_original():
    incident = make_incident()
    existing = {
        "incident_id": "original123",
        "first_detected": "2026-10-01 10:00:00",
        "status": "RECOVERY_DETECTED",
    }

    result = reuse_incident_identity(incident, existing)

    assert incident["incident_id"] == "abc123456789"
    assert result["incident_id"] == "original123"


def test_new_incident_keeps_its_own_identity():
    incident = make_incident()

    result = reuse_incident_identity(incident, None)

    assert result["incident_id"] == incident["incident_id"]
    assert result["first_detected"] == incident["first_detected"]

def test_build_event_item_links_to_incident_id():
    item = build_event_item(
        make_event(),
        "telemetry/batch1.csv",
        incident_id="original123",
    )

    assert item["incident_id"] == "original123"

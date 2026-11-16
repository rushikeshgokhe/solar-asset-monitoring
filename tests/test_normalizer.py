from src.processor.normalizer import normalize_incidents


def make_alert(timestamp, site="SITE-101", inverter="INV-01",
               incident_type="ZERO_POWER", severity="HIGH"):
    return {
        "timestamp": timestamp,
        "site_id": site,
        "inverter_id": inverter,
        "incident_type": incident_type,
        "severity": severity,
        "detail": "Test alert",
    }


def test_repeated_alerts_are_grouped():
    alerts = [
        make_alert("2026-10-01 11:00:00"),
        make_alert("2026-10-01 11:05:00"),
        make_alert("2026-10-01 11:10:00"),
    ]
    result = normalize_incidents(alerts)
    assert len(result) == 1
    assert result[0]["occurrence_count"] == 3


def test_alerts_outside_window_are_separated():
    alerts = [
        make_alert("2026-10-01 11:00:00"),
        make_alert("2026-10-01 11:20:00"),
    ]
    result = normalize_incidents(alerts)
    assert len(result) == 2


def test_different_inverters_are_not_grouped():
    alerts = [
        make_alert("2026-10-01 11:00:00", inverter="INV-01"),
        make_alert("2026-10-01 11:05:00", inverter="INV-02"),
    ]
    result = normalize_incidents(alerts)
    assert len(result) == 2


def test_different_incident_types_are_not_grouped():
    alerts = [
        make_alert("2026-10-01 11:00:00", incident_type="ZERO_POWER"),
        make_alert("2026-10-01 11:05:00", incident_type="HIGH_TEMPERATURE"),
    ]
    result = normalize_incidents(alerts)
    assert len(result) == 2


def test_highest_severity_is_preserved():
    alerts = [
        make_alert("2026-10-01 11:00:00", severity="MEDIUM"),
        make_alert("2026-10-01 11:05:00", severity="CRITICAL"),
    ]
    result = normalize_incidents(alerts)
    assert len(result) == 1
    assert result[0]["severity"] == "CRITICAL"

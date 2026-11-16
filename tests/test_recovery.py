from datetime import datetime

import pytest

from src.processor.recovery import (
    is_recovered,
    count_consecutive_healthy_readings,
    recovery_confirmed,
)


def make_row(timestamp, kw=50.0, temp=40.0, ghi=500.0):
    return {
        "timestamp": datetime.fromisoformat(timestamp),
        "ac_power_kw": kw,
        "inverter_temp_c": temp,
        "ghi_w_m2": ghi,
    }


def test_zero_power_recovery():
    row = make_row("2026-10-01 11:00:00", kw=10, ghi=500)
    assert is_recovered("ZERO_POWER", row)


def test_zero_power_not_recovered():
    row = make_row("2026-10-01 11:00:00", kw=0, ghi=500)
    assert not is_recovered("ZERO_POWER", row)


def test_high_temperature_recovery():
    row = make_row("2026-10-01 11:00:00", temp=65)
    assert is_recovered("HIGH_TEMPERATURE", row)


def test_high_temperature_not_recovered():
    row = make_row("2026-10-01 11:00:00", temp=85)
    assert not is_recovered("HIGH_TEMPERATURE", row)


def test_missing_telemetry_recovery():
    row = make_row("2026-10-01 11:00:00")
    assert is_recovered("MISSING_TELEMETRY", row)


def test_two_healthy_readings_confirm_recovery():
    rows = [
        make_row("2026-10-01 11:05:00", kw=50),
        make_row("2026-10-01 11:10:00", kw=55),
    ]

    assert recovery_confirmed("ZERO_POWER", rows)


def test_one_healthy_reading_does_not_confirm_recovery():
    rows = [
        make_row("2026-10-01 11:05:00", kw=50),
    ]

    assert not recovery_confirmed("ZERO_POWER", rows)


def test_unhealthy_latest_reading_breaks_sequence():
    rows = [
        make_row("2026-10-01 11:00:00", kw=50),
        make_row("2026-10-01 11:05:00", kw=0),
    ]

    assert count_consecutive_healthy_readings(
        "ZERO_POWER", rows
    ) == 0


def test_invalid_required_readings():
    rows = [
        make_row("2026-10-01 11:05:00"),
    ]

    with pytest.raises(ValueError):
        recovery_confirmed(
            "ZERO_POWER",
            rows,
            required_readings=0,
        )
from src.processor.recovery import evaluate_incident_recovery


def make_incident():
    return {
        "site_id": "SITE-101",
        "inverter_id": "INV-01",
        "incident_type": "ZERO_POWER",
        "last_detected": "2026-10-01 11:00:00",
    }


def test_recovery_uses_only_matching_inverter():
    incident = make_incident()

    rows = [
        {
            **make_row("2026-10-01 11:05:00", kw=50),
            "site_id": "SITE-101",
            "inverter_id": "INV-02",
        },
        {
            **make_row("2026-10-01 11:10:00", kw=50),
            "site_id": "SITE-101",
            "inverter_id": "INV-02",
        },
    ]

    assert not evaluate_incident_recovery(incident, rows)


def test_old_healthy_readings_do_not_confirm_recovery():
    incident = make_incident()

    rows = [
        {
            **make_row("2026-10-01 10:50:00", kw=50),
            "site_id": "SITE-101",
            "inverter_id": "INV-01",
        },
        {
            **make_row("2026-10-01 10:55:00", kw=50),
            "site_id": "SITE-101",
            "inverter_id": "INV-01",
        },
    ]

    assert not evaluate_incident_recovery(incident, rows)


def test_matching_healthy_readings_confirm_recovery():
    incident = make_incident()

    rows = [
        {
            **make_row("2026-10-01 11:05:00", kw=50),
            "site_id": "SITE-101",
            "inverter_id": "INV-01",
        },
        {
            **make_row("2026-10-01 11:10:00", kw=55),
            "site_id": "SITE-101",
            "inverter_id": "INV-01",
        },
    ]

    assert evaluate_incident_recovery(incident, rows)
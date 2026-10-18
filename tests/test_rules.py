from datetime import datetime

import rules


def row(ts="2026-01-01 10:00:00", site="S1", inv="I1", kw=50.0, temp=40.0, ghi=500.0):
    return {"timestamp": datetime.fromisoformat(ts), "site_id": site, "inverter_id": inv,
            "ac_power_kw": kw, "inverter_temp_c": temp, "ghi_w_m2": ghi}


# ---- ZERO_POWER ----
def test_zero_power_detected():
    assert len(rules.zero_power([row(ghi=300, kw=0.0)])) == 1

def test_zero_power_boundary_inclusive():
    assert len(rules.zero_power([row(ghi=200, kw=1.0)])) == 1

def test_zero_power_low_irradiance_ignored():
    assert rules.zero_power([row(ghi=199.9, kw=0.0)]) == []

def test_zero_power_producing_ignored():
    assert rules.zero_power([row(ghi=800, kw=1.1)]) == []


# ---- HIGH_TEMPERATURE ----
def test_high_temp_boundary_inclusive():
    assert len(rules.high_temperature([row(temp=80.0)])) == 1

def test_high_temp_below_threshold():
    assert rules.high_temperature([row(temp=79.9)]) == []

def test_high_temp_severity():
    assert rules.high_temperature([row(temp=90)])[0]["severity"] == "HIGH"


# ---- MISSING_TELEMETRY ----
def test_gap_over_five_minutes_detected():
    rows = [row("2026-01-01 10:00:00"), row("2026-01-01 10:05:01")]
    out = rules.missing_telemetry(rows)
    assert len(out) == 1 and out[0]["severity"] == "MEDIUM"

def test_gap_exactly_five_minutes_ok():
    rows = [row("2026-01-01 10:00:00"), row("2026-01-01 10:05:00")]
    assert rules.missing_telemetry(rows) == []

def test_gap_checked_per_inverter():
    rows = [row("2026-01-01 10:00:00", inv="I1"), row("2026-01-01 10:30:00", inv="I2")]
    assert rules.missing_telemetry(rows) == []

def test_gap_handles_unsorted_input():
    rows = [row("2026-01-01 10:10:00"), row("2026-01-01 10:00:00")]
    assert len(rules.missing_telemetry(rows)) == 1


# ---- parsing ----
CSV = (
    "timestamp,site_id,inverter_id,ac_power_kw,dc_voltage_v,inverter_temp_c,ghi_w_m2\n"
    "2026-01-01 10:00:00,S1,I1,50,600,40,500\n"
    "not-a-date,S1,I1,50,600,40,500\n"
    "2026-01-01 10:05:00,S1,I1,abc,600,40,500\n"
)

def test_parse_skips_malformed_rows():
    rows, skipped = rules.parse_rows(CSV)
    assert len(rows) == 1 and skipped == 2


# ---- end to end ----
def test_detect_all_and_csv_output():
    rows = [row(ghi=300, kw=0, temp=85)]
    inc = rules.detect_all(rows)
    assert {i["incident_type"] for i in inc} == {"ZERO_POWER", "HIGH_TEMPERATURE"}
    text = rules.incidents_to_csv(inc)
    assert text.splitlines()[0] == ",".join(rules.INCIDENT_FIELDS)

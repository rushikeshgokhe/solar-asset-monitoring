"""Pure anomaly-detection rules. No AWS imports, so they are easy to test."""
import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta

ZERO_POWER_MIN_GHI = 200.0   # W/m2
ZERO_POWER_MAX_KW = 1.0      # kW
HIGH_TEMP_C = 80.0           # deg C
MAX_GAP = timedelta(minutes=5)

INCIDENT_FIELDS = ["timestamp", "site_id", "inverter_id", "incident_type", "severity", "detail"]


def parse_rows(csv_text):
    """Parse CSV text -> (valid_rows, skipped_count). Malformed rows are skipped."""
    rows, skipped = [], 0
    for raw in csv.DictReader(io.StringIO(csv_text)):
        try:
            rows.append({
                "timestamp": datetime.fromisoformat(raw["timestamp"].strip()),
                "site_id": raw["site_id"].strip(),
                "inverter_id": raw["inverter_id"].strip(),
                "ac_power_kw": float(raw["ac_power_kw"]),
                "inverter_temp_c": float(raw["inverter_temp_c"]),
                "ghi_w_m2": float(raw["ghi_w_m2"]),
            })
        except (KeyError, ValueError, AttributeError):
            skipped += 1
    return rows, skipped


def _incident(row, itype, severity, detail):
    return {
        "timestamp": row["timestamp"].isoformat(sep=" "),
        "site_id": row["site_id"],
        "inverter_id": row["inverter_id"],
        "incident_type": itype,
        "severity": severity,
        "detail": detail,
    }


def zero_power(rows):
    return [
        _incident(r, "ZERO_POWER", "HIGH",
                  f"ghi={r['ghi_w_m2']} W/m2, ac_power={r['ac_power_kw']} kW")
        for r in rows
        if r["ghi_w_m2"] >= ZERO_POWER_MIN_GHI and r["ac_power_kw"] <= ZERO_POWER_MAX_KW
    ]


def high_temperature(rows):
    return [
        _incident(r, "HIGH_TEMPERATURE", "HIGH", f"temp={r['inverter_temp_c']} C")
        for r in rows
        if r["inverter_temp_c"] >= HIGH_TEMP_C
    ]


def missing_telemetry(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[(r["site_id"], r["inverter_id"])].append(r)
    out = []
    for series in groups.values():
        series.sort(key=lambda r: r["timestamp"])
        for prev, cur in zip(series, series[1:]):
            gap = cur["timestamp"] - prev["timestamp"]
            if gap > MAX_GAP:
                out.append(_incident(cur, "MISSING_TELEMETRY", "MEDIUM",
                                     f"gap={int(gap.total_seconds() // 60)} min"))
    return out


def detect_all(rows):
    incidents = zero_power(rows) + high_temperature(rows) + missing_telemetry(rows)
    return sorted(incidents, key=lambda i: (i["timestamp"], i["site_id"], i["inverter_id"]))


def incidents_to_csv(incidents):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=INCIDENT_FIELDS)
    w.writeheader()
    w.writerows(incidents)
    return buf.getvalue()


def summarize(total_rows, skipped, incidents):
    counts = defaultdict(int)
    for i in incidents:
        counts[i["incident_type"]] += 1
    lines = [f"Rows processed: {total_rows}", f"Rows skipped: {skipped}",
             f"Anomaly records: {len(incidents)}"]
    lines += [f"  {k}: {v}" for k, v in sorted(counts.items())]
    return "\n".join(lines)

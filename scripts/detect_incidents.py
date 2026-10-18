
import csv
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_DIR / "data" / "solar_telemetry.csv"
INCIDENT_FILE = PROJECT_DIR / "reports" / "incident_register.csv"

ZERO_POWER_THRESHOLD_KW = 1.0
HIGH_TEMPERATURE_THRESHOLD_C = 80.0
MIN_IRRADIANCE_W_M2 = 200.0
EXPECTED_INTERVAL_MINUTES = 5

if not DATA_FILE.exists():
    raise FileNotFoundError(
        f"Telemetry file not found: {DATA_FILE}. "
        "Run generate_data.py first."
    )

# Read telemetry
with DATA_FILE.open(newline="", encoding="utf-8") as file:
    reader = csv.DictReader(file)
    readings = list(reader)

# Organize readings by inverter
by_inverter = defaultdict(list)

for row in readings:
    row["timestamp_parsed"] = datetime.strptime(
        row["timestamp"], "%Y-%m-%d %H:%M:%S"
    )
    by_inverter[
        (row["site_id"], row["inverter_id"])
    ].append(row)

incidents = []
seen_incidents = set()


def add_incident(site, inverter, timestamp, incident_type,
                 severity, description):
    """Create one incident per asset, timestamp and type."""
    key = (site, inverter, timestamp, incident_type)

    if key in seen_incidents:
        return

    seen_incidents.add(key)

    incidents.append({
        "incident_id": f"INC-{len(incidents) + 1:04d}",
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "site_id": site,
        "inverter_id": inverter,
        "incident_type": incident_type,
        "severity": severity,
        "description": description,
        "status": "OPEN",
    })


for (site, inverter), asset_rows in by_inverter.items():
    asset_rows.sort(key=lambda r: r["timestamp_parsed"])

    # Detect suspicious power and temperature readings
    for row in asset_rows:
        timestamp = row["timestamp_parsed"]
        power = float(row["ac_power_kw"])
        ghi = float(row["ghi_w_m2"])
        temperature = float(row["inverter_temp_c"])

        if (
            ghi >= MIN_IRRADIANCE_W_M2
            and power <= ZERO_POWER_THRESHOLD_KW
        ):
            add_incident(
                site, inverter, timestamp,
                "ZERO_POWER_ANOMALY", "HIGH",
                f"AC power is {power} kW while "
                f"irradiance is {ghi} W/m2."
            )

        if temperature >= HIGH_TEMPERATURE_THRESHOLD_C:
            add_incident(
                site, inverter, timestamp,
                "HIGH_TEMPERATURE", "HIGH",
                f"Inverter temperature is {temperature} C."
            )

    # Detect missing five-minute telemetry intervals
    for previous, current in zip(
        asset_rows, asset_rows[1:]
    ):
        previous_time = previous["timestamp_parsed"]
        current_time = current["timestamp_parsed"]

        elapsed = current_time - previous_time

        if elapsed > timedelta(
            minutes=EXPECTED_INTERVAL_MINUTES
        ):
            missing_count = (
                int(elapsed.total_seconds() // 60)
                // EXPECTED_INTERVAL_MINUTES
            ) - 1

            if missing_count > 0:
                first_missing = previous_time + timedelta(
                    minutes=EXPECTED_INTERVAL_MINUTES
                )

                add_incident(
                    site, inverter, first_missing,
                    "MISSING_TELEMETRY", "MEDIUM",
                    f"{missing_count} expected reading(s) "
                    f"missing between consecutive records."
                )

# Export incident register
INCIDENT_FILE.parent.mkdir(parents=True, exist_ok=True)

fieldnames = [
    "incident_id",
    "timestamp",
    "site_id",
    "inverter_id",
    "incident_type",
    "severity",
    "description",
    "status",
]

with INCIDENT_FILE.open(
    "w", newline="", encoding="utf-8"
) as file:
    writer = csv.DictWriter(file, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(incidents)

print("Incident detection completed.")
print(f"Telemetry readings processed: {len(readings)}")
print(f"Incidents generated: {len(incidents)}")
print(f"Incident register: {INCIDENT_FILE}")

for incident_type in sorted({
    incident["incident_type"] for incident in incidents
}):
    count = sum(
        incident["incident_type"] == incident_type
        for incident in incidents
    )
    print(f"{incident_type}: {count}")

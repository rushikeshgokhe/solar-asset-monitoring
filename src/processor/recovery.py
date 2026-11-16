"""
Recovery detection for solar monitoring incidents.
"""
from datetime import datetime
ZERO_POWER_MIN_GHI = 200.0
ZERO_POWER_MIN_KW = 1.0
HIGH_TEMP_C = 80.0


def is_recovered(incident_type, row):
    """
    Check whether a telemetry reading provides recovery evidence.
    """

    if incident_type == "ZERO_POWER":
        return (
            row["ghi_w_m2"] >= ZERO_POWER_MIN_GHI
            and row["ac_power_kw"] > ZERO_POWER_MIN_KW
        )

    if incident_type == "HIGH_TEMPERATURE":
        return row["inverter_temp_c"] < HIGH_TEMP_C

    if incident_type == "MISSING_TELEMETRY":
        return True

    return False


def count_consecutive_healthy_readings(incident_type, rows):
    """
    Count consecutive healthy readings from the latest telemetry.
    """

    ordered_rows = sorted(
        rows,
        key=lambda row: row["timestamp"],
        reverse=True,
    )

    count = 0

    for row in ordered_rows:
        if is_recovered(incident_type, row):
            count += 1
        else:
            break

    return count


def recovery_confirmed(incident_type, rows, required_readings=2):
    """
    Require consecutive healthy readings before confirming recovery.
    """

    if required_readings < 1:
        raise ValueError("required_readings must be at least 1")

    healthy_count = count_consecutive_healthy_readings(
        incident_type,
        rows,
    )

    return healthy_count >= required_readings
def evaluate_incident_recovery(
    incident,
    rows,
    required_readings=2,
):
    """
    Evaluate recovery using only telemetry belonging to this incident's
    inverter and recorded at or after its latest detection.
    """

    required_fields = [
        "site_id",
        "inverter_id",
        "incident_type",
        "last_detected",
    ]

    for field in required_fields:
        if field not in incident:
            raise ValueError(f"Missing incident field: {field}")

    last_detected = incident["last_detected"]

    if isinstance(last_detected, str):
        last_detected = datetime.fromisoformat(last_detected)

    matching_rows = []

    for row in rows:
        if row["site_id"] != incident["site_id"]:
            continue

        if row["inverter_id"] != incident["inverter_id"]:
            continue

        timestamp = row["timestamp"]

        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        if timestamp >= last_detected:
            matching_rows.append({
                **row,
                "timestamp": timestamp,
            })

    return recovery_confirmed(
        incident["incident_type"],
        matching_rows,
        required_readings,
    )
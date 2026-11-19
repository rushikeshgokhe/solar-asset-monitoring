

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta


def normalize_incidents(incidents, correlation_window_minutes=15):
    """
    Group related alerts into normalized incidents.

    Matching criteria:
    - Same site
    - Same inverter
    - Same incident type
    - Consecutive alerts within the correlation window
    """

    grouped = defaultdict(list)

    for incident in incidents:
        key = (
            incident["site_id"],
            incident["inverter_id"],
            incident["incident_type"],
        )
        grouped[key].append(incident)

    normalized = []

    for key, alerts in grouped.items():
        alerts.sort(
            key=lambda item: datetime.fromisoformat(item["timestamp"])
        )

        current_group = []

        for alert in alerts:
            alert_time = datetime.fromisoformat(alert["timestamp"])

            if current_group:
                previous_time = datetime.fromisoformat(
                    current_group[-1]["timestamp"]
                )

                time_gap = alert_time - previous_time

                if time_gap > timedelta(minutes=correlation_window_minutes):
                    normalized.append(
                        _build_normalized_incident(key, current_group)
                    )
                    current_group = []

            current_group.append(alert)

        if current_group:
            normalized.append(
                _build_normalized_incident(key, current_group)
            )

    normalized.sort(key=lambda item: item["first_detected"])

    return normalized


def _build_normalized_incident(key, alerts):
    site_id, inverter_id, incident_type = key

    first_detected = alerts[0]["timestamp"]
    last_detected = alerts[-1]["timestamp"]

    identity = (
        f"{site_id}|{inverter_id}|{incident_type}|{first_detected}"
    )

    incident_id = hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()[:16]

    severity_rank = {
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "CRITICAL": 4,
    }

    severity = max(
        (alert["severity"] for alert in alerts),
        key=lambda value: severity_rank.get(value.upper(), 0),
    )

    return {
        "incident_id": incident_id,
        "site_id": site_id,
        "inverter_id": inverter_id,
        "incident_type": incident_type,
        "severity": severity,
        "first_detected": first_detected,
        "last_detected": last_detected,
        "occurrence_count": len(alerts),
        "source": "telemetry_rules",
        "status": "NEW",
        "details": [alert["detail"] for alert in alerts],
    }

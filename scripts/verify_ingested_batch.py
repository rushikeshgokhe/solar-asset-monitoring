
import sys
from pathlib import Path
from collections import Counter

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from src.processor import rules
from src.processor.normalizer import normalize_incidents

INPUT_DIR = PROJECT_DIR / "data" / "incoming"


def main():
    files = sorted(INPUT_DIR.glob("telemetry_*.csv"))

    if not files:
        raise FileNotFoundError("No ingested telemetry CSV found.")

    input_file = files[-1]

    print(f"Processing file: {input_file.name}")

    with input_file.open("r", newline="", encoding="utf-8") as file:
        csv_text = file.read()

    valid_rows, skipped_count = rules.parse_rows(csv_text)
    incidents = rules.detect_all(valid_rows)

    normalized_incidents = normalize_incidents(incidents)

    # Calculate raw incident distribution
    incident_counts = Counter(
        incident["incident_type"] for incident in incidents
    )

    print("\n--- Processing Results ---")
    print(f"Total valid telemetry records: {len(valid_rows)}")
    print(f"Skipped records: {skipped_count}")
    print(f"Detected incidents: {len(incidents)}")

    print("\n--- Incident Breakdown ---")

    for incident_type, count in sorted(incident_counts.items()):
        print(f"{incident_type}: {count}")

    print("\n--- Normalized Incident Results ---")
    print(f"Raw alerts: {len(incidents)}")
    print(f"Normalized incidents: {len(normalized_incidents)}")

    for incident in normalized_incidents:
        print(
            incident["incident_type"],
            incident["site_id"],
            incident["inverter_id"],
            "Occurrences:", incident["occurrence_count"],
            "Severity:", incident["severity"],
        )

    print("\n--- Sample Raw Incidents ---")

    for incident in incidents[:5]:
        print(incident)


if __name__ == "__main__":
    main()

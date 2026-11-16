
import csv
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests


PROJECT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_DIR / "data" / "incoming"

API_BASE_URL = "http://127.0.0.1:8000"
PAGE_SIZE = 500
REQUEST_TIMEOUT = 15

REQUIRED_FIELDS = {
    "timestamp",
    "site_id",
    "inverter_id",
    "ac_power_kw",
    "dc_voltage_v",
    "inverter_temp_c",
    "ghi_w_m2",
    "energy_kwh_interval",
    "expected_scenario",
}

CSV_FIELDS = [
    "timestamp",
    "site_id",
    "inverter_id",
    "ac_power_kw",
    "dc_voltage_v",
    "inverter_temp_c",
    "ghi_w_m2",
    "energy_kwh_interval",
    "expected_scenario",
]


def validate_record(record):
    """Validate one telemetry record returned by the API."""

    missing = REQUIRED_FIELDS - record.keys()

    if missing:
        raise ValueError(f"Missing fields: {sorted(missing)}")

    datetime.strptime(
        record["timestamp"], "%Y-%m-%d %H:%M:%S"
    )

    if not record["site_id"] or not record["inverter_id"]:
        raise ValueError("Site ID and inverter ID cannot be empty")

    numeric_fields = [
        "ac_power_kw",
        "dc_voltage_v",
        "inverter_temp_c",
        "ghi_w_m2",
        "energy_kwh_interval",
    ]

    for field in numeric_fields:
        value = float(record[field])

        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid numeric value in {field}")

    return True


def fetch_page(session, offset):
    """Retrieve one page of telemetry from the API."""

    response = session.get(
        f"{API_BASE_URL}/telemetry",
        params={
            "limit": PAGE_SIZE,
            "offset": offset,
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload.get("data"), list):
        raise ValueError("API returned an invalid data response")

    return payload


def fetch_all_telemetry():
    """Fetch all telemetry records using pagination."""

    all_records = []
    offset = 0
    expected_total = None

    with requests.Session() as session:
        while True:
            payload = fetch_page(session, offset)

            total = payload.get("total_records")
            records = payload["data"]

            if not isinstance(total, int) or total < 0:
                raise ValueError("Invalid total_records in API response")

            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise ValueError("Dataset size changed during ingestion")

            if len(records) > PAGE_SIZE:
                raise ValueError("API returned more records than requested")

            for record in records:
                validate_record(record)

            all_records.extend(records)

            print(
                f"Retrieved {len(all_records)} "
                f"of {expected_total} records"
            )

            offset += len(records)

            if len(all_records) >= expected_total:
                break

            if not records:
                raise ValueError("API returned an incomplete dataset")

    return all_records


def save_batch(records):
    """Save validated telemetry records as a unique CSV batch."""

    if not records:
        raise ValueError("No telemetry records received")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    batch_id = uuid.uuid4().hex[:8]

    output_file = (
        OUTPUT_DIR / f"telemetry_{timestamp}_{batch_id}.csv"
    )

    with output_file.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_FIELDS,
        )
        writer.writeheader()
        writer.writerows(records)

    return output_file


def run_ingestion():
    """Execute the complete telemetry ingestion workflow."""

    print("Starting telemetry ingestion...")

    records = fetch_all_telemetry()

    output_file = save_batch(records)

    print("Telemetry ingestion completed.")
    print(f"Total records: {len(records)}")
    print(f"Output file: {output_file}")

    return output_file


if __name__ == "__main__":
    try:
        run_ingestion()
    except (requests.RequestException, ValueError, OSError) as exc:
        print(f"Telemetry ingestion failed: {exc}")
        raise SystemExit(1)

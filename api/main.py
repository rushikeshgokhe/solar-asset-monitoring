
import csv
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

# Locate the existing telemetry CSV
PROJECT_DIR = Path(__file__).resolve().parent.parent
CSV_FILE = PROJECT_DIR / "data" / "solar_telemetry.csv"

app = FastAPI(
    title="Solar Asset Telemetry API",
    description="API for retrieving simulated solar plant telemetry.",
    version="1.0.0",
)


def load_telemetry():
    """Read and convert telemetry records from the existing CSV."""

    if not CSV_FILE.exists():
        raise HTTPException(
            status_code=503,
            detail="Telemetry dataset is currently unavailable.",
        )

    records = []

    try:
        with CSV_FILE.open(
            newline="",
            encoding="utf-8",
        ) as file:
            reader = csv.DictReader(file)

            for row in reader:
                records.append({
                    "timestamp": row["timestamp"],
                    "site_id": row["site_id"],
                    "inverter_id": row["inverter_id"],
                    "ac_power_kw": float(row["ac_power_kw"]),
                    "dc_voltage_v": float(row["dc_voltage_v"]),
                    "inverter_temp_c": float(row["inverter_temp_c"]),
                    "ghi_w_m2": float(row["ghi_w_m2"]),
                    "energy_kwh_interval": float(
                        row["energy_kwh_interval"]
                    ),
                    "expected_scenario": row["expected_scenario"],
                })

    except (KeyError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to read telemetry dataset: {exc}",
        ) from exc

    return records


@app.get("/health")
def health_check():
    """Check API availability."""

    return {
        "status": "healthy",
        "service": "solar-asset-telemetry-api",
    }


@app.get("/sites")
def get_sites():
    """Return all available solar site IDs."""

    records = load_telemetry()

    sites = sorted({
        record["site_id"] for record in records
    })

    return {
        "total_sites": len(sites),
        "sites": sites,
    }


@app.get("/telemetry")
def get_telemetry(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Return paginated telemetry records."""

    records = load_telemetry()

    total = len(records)
    items = records[offset:offset + limit]

    return {
        "total_records": total,
        "limit": limit,
        "offset": offset,
        "returned_records": len(items),
        "data": items,
    }


@app.get("/telemetry/{site_id}")
def get_site_telemetry(
    site_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Return paginated telemetry for a specific site."""

    records = load_telemetry()

    site_records = [
        record for record in records
        if record["site_id"] == site_id
    ]

    if not site_records:
        raise HTTPException(
            status_code=404,
            detail=f"No telemetry found for site: {site_id}",
        )

    total = len(site_records)
    items = site_records[offset:offset + limit]

    return {
        "site_id": site_id,
        "total_records": total,
        "limit": limit,
        "offset": offset,
        "returned_records": len(items),
        "data": items,
    }

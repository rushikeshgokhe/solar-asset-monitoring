"""Scheduled Lambda entry point: generates a synthetic solar telemetry CSV batch
and uploads it to s3://<TELEMETRY_BUCKET>/telemetry/ to trigger processing."""
import csv
import io
import json
import logging
import os
import random
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_s3 = boto3.client("s3")

SITES = {
    "SITE-101": ["INV-01", "INV-02", "INV-03"],
    "SITE-102": ["INV-01", "INV-02", "INV-03"],
    "SITE-103": ["INV-01", "INV-02", "INV-03"],
    "SITE-104": ["INV-01", "INV-02", "INV-03"],
}

CSV_HEADERS = [
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


def generate_batch_rows(timestamp_str=None, inject_faults=True):
    """Build one 5-minute interval snapshot across all 12 inverters."""
    if timestamp_str is None:
        timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for site_id, inverters in SITES.items():
        for inverter_id in inverters:
            ghi = round(random.uniform(650.0, 850.0), 1)
            ac_power = round(random.uniform(70.0, 88.0), 2)
            dc_voltage = round(random.uniform(595.0, 635.0), 2)
            temp_c = round(random.uniform(42.0, 56.0), 2)
            scenario = "NORMAL"

            if inject_faults and site_id == "SITE-104" and inverter_id == "INV-03":
                ac_power = 0.2
                scenario = "ZERO_POWER"
            elif inject_faults and site_id == "SITE-102" and inverter_id == "INV-01":
                temp_c = 84.5
                scenario = "HIGH_TEMPERATURE"

            energy_kwh = round(ac_power * (5.0 / 60.0), 3)
            rows.append(
                {
                    "timestamp": timestamp_str,
                    "site_id": site_id,
                    "inverter_id": inverter_id,
                    "ac_power_kw": ac_power,
                    "dc_voltage_v": dc_voltage,
                    "inverter_temp_c": temp_c,
                    "ghi_w_m2": ghi,
                    "energy_kwh_interval": energy_kwh,
                    "expected_scenario": scenario,
                }
            )
    return rows


def rows_to_csv(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_HEADERS)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def handler(event, context):
    bucket = os.environ["TELEMETRY_BUCKET"]
    prefix = os.environ.get("TELEMETRY_PREFIX", "telemetry/")
    inject_faults = os.environ.get("INJECT_FAULTS", "true").lower() == "true"

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
    batch_tag = now_utc.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    key = f"{prefix}telemetry_{batch_tag}.csv"

    rows = generate_batch_rows(timestamp_str=ts_str, inject_faults=inject_faults)
    csv_body = rows_to_csv(rows)

    _s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_body.encode("utf-8"),
        ContentType="text/csv",
    )

    logger.info(
        json.dumps(
            {
                "event": "telemetry_generated",
                "bucket": bucket,
                "key": key,
                "rows": len(rows),
            }
        )
    )
    return {"bucket": bucket, "key": key, "rows": len(rows)}
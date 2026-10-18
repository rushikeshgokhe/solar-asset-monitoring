"""Lambda entry point: S3 object-created event -> incident CSV in processed/ + SNS summary."""
import json
import logging
import os
from urllib.parse import unquote_plus

import boto3

import rules

logger = logging.getLogger()
logger.setLevel(logging.INFO)

INPUT_PREFIX = "telemetry/"
OUTPUT_PREFIX = "processed/"

_s3 = boto3.client("s3")
_sns = boto3.client("sns")


def _log(**kw):
    logger.info(json.dumps(kw))


def process_object(bucket, key):
    body = _s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    rows, skipped = rules.parse_rows(body)
    incidents = rules.detect_all(rows)

    name = os.path.splitext(os.path.basename(key))[0]
    out_key = f"{OUTPUT_PREFIX}{name}_incidents.csv"
    _s3.put_object(Bucket=bucket, Key=out_key,
                   Body=rules.incidents_to_csv(incidents).encode("utf-8"),
                   ContentType="text/csv")

    summary = rules.summarize(len(rows), skipped, incidents)
    topic = os.environ.get("SNS_TOPIC_ARN")
    if incidents and topic:
        _sns.publish(TopicArn=topic, Subject="Solar monitoring: anomalies detected",
                     Message=f"File: s3://{bucket}/{key}\n{summary}")

    _log(event="processed", key=key, out_key=out_key, rows=len(rows),
         skipped=skipped, incidents=len(incidents))
    return {"key": key, "out_key": out_key, "rows": len(rows),
            "skipped": skipped, "incidents": len(incidents)}


def handler(event, context):
    results = []
    for rec in event.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        key = unquote_plus(rec["s3"]["object"]["key"])
        # Guard against recursion / wrong files
        if not key.startswith(INPUT_PREFIX) or not key.lower().endswith(".csv"):
            _log(event="ignored", key=key)
            continue
        results.append(process_object(bucket, key))
    return {"processed": results}

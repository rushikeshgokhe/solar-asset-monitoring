"""Lambda entry point: S3 object-created event -> incident CSV in processed/,
correlated & idempotent incident lifecycle in DynamoDB, SNS & SQS ticket queue."""
import json
import logging
import os
from urllib.parse import unquote_plus

import boto3

from incident_repository import (
    evaluate_and_persist_recovery,
    list_active_incidents,
    persist_correlated_batch,
)
import rules

logger = logging.getLogger()
logger.setLevel(logging.INFO)

INPUT_PREFIX = "telemetry/"
OUTPUT_PREFIX = "processed/"

_s3 = boto3.client("s3")
_sns = boto3.client("sns")
_sqs = boto3.client("sqs")
_dynamodb = None


def _log(**kw):
    logger.info(json.dumps(kw))


def _table():
    """Return the incidents table, or None when INCIDENTS_TABLE is not set."""
    global _dynamodb
    name = os.environ.get("INCIDENTS_TABLE")
    if not name:
        return None
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(name)


def store_items(items):
    """Legacy batch writer helper kept for backward compatibility."""
    table = _table()
    if table is None or not items:
        return 0
    with table.batch_writer(overwrite_by_pkeys=["pk", "sk"]) as batch:
        for item in items:
            batch.put_item(Item=item)
    return len(items)


def _format_sns_message(bucket, key, summary, persisted_incidents, closed_incidents):
    lines = [f"File: s3://{bucket}/{key}", summary]
    if persisted_incidents:
        lines.append("\nNormalized Incidents:")
        for inc in persisted_incidents:
            lines.append(
                f"- [{inc['severity']}] {inc['incident_type']} | "
                f"{inc['site_id']}/{inc['inverter_id']} | "
                f"ID: {inc['incident_id']} | Status: {inc['status']} | "
                f"First: {inc['first_detected']} | Last: {inc['last_detected']}"
            )
    if closed_incidents:
        lines.append("\nRecovered & Closed Incidents:")
        for inc in closed_incidents:
            lines.append(
                f"- {inc['incident_type']} | {inc['site_id']}/{inc['inverter_id']} | "
                f"ID: {inc['incident_id']} -> CLOSED"
            )
    return "\n".join(lines)


def _publish_ticket_messages(persisted_incidents, closed_incidents):
    """Send actionable incident creation/closure events to the SQS ticket queue."""
    queue_url = os.environ.get("TICKET_QUEUE_URL")
    if not queue_url:
        return 0

    sent = 0
    seen_ids = set()
    for inc in list(persisted_incidents) + list(closed_incidents):
        inc_id = inc["incident_id"]
        if inc_id in seen_ids:
            continue
        seen_ids.add(inc_id)
        payload = {
            "incident_id": inc_id,
            "site_id": inc["site_id"],
            "inverter_id": inc["inverter_id"],
            "incident_type": inc["incident_type"],
            "severity": inc["severity"],
            "first_detected": inc["first_detected"],
            "last_detected": inc["last_detected"],
            "occurrence_count": int(inc.get("occurrence_count", 1)),
            "status": inc["status"],
        }
        _sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(payload))
        sent += 1
    return sent


def process_object(bucket, key):
    body = _s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    rows, skipped = rules.parse_rows(body)
    incidents = rules.detect_all(rows)

    name = os.path.splitext(os.path.basename(key))[0]
    out_key = f"{OUTPUT_PREFIX}{name}_incidents.csv"
    _s3.put_object(
        Bucket=bucket,
        Key=out_key,
        Body=rules.incidents_to_csv(incidents).encode("utf-8"),
        ContentType="text/csv",
    )

    table = _table()
    stored_events = 0
    duplicate_events = 0
    normalized_incidents = []
    closed_incidents = []

    if table is not None:
        batch_result = persist_correlated_batch(table, incidents, key)
        stored_events = batch_result["stored_events"]
        duplicate_events = batch_result["duplicate_events"]
        normalized_incidents = batch_result["incidents"]

        for active_inc in list_active_incidents(table):
            updated_inc = evaluate_and_persist_recovery(table, active_inc, rows)
            if updated_inc.get("status") == "CLOSED" and active_inc.get("status") != "CLOSED":
                closed_incidents.append(updated_inc)

    summary = rules.summarize(len(rows), skipped, incidents)
    topic = os.environ.get("SNS_TOPIC_ARN")
    should_notify = (
        (stored_events > 0 or len(closed_incidents) > 0)
        if table is not None
        else bool(incidents)
    )

    if should_notify and topic:
        _sns.publish(
            TopicArn=topic,
            Subject="Solar monitoring: incident update",
            Message=_format_sns_message(
                bucket, key, summary, normalized_incidents, closed_incidents
            ),
        )

    tickets_queued = 0
    if stored_events > 0 or closed_incidents:
        tickets_queued = _publish_ticket_messages(
            normalized_incidents if stored_events > 0 else [],
            closed_incidents,
        )

    _log(
        event="processed",
        key=key,
        out_key=out_key,
        rows=len(rows),
        skipped=skipped,
        incidents=len(incidents),
        normalized_incidents=len(normalized_incidents),
        stored=stored_events,
        duplicates=duplicate_events,
        closed=len(closed_incidents),
        tickets_queued=tickets_queued,
    )
    return {
        "key": key,
        "out_key": out_key,
        "rows": len(rows),
        "skipped": skipped,
        "incidents": len(incidents),
        "normalized_incidents": len(normalized_incidents),
        "stored": stored_events,
        "duplicates": duplicate_events,
        "closed": len(closed_incidents),
        "tickets_queued": tickets_queued,
    }


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
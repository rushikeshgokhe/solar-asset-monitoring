from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from normalizer import normalize_incidents
from recovery import count_consecutive_healthy_readings, evaluate_incident_recovery


ACTIVE_STATUSES = {"NEW", "OPEN", "RECOVERY_DETECTED"}


def build_incident_item(incident):
    """
    Convert a normalized incident into a DynamoDB-compatible item.
    """
    required_fields = [
        "incident_id",
        "site_id",
        "inverter_id",
        "incident_type",
        "severity",
        "first_detected",
        "last_detected",
        "occurrence_count",
        "status",
    ]

    for field in required_fields:
        if field not in incident:
            raise ValueError(f"Missing required field: {field}")

    if not incident["site_id"] or not incident["inverter_id"]:
        raise ValueError("Site ID and inverter ID cannot be empty")

    if incident["occurrence_count"] < 1:
        raise ValueError("Occurrence count must be at least 1")

    first_detected = datetime.fromisoformat(incident["first_detected"])
    last_detected = datetime.fromisoformat(incident["last_detected"])

    if last_detected < first_detected:
        raise ValueError("Last detected cannot precede first detected")

    partition_key = f"{incident['site_id']}#{incident['inverter_id']}"
    sort_key = (
        f"INCIDENT#{incident['incident_type']}#"
        f"{incident['first_detected']}"
    )

    return {
        "pk": partition_key,
        "sk": sort_key,
        "record_type": "INCIDENT",
        "incident_id": incident["incident_id"],
        "site_id": incident["site_id"],
        "inverter_id": incident["inverter_id"],
        "incident_type": incident["incident_type"],
        "severity": incident["severity"],
        "first_detected": incident["first_detected"],
        "last_detected": incident["last_detected"],
        "occurrence_count": incident["occurrence_count"],
        "source": incident.get("source", "telemetry_rules"),
        "status": incident["status"],
    }


def build_event_item(
    incident,
    source_key,
    ingested_at=None,
    incident_id=None,
):
    """
    Convert an individual detection into a DynamoDB event item.
    """
    required_fields = [
        "timestamp",
        "site_id",
        "inverter_id",
        "incident_type",
        "severity",
        "detail",
    ]

    for field in required_fields:
        if field not in incident:
            raise ValueError(f"Missing required field: {field}")

    if not incident["site_id"] or not incident["inverter_id"]:
        raise ValueError("Site ID and inverter ID cannot be empty")

    datetime.fromisoformat(incident["timestamp"])

    partition_key = f"{incident['site_id']}#{incident['inverter_id']}"
    sort_key = f"{incident['timestamp']}#{incident['incident_type']}"

    item = {
        "pk": partition_key,
        "sk": sort_key,
        "record_type": "EVENT",
        **incident,
        "source_key": source_key,
    }

    if incident_id is not None:
        item["incident_id"] = incident_id

    if ingested_at is not None:
        item["ingested_at"] = ingested_at

    return item


def _advance_incident_boundaries(table, pk, sk, event_timestamp):
    """
    Monotonically expand first_detected and last_detected so out-of-order
    events never move last_detected backwards or first_detected forwards.
    """
    try:
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #last = :ts",
            ConditionExpression="attribute_not_exists(#last) OR #last < :ts",
            ExpressionAttributeNames={"#last": "last_detected"},
            ExpressionAttributeValues={":ts": event_timestamp},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

    try:
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #first = :ts",
            ConditionExpression="#first > :ts",
            ExpressionAttributeNames={"#first": "first_detected"},
            ExpressionAttributeValues={":ts": event_timestamp},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def store_event_and_update_incident(table, event, incident, source_key):
    """
    Atomically store a new event and update its incident summary.
    Duplicate events will not increment the occurrence count.
    Out-of-order events preserve true first_detected and last_detected bounds.
    """
    event_item = build_event_item(
        event,
        source_key,
        incident_id=incident.get("incident_id"),
    )
    incident_item = build_incident_item(incident)

    try:
        table.meta.client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": table.name,
                        "Item": event_item,
                        "ConditionExpression": (
                            "attribute_not_exists(pk) "
                            "AND attribute_not_exists(sk)"
                        ),
                    }
                },
                {
                    "Update": {
                        "TableName": table.name,
                        "Key": {
                            "pk": incident_item["pk"],
                            "sk": incident_item["sk"],
                        },
                        "UpdateExpression": (
                            "SET #rt = if_not_exists(#rt, :rt), "
                            "#iid = if_not_exists(#iid, :iid), "
                            "#site = if_not_exists(#site, :site), "
                            "#inv = if_not_exists(#inv, :inv), "
                            "#type = if_not_exists(#type, :type), "
                            "#severity = :severity, "
                            "#first = if_not_exists(#first, :first), "
                            "#last = if_not_exists(#last, :last), "
                            "#source = if_not_exists(#source, :source), "
                            "#status = if_not_exists(#status, :status) "
                            "ADD #count :one"
                        ),
                        "ExpressionAttributeNames": {
                            "#rt": "record_type",
                            "#iid": "incident_id",
                            "#site": "site_id",
                            "#inv": "inverter_id",
                            "#type": "incident_type",
                            "#severity": "severity",
                            "#first": "first_detected",
                            "#last": "last_detected",
                            "#source": "source",
                            "#status": "status",
                            "#count": "occurrence_count",
                        },
                        "ExpressionAttributeValues": {
                            ":rt": "INCIDENT",
                            ":iid": incident_item["incident_id"],
                            ":site": incident_item["site_id"],
                            ":inv": incident_item["inverter_id"],
                            ":type": incident_item["incident_type"],
                            ":severity": incident_item["severity"],
                            ":first": incident_item["first_detected"],
                            ":last": event["timestamp"],
                            ":source": incident_item["source"],
                            ":status": incident_item["status"],
                            ":one": 1,
                        },
                    }
                },
            ]
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            reasons = exc.response.get("CancellationReasons", [])
            if reasons and reasons[0].get("Code") == "ConditionalCheckFailed":
                return False
        raise

    _advance_incident_boundaries(
        table,
        incident_item["pk"],
        incident_item["sk"],
        event["timestamp"],
    )
    return True


def find_active_incident(table, site_id, inverter_id, incident_type):
    """
    Find the latest unresolved incident for a specific inverter
    and incident type. A CLOSED incident is never reused.
    """
    partition_key = f"{site_id}#{inverter_id}"
    sort_key_prefix = f"INCIDENT#{incident_type}#"

    response = table.query(
        KeyConditionExpression=(
            Key("pk").eq(partition_key)
            & Key("sk").begins_with(sort_key_prefix)
        ),
        ScanIndexForward=False,
        Limit=1,
    )

    items = response.get("Items", [])
    if not items:
        return None

    latest_incident = items[0]
    if latest_incident.get("status") in ACTIVE_STATUSES:
        return latest_incident

    return None


def list_active_incidents(table):
    """
    Return all currently unresolved incident records (NEW, OPEN, RECOVERY_DETECTED).
    """
    response = table.scan()
    return [
        item
        for item in response.get("Items", [])
        if item.get("record_type") == "INCIDENT"
        and item.get("status") in ACTIVE_STATUSES
    ]


def reuse_incident_identity(incident, existing_incident):
    """
    Preserve the identity, sort-key start time, and original first_detected
    of an existing unresolved incident. A CLOSED incident is ignored.
    """
    updated = dict(incident)

    if existing_incident is None:
        return updated

    if existing_incident.get("status") not in ACTIVE_STATUSES:
        return updated

    updated["incident_id"] = existing_incident["incident_id"]
    updated["first_detected"] = existing_incident["first_detected"]
    updated["status"] = "OPEN"
    return updated


def update_incident_status(table, incident, new_status, updated_at=None):
    """
    Persist an incident lifecycle status transition in DynamoDB.
    """
    pk = incident.get("pk") or f"{incident['site_id']}#{incident['inverter_id']}"
    sk = incident.get("sk") or (
        f"INCIDENT#{incident['incident_type']}#{incident['first_detected']}"
    )

    update_expr = "SET #status = :status"
    expr_names = {"#status": "status"}
    expr_values = {":status": new_status}

    if updated_at is not None:
        update_expr += ", #updated = :updated"
        expr_names["#updated"] = "updated_at"
        expr_values[":updated"] = updated_at

    response = table.update_item(
        Key={"pk": pk, "sk": sk},
        UpdateExpression=update_expr,
        ConditionExpression="attribute_exists(pk) AND attribute_exists(sk)",
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW",
    )
    return response["Attributes"]


def evaluate_and_persist_recovery(
    table,
    incident,
    rows,
    required_readings=2,
):
    """
    Evaluate telemetry rows for an active incident and persist lifecycle
    transitions (RECOVERY_DETECTED or CLOSED) in DynamoDB.
    """
    if incident.get("status") == "CLOSED":
        return incident

    if evaluate_incident_recovery(incident, rows, required_readings=required_readings):
        return update_incident_status(table, incident, "CLOSED")

    last_detected = incident["last_detected"]
    if isinstance(last_detected, str):
        last_detected_dt = datetime.fromisoformat(last_detected)
    else:
        last_detected_dt = last_detected

    matching_rows = []
    for row in rows:
        if (
            row["site_id"] != incident["site_id"]
            or row["inverter_id"] != incident["inverter_id"]
        ):
            continue
        ts = row["timestamp"]
        ts_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
        if ts_dt >= last_detected_dt:
            matching_rows.append({**row, "timestamp": ts_dt})

    healthy_streak = count_consecutive_healthy_readings(
        incident["incident_type"],
        matching_rows,
    )
    if healthy_streak >= 1 and incident.get("status") in {"NEW", "OPEN"}:
        return update_incident_status(table, incident, "RECOVERY_DETECTED")

    return incident


def persist_correlated_batch(
    table,
    raw_alerts,
    source_key,
    correlation_window_minutes=15,
):
    """
    Correlate raw alerts within a batch and across existing open DynamoDB
    incidents, persisting raw events and incident summaries atomically.
    """
    if not raw_alerts:
        return {"stored_events": 0, "duplicate_events": 0, "incidents": []}

    normalized_groups = normalize_incidents(
        raw_alerts,
        correlation_window_minutes=correlation_window_minutes,
    )

    stored_events = 0
    duplicate_events = 0
    persisted_incidents = []

    for group in normalized_groups:
        existing = find_active_incident(
            table,
            group["site_id"],
            group["inverter_id"],
            group["incident_type"],
        )

        if existing is not None:
            existing_last = datetime.fromisoformat(existing["last_detected"])
            group_first = datetime.fromisoformat(group["first_detected"])
            gap = abs(group_first - existing_last)
            if (
                gap <= timedelta(minutes=correlation_window_minutes)
                or existing.get("status") in {"OPEN", "RECOVERY_DETECTED"}
            ):
                target_incident = reuse_incident_identity(group, existing)
            else:
                target_incident = dict(group)
        else:
            target_incident = dict(group)

        matching_alerts = [
            alert
            for alert in raw_alerts
            if alert["site_id"] == group["site_id"]
            and alert["inverter_id"] == group["inverter_id"]
            and alert["incident_type"] == group["incident_type"]
            and group["first_detected"] <= alert["timestamp"] <= group["last_detected"]
        ]

        group_new_events = 0
        for alert in matching_alerts:
            inserted = store_event_and_update_incident(
                table,
                alert,
                target_incident,
                source_key,
            )
            if inserted:
                stored_events += 1
                group_new_events += 1
            else:
                duplicate_events += 1

        if existing is not None and group_new_events > 0 and existing.get("status") == "NEW":
            update_incident_status(table, target_incident, "OPEN")
            target_incident["status"] = "OPEN"

        persisted_incidents.append(target_incident)

    return {
        "stored_events": stored_events,
        "duplicate_events": duplicate_events,
        "incidents": persisted_incidents,
    }

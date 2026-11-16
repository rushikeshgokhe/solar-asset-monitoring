
from datetime import datetime


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

    first_detected = datetime.fromisoformat(
        incident["first_detected"]
    )

    last_detected = datetime.fromisoformat(
        incident["last_detected"]
    )

    if last_detected < first_detected:
        raise ValueError("Last detected cannot precede first detected")

    partition_key = (
        f"{incident['site_id']}#{incident['inverter_id']}"
    )

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

    partition_key = (
        f"{incident['site_id']}#{incident['inverter_id']}"
    )

    sort_key = (
        f"{incident['timestamp']}#{incident['incident_type']}"
    )

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



def store_event_and_update_incident(table, event, incident, source_key):
    """
    Atomically store a new event and update its incident summary.
    Duplicate events will not increment the occurrence count.
    """
    from boto3.dynamodb.types import TypeSerializer
    from botocore.exceptions import ClientError

    event_item = build_event_item(event, source_key)
    incident_item = build_incident_item(incident)

    serializer = TypeSerializer()

    def serialize_map(item):
        return {
            key: serializer.serialize(value)
            for key, value in item.items()
        }

    try:
        table.meta.client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": table.name,
                        "Item": serialize_map(event_item),
                        "ConditionExpression": (
                            "attribute_not_exists(pk) "
                            "AND attribute_not_exists(sk)"
                        ),
                    }
                },
                {
                    "Update": {
                        "TableName": table.name,
                        "Key": serialize_map({
                            "pk": incident_item["pk"],
                            "sk": incident_item["sk"],
                        }),
                        "UpdateExpression": (
                            "SET #rt = if_not_exists(#rt, :rt), "
                            "#iid = if_not_exists(#iid, :iid), "
                            "#site = if_not_exists(#site, :site), "
                            "#inv = if_not_exists(#inv, :inv), "
                            "#type = if_not_exists(#type, :type), "
                            "#severity = :severity, "
                            "#first = if_not_exists(#first, :first), "
                            "#last = :last, "
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
                        "ExpressionAttributeValues": serialize_map({
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
                        }),
                    }
                },
            ]
        )
        return True

    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            reasons = exc.response.get("CancellationReasons", [])
            if reasons and reasons[0].get("Code") == "ConditionalCheckFailed":
                return False
        raise

def find_active_incident(table, site_id, inverter_id, incident_type):
    """
    Find the latest unresolved incident for a specific inverter
    and incident type.

    A resolved incident is not reused for a future occurrence.
    """

    from boto3.dynamodb.conditions import Key

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

    active_statuses = {
        "NEW",
        "OPEN",
        "RECOVERY_DETECTED",
    }

    if latest_incident.get("status") in active_statuses:
        return latest_incident

    return None

def reuse_incident_identity(incident, existing_incident):
    """
    Preserve the identity and original start time of an
    existing unresolved incident.

    A new incident keeps its own identity.
    """

    updated = dict(incident)

    if existing_incident is None:
        return updated

    updated["incident_id"] = existing_incident["incident_id"]
    updated["first_detected"] = existing_incident["first_detected"]

    # A new anomaly while recovery is pending means
    # the same incident is active again.
    updated["status"] = "OPEN"

    return updated

"""SQS-triggered Lambda: creates or updates Jira tickets for correlated solar
incidents idempotently, storing jira_ticket_id in DynamoDB."""
import base64
import json
import logging
import os
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_dynamodb = None
_ssm = None


def _table():
    global _dynamodb
    name = os.environ.get("INCIDENTS_TABLE")
    if not name:
        return None
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb.Table(name)


def _get_jira_config():
    """Fetch Jira connection details from SSM Parameter Store (SecureString)."""
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm")

    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    project_key = os.environ.get("JIRA_PROJECT_KEY", "SOLAR")
    email_param = os.environ["JIRA_EMAIL_PARAM"]
    token_param = os.environ["JIRA_TOKEN_PARAM"]

    email = _ssm.get_parameter(Name=email_param, WithDecryption=True)["Parameter"]["Value"]
    token = _ssm.get_parameter(Name=token_param, WithDecryption=True)["Parameter"]["Value"]
    return base_url, project_key, email, token


def _jira_request(method, url, email, token, payload=None):
    auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def create_jira_issue(incident):
    base_url, project_key, email, token = _get_jira_config()
    summary = (
        f"{incident['incident_type']} - {incident['site_id']} - {incident['inverter_id']}"
    )
    description = (
        f"Automated Solar Asset Monitoring Incident\n"
        f"Incident ID: {incident['incident_id']}\n"
        f"Site: {incident['site_id']} | Inverter: {incident['inverter_id']}\n"
        f"Severity: {incident['severity']}\n"
        f"First Detected: {incident['first_detected']}\n"
        f"Last Detected: {incident['last_detected']}\n"
        f"Occurrences: {incident.get('occurrence_count', 1)}\n"
        f"Status: {incident['status']}"
    )
    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": "Bug"},
        }
    }
    resp = _jira_request("POST", f"{base_url}/rest/api/2/issue", email, token, payload)
    return resp["key"]


def comment_jira_issue(ticket_key, incident):
    base_url, _, email, token = _get_jira_config()
    payload = {
        "body": (
            f"Incident lifecycle update: status is now {incident['status']} "
            f"(occurrences: {incident.get('occurrence_count', 1)}, "
            f"last_detected: {incident.get('last_detected')})."
        )
    }
    _jira_request(
        "POST",
        f"{base_url}/rest/api/2/issue/{ticket_key}/comment",
        email,
        token,
        payload,
    )


def process_ticket_message(msg, table=None):
    if table is None:
        table = _table()

    pk = f"{msg['site_id']}#{msg['inverter_id']}"
    sk = f"INCIDENT#{msg['incident_type']}#{msg['first_detected']}"

    existing_item = {}
    if table is not None:
        existing_item = table.get_item(Key={"pk": pk, "sk": sk}).get("Item", {})

    existing_ticket_id = existing_item.get("jira_ticket_id") or msg.get("jira_ticket_id")

    if existing_ticket_id:
        if msg.get("status") == "CLOSED":
            comment_jira_issue(existing_ticket_id, msg)
            action = "updated_closed"
        else:
            action = "duplicate_skipped"
        logger.info(
            json.dumps(
                {
                    "event": "ticket_skipped_or_updated",
                    "action": action,
                    "incident_id": msg["incident_id"],
                    "jira_ticket_id": existing_ticket_id,
                }
            )
        )
        return {"action": action, "jira_ticket_id": existing_ticket_id}

    ticket_key = create_jira_issue(msg)

    if table is not None:
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #jt = :jt",
            ConditionExpression="attribute_not_exists(#jt)",
            ExpressionAttributeNames={"#jt": "jira_ticket_id"},
            ExpressionAttributeValues={":jt": ticket_key},
        )

    logger.info(
        json.dumps(
            {
                "event": "jira_ticket_created",
                "incident_id": msg["incident_id"],
                "jira_ticket_id": ticket_key,
            }
        )
    )
    return {"action": "created", "jira_ticket_id": ticket_key}


def handler(event, context):
    results = []
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        results.append(process_ticket_message(body))
    return {"processed": results}
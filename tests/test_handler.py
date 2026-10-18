import os
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
import handler


def test_ignores_non_telemetry_keys():
    ev = {"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": "processed/x.csv"}}}]}
    assert handler.handler(ev, None) == {"processed": []}

def test_ignores_non_csv():
    ev = {"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": "telemetry/x.txt"}}}]}
    assert handler.handler(ev, None) == {"processed": []}

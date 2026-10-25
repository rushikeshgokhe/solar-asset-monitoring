import os

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")

import handler
import rules

INC = {
    "timestamp": "2026-10-01 12:00:00",
    "site_id": "SITE-101",
    "inverter_id": "INV-01",
    "incident_type": "ZERO_POWER",
    "severity": "HIGH",
    "detail": "x",
}


def test_item_keys():
    item = rules.to_item(INC, "telemetry/a.csv", "2026-10-24T00:00:00+00:00")
    assert item["pk"] == "SITE-101#INV-01"
    assert item["sk"] == "2026-10-01 12:00:00#ZERO_POWER"
    assert item["source_key"] == "telemetry/a.csv"


def test_same_incident_gives_same_key():
    a = rules.to_item(INC, "telemetry/a.csv", "t1")
    b = rules.to_item(INC, "telemetry/b.csv", "t2")
    assert (a["pk"], a["sk"]) == (b["pk"], b["sk"])


def test_different_type_gives_different_key():
    other = dict(INC, incident_type="HIGH_TEMPERATURE")
    assert rules.to_item(INC, "k")["sk"] != rules.to_item(other, "k")["sk"]


def test_store_items_without_table_returns_zero(monkeypatch):
    monkeypatch.delenv("INCIDENTS_TABLE", raising=False)
    assert handler.store_items([rules.to_item(INC, "k")]) == 0


class FakeTable:
    def __init__(self):
        self.items = []

    def batch_writer(self, overwrite_by_pkeys=None):
        table = self

        class Writer:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def put_item(self, Item):
                table.items.append(Item)

        return Writer()


def test_store_items_writes_every_item(monkeypatch):
    fake = FakeTable()
    monkeypatch.setattr(handler, "_table", lambda: fake)
    assert handler.store_items([rules.to_item(INC, "k")]) == 1
    assert fake.items[0]["pk"] == "SITE-101#INV-01"
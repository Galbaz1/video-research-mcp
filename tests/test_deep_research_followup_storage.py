"""Process-local follow-up append controls with fake collection snapshots."""

import asyncio
import copy
import json
import threading
from types import SimpleNamespace

import pytest

from video_research_mcp.weaviate_store import deep_research as storage


class FakeCollection:
    """Model detached fetches and replacement updates without a database."""

    def __init__(self, properties=None):
        self.properties = properties or {
            "follow_up_ids": [], "follow_ups_json": "[]", "report_text": "original report",
        }
        self.guard = threading.Lock()
        self.first_snapshot = threading.Event()
        self.second_snapshot = threading.Event()
        self.overlap_reads = False
        self.reads = 0
        self.updates = []
        self.fail_once = None
        self.missing = False
        self.query = SimpleNamespace(fetch_objects=self.fetch_objects)
        self.data = SimpleNamespace(update=self.update)

    def fetch_objects(self, *, filters, limit):
        """Return independent report properties and optionally overlap two reads."""
        assert threading.current_thread() is not threading.main_thread()
        assert filters == ("interaction_id", "original") and limit == 1
        with self.guard:
            if self.fail_once == "fetch":
                self.fail_once = None
                raise OSError("injected fetch failure")
            if self.missing:
                return SimpleNamespace(objects=[])
            self.reads += 1
            ordinal = self.reads
            snapshot = copy.deepcopy(self.properties)
        if self.overlap_reads:
            if ordinal == 1:
                self.first_snapshot.set()
                # A serialized second worker cannot fetch until this bounded wait ends.
                self.second_snapshot.wait(1)
            elif ordinal == 2:
                self.second_snapshot.set()
        return SimpleNamespace(objects=[SimpleNamespace(uuid="report-uuid", properties=snapshot)])

    def update(self, *, uuid, properties):
        """Replace supplied array fields while retaining unrelated report fields."""
        assert threading.current_thread() is not threading.main_thread()
        assert uuid == "report-uuid"
        with self.guard:
            if self.fail_once == "update":
                self.fail_once = None
                raise OSError("injected update failure")
            self.updates.append(copy.deepcopy(properties))
            self.properties.update(copy.deepcopy(properties))


@pytest.fixture
def collection(monkeypatch):
    """Bind the actual helper to invented local service boundaries."""
    fake = FakeCollection()

    def selected_collection(name):
        assert name == "DeepResearchReports"
        return fake

    client = SimpleNamespace(collections=SimpleNamespace(get=selected_collection))
    monkeypatch.setattr(storage, "WeaviateClient", SimpleNamespace(get=lambda: client))
    monkeypatch.setattr(storage, "_is_enabled", lambda: True)
    monkeypatch.setattr(storage, "_now", lambda: "invented-utc")
    monkeypatch.setattr(storage, "_interaction_id_filter", lambda value: ("interaction_id", value))
    return fake


async def test_concurrent_followups_preserve_both_appends(collection):
    """GIVEN overlapping worker calls THEN both successful append results remain stored."""
    collection.overlap_reads = True
    first = asyncio.create_task(storage.store_deep_research_followup(
        "original", "first", question="first question", response="first answer",
    ))
    assert await asyncio.to_thread(collection.first_snapshot.wait, 2), "first fetch did not start"
    second = asyncio.create_task(storage.store_deep_research_followup(
        "original", "second", question="second question", response="second answer",
    ))
    assert await asyncio.wait_for(asyncio.gather(first, second), 5) == [True, True]
    assert collection.properties["follow_up_ids"] == ["first", "second"]
    assert json.loads(collection.properties["follow_ups_json"]) == [
        {"id": "first", "question": "first question", "response": "first answer"},
        {"id": "second", "question": "second question", "response": "second answer"},
    ]
    assert collection.properties["report_text"] == "original report"


@pytest.mark.parametrize("operation", ["fetch", "update"])
async def test_followup_failure_releases_lock_for_next_call(collection, operation):
    """GIVEN a nonfatal worker exception THEN a subsequent append can complete."""
    collection.fail_once = operation
    assert await storage.store_deep_research_followup("original", "failed") is False
    assert await asyncio.wait_for(storage.store_deep_research_followup(
        "original", "retained", question="next question", response="next answer",
    ), 3) is True
    assert collection.properties["follow_up_ids"] == ["retained"]
    assert json.loads(collection.properties["follow_ups_json"]) == [
        {"id": "retained", "question": "next question", "response": "next answer"},
    ]


@pytest.mark.parametrize("existing", [False, True])
async def test_followup_preserves_existing_fields_order_and_exact_text(collection, existing):
    """GIVEN an ordinary report THEN append fields and existing order stay exact."""
    prior = {"id": "prior", "question": "old question", "response": "old answer"}
    collection.properties["follow_up_ids"] = ["prior"] if existing else None
    collection.properties["follow_ups_json"] = json.dumps([prior]) if existing else ""
    assert await storage.store_deep_research_followup(
        "original", "new", question="question\nexact", response="answer\nexact",
    ) is True
    appended = {"id": "new", "question": "question\nexact", "response": "answer\nexact"}
    assert collection.properties["follow_up_ids"] == (["prior"] if existing else []) + ["new"]
    assert json.loads(collection.properties["follow_ups_json"]) == (
        ([prior] if existing else []) + [appended]
    )
    assert list(collection.updates[0]) == ["follow_up_ids", "follow_ups_json", "updated_at"]
    assert collection.properties["updated_at"] == "invented-utc"
    assert collection.properties["report_text"] == "original report"


async def test_disabled_followup_skips_worker(collection, monkeypatch):
    """GIVEN disabled optional storage THEN no fetch or update is attempted."""
    monkeypatch.setattr(storage, "_is_enabled", lambda: False)
    assert await storage.store_deep_research_followup("original", "unused") is False
    assert collection.reads == 0 and collection.updates == []


async def test_missing_report_followup_remains_nonfatal(collection):
    """GIVEN no matching report THEN return False without an update."""
    collection.missing = True
    assert await storage.store_deep_research_followup("original", "unused") is False
    assert collection.reads == 0 and collection.updates == []

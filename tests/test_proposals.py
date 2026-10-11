"""feat-066: records single-table CAS + proposal lifecycle gates. 100% offline."""

import pytest

from memoria.proposals import (
    ProposalExpired,
    ProposalHashMismatch,
    ProposalInvalid,
    ProposalNotFound,
    ProposalService,
    payload_hash,
)
from memoria.records import RecordStore


@pytest.fixture
def service(tmp_path):
    return ProposalService(RecordStore(tmp_path / "records.db"))


def test_cas_only_when_premise_still_holds(tmp_path):
    store = RecordStore(tmp_path / "r.db")
    assert store.insert("t", "a", {"status": "queued", "n": 1})
    assert not store.insert("t", "a", {"status": "other"})  # (kind, id) is the PK
    assert store.cas("t", "a", {"status": "queued"}, {"status": "running"})
    row = store.get("t", "a")
    assert row["status"] == "running" and row["n"] == 1  # shallow merge keeps siblings
    assert not store.cas("t", "a", {"status": "queued"}, {"status": "x"})  # premise gone


def test_propose_hashes_payload_and_dedups_by_idem_key(service):
    p1 = service.propose("delete_doc", {"doc_id": "d1"}, idem_key="delete_doc:d1")
    assert p1["status"] == "awaiting_review"
    assert p1["content_hash"] == payload_hash("delete_doc", {"doc_id": "d1"})
    p2 = service.propose("delete_doc", {"doc_id": "d1"}, idem_key="delete_doc:d1")
    assert p2["id"] == p1["id"]  # one live proposal per purpose
    p3 = service.propose("delete_doc", {"doc_id": "d2"})
    assert p3["id"] not in {p1["id"], p2["id"]}


def test_propose_rejects_unknown_kind(service):
    with pytest.raises(ProposalInvalid):
        service.propose("nuke_everything", {})


def test_decide_gates(service):
    p = service.propose("delete_doc", {"doc_id": "d1"})
    with pytest.raises(ProposalNotFound):
        service.decide("nope", "approved", p["content_hash"])
    with pytest.raises(ProposalHashMismatch):
        service.decide(p["id"], "approved", "deadbeef")  # anti content-swap
    with pytest.raises(ProposalInvalid):
        service.decide(p["id"], "maybe", p["content_hash"])


def test_decide_deny_is_terminal_and_idempotent(service):
    p = service.propose("reindex", {})
    denied = service.decide(p["id"], "denied", p["content_hash"])
    assert denied["status"] == "denied"
    again = service.decide(p["id"], "denied", p["content_hash"])
    assert again["status"] == "denied" and again["id"] == p["id"]  # replay, no error


def test_claim_then_complete_records_the_outcome(service):
    p = service.propose("archive", {"thread_id": "t", "confirmed_ids": ["m1"]})
    claimed = service.decide(p["id"], "approved", p["content_hash"])
    assert claimed["status"] == "executing"
    assert service.decide(p["id"], "approved", p["content_hash"])["status"] == "executing"
    done = service.complete(p["id"], "succeeded", result={"archived": ["m1"]})
    assert done["status"] == "succeeded" and done["result"] == {"archived": ["m1"]}
    assert service.complete(p["id"], "failed") is None  # already terminal: no retry write


def test_outcome_unknown_is_a_first_class_outcome(service):
    p = service.propose("archive", {})
    service.decide(p["id"], "approved", p["content_hash"])
    done = service.complete(p["id"], "outcome_unknown", error="网络中断")
    assert done["status"] == "outcome_unknown" and "网络中断" in done["error"]


def test_expired_proposal_cannot_be_decided(service):
    p = service.propose("delete_doc", {"doc_id": "d"})
    # White-box: age the record past its TTL.
    assert service._records.cas(
        "proposal", p["id"], {"status": "awaiting_review"}, {"expires_at": "2020-01-01T00:00:00+00:00"}
    )
    with pytest.raises(ProposalExpired):
        service.decide(p["id"], "approved", p["content_hash"])
    assert service.get(p["id"])["status"] == "expired"


def test_startup_recovery_marks_interrupted_executions_unknown(service):
    p = service.propose("delete_doc", {"doc_id": "d"})
    service.decide(p["id"], "approved", p["content_hash"])  # claimed, then "crash"
    assert service.recover_interrupted() == 1
    row = service.get(p["id"])
    assert row["status"] == "outcome_unknown"
    assert service.recover_interrupted() == 0  # second boot: nothing left to recover

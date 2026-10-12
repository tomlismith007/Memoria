"""Action proposals: destructive/external actions need a hash-bound, expiring,
single-consumption record that a human approves on a channel separate from chat.

feat-066, design in docs/PERSONAL_AGENT_UPGRADE.md §3 P0.1; mechanics from OpenMuse
(docs/agent-architecture/04b §11). Boundary (hard): approval travels only through
ProposalService.decide, which only the /api/proposals/{id}/decide route calls —
never from the chat/agent graph path. Execution itself happens in the app layer
(delete/reindex run inline; archive resumes the graph, whose mail_archive node
writes the terminal status back here).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from memoria.records import RecordStore

KIND = "proposal"
# Status vocabulary lives where it is enforced and displayed: the transitions in
# this module, and ApprovalCenter's STATUS_LABEL map (which also still labels the
# retired `cancelled` status of pre-existing records).
ALL_KINDS = ("archive", "delete_doc", "reindex")
TTL_SECONDS = 30 * 60
DECISIONS = ("approved", "denied")


class ProposalError(Exception):
    """Base; `status_code` maps onto HTTP in the web layer."""

    status_code = 400


class ProposalNotFound(ProposalError):
    status_code = 404


class ProposalHashMismatch(ProposalError):
    status_code = 409


class ProposalExpired(ProposalError):
    status_code = 409


class ProposalConflict(ProposalError):
    status_code = 409


class ProposalInvalid(ProposalError):
    status_code = 400


def _now() -> datetime:
    return datetime.now(timezone.utc)


def payload_hash(kind: str, payload: dict) -> str:
    """Binds the review to the executed bytes: what was shown is what will run."""
    canonical = json.dumps(
        {"kind": kind, "payload": payload}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProposalService:
    def __init__(self, records: RecordStore):
        self._records = records

    def propose(
        self, kind: str, payload: dict, idem_key: str | None = None
    ) -> dict:
        if kind not in ALL_KINDS:
            raise ProposalInvalid(f"未知的提案类型: {kind}")
        if idem_key:
            for p in self._records.scan(KIND):
                if p.get("idem_key") == idem_key and p["status"] in (
                    "awaiting_review",
                    "executing",
                ):
                    return p  # one live proposal per purpose
        now = _now()
        proposal_id = uuid.uuid4().hex
        data = {
            "id": proposal_id,
            "kind": kind,
            "payload": payload,
            "content_hash": payload_hash(kind, payload),
            "status": "awaiting_review",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=TTL_SECONDS)).isoformat(),
            "idem_key": idem_key,
            "result": None,
            "error": None,
        }
        self._records.insert(KIND, proposal_id, data)
        return data

    def get(self, proposal_id: str) -> dict | None:
        return self._records.get(KIND, proposal_id)

    def list(self, status: str | None = None) -> list[dict]:
        items = self._records.scan(KIND)
        return [p for p in items if status is None or p["status"] == status]

    def decide(self, proposal_id: str, decision: str, content_hash: str) -> dict:
        """The six gates: exists → hash matches → not yet decided → not expired →
        atomic claim (approved) or deny. Returns the record in its new state;
        execution is the caller's job (see module docstring)."""
        if decision not in DECISIONS:
            raise ProposalInvalid(f"未知的决定: {decision}")
        p = self._records.get(KIND, proposal_id)
        if p is None:
            raise ProposalNotFound(f"提案 {proposal_id} 不存在")
        if content_hash != p.get("content_hash"):
            raise ProposalHashMismatch("提案内容已变化，请重新打开最新评审再决定")
        if p["status"] != "awaiting_review":
            return p  # idempotent: already decided / executing / terminal
        expires_at = p.get("expires_at")
        if expires_at and _now() > datetime.fromisoformat(expires_at):
            self._records.cas(
                KIND, proposal_id, {"status": "awaiting_review"}, {"status": "expired"}
            )
            raise ProposalExpired("评审已过期，请创建新提案")
        if decision == "denied":
            if not self._records.cas(
                KIND,
                proposal_id,
                {"status": "awaiting_review"},
                {"status": "denied", "result": "Denied by you."},
            ):
                raise ProposalConflict("提案状态已变化，请刷新后重试")
            return self._records.get(KIND, proposal_id)
        if not self._records.cas(
            KIND, proposal_id, {"status": "awaiting_review"}, {"status": "executing"}
        ):
            raise ProposalConflict("提案状态已变化，请刷新后重试")
        return self._records.get(KIND, proposal_id)

    def complete(
        self, proposal_id: str, outcome: str, result: dict | None = None, error: str | None = None
    ) -> dict | None:
        """executing → terminal. Returns None when the record is not executing
        (e.g. already completed by a previous run) — callers must not retry."""
        if outcome not in ("succeeded", "failed", "outcome_unknown"):
            raise ValueError(f"未知的执行结局: {outcome}")
        ok = self._records.cas(
            KIND,
            proposal_id,
            {"status": "executing"},
            {"status": outcome, "result": result, "error": error},
        )
        return self._records.get(KIND, proposal_id) if ok else None

    def recover_interrupted(self) -> int:
        """Startup sweep: executing → outcome_unknown. A restart during execution
        means the result is unknowable; never pretend success (feat-066 boundary)."""
        n = 0
        for p in self.list(status="executing"):
            if self._records.cas(
                KIND,
                p["id"],
                {"status": "executing"},
                {"status": "outcome_unknown", "error": "服务在执行期间重启，结果未知"},
            ):
                n += 1
        return n

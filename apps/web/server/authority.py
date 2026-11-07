"""Execution authority: revisions, exact-plan confirmation, request identity, late-callback rules.

Rules (tested in tests/test_authority.py):
  * Any edit to claim / source / assumption bumps the revision and revokes confirmation.
  * Confirmation binds (revision, plan_hash). A stale hash or revision is refused.
  * Double confirmation and retried start_run with the same request_id are idempotent.
  * A run that completes after an edit, cancel or replacement is stored as HISTORICAL
    on its original revision and never restores current authority.
"""
import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def now():
    return datetime.now(UTC).isoformat()


class AuthorityError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class Session:
    def __init__(self, session_id=None):
        self.id = session_id or uuid.uuid4().hex
        self.lock = threading.RLock()
        self.revision = 0
        self.claim = None          # approved field set
        self.sources = []          # list of provenance dicts
        self.assumptions = {}
        self.plan = None
        self.confirmation = None   # {revision, plan_hash, at}
        self.runs = {}             # run_id -> run dict
        self.request_index = {}    # request_id -> run_id
        self.current_run = None
        self.log = []

    def _log(self, kind, **kw):
        self.log.append({"t": now(), "kind": kind, "revision": self.revision, **kw})

    # -- edits -------------------------------------------------------------
    def edit(self, claim=None, add_source=None, assumptions=None, reason="edit"):
        with self.lock:
            changed = False
            if claim is not None and claim != self.claim:
                self.claim, changed = claim, True
            if add_source is not None:
                self.sources.append(add_source)
                changed = True
            if assumptions is not None and assumptions != self.assumptions:
                self.assumptions, changed = assumptions, True
            if not changed:
                return {"revision": self.revision, "changed": False}
            self.revision += 1
            revoked = self.confirmation is not None
            self.confirmation = None
            self.plan = None
            if self.current_run:
                r = self.runs[self.current_run]
                if r["status"] in ("RUNNING", "QUEUED"):
                    r["status"] = "SUPERSEDED"
                    r["authority"] = "none"
                self.current_run = None
            self._log("edit", reason=reason, confirmation_revoked=revoked)
            return {"revision": self.revision, "changed": True, "confirmation_revoked": revoked}

    # -- plan --------------------------------------------------------------
    def propose_plan(self, plan_body):
        with self.lock:
            if self.claim is None:
                raise AuthorityError("NO_CLAIM", "approve a claim before proposing a plan")
            plan = {
                "revision": self.revision,
                "claim": self.claim,
                "sources": [s["sha256"] for s in self.sources if "sha256" in s],
                "assumptions": self.assumptions,
                **plan_body,
            }
            plan["canonical_plan_hash"] = sha(plan)
            self.plan = plan
            self._log("plan_proposed", plan_hash=plan["canonical_plan_hash"])
            return plan

    def confirm(self, revision, plan_hash):
        with self.lock:
            if self.plan is None:
                raise AuthorityError("NO_PLAN", "no plan to confirm")
            if revision != self.revision:
                raise AuthorityError("STALE_REVISION", f"plan is for revision {revision}; current is {self.revision}")
            if plan_hash != self.plan["canonical_plan_hash"]:
                raise AuthorityError("STALE_PLAN", "plan hash does not match the plan on screen")
            if self.confirmation and self.confirmation["plan_hash"] == plan_hash:
                return {**self.confirmation, "idempotent": True}
            self.confirmation = {"revision": revision, "plan_hash": plan_hash, "at": now()}
            self._log("confirmed", plan_hash=plan_hash)
            return {**self.confirmation, "idempotent": False}

    # -- runs --------------------------------------------------------------
    def start_run(self, request_id):
        with self.lock:
            if request_id in self.request_index:
                return self.runs[self.request_index[request_id]], True
            if not self.confirmation or self.confirmation["revision"] != self.revision:
                raise AuthorityError("NOT_CONFIRMED", "no valid confirmation for the current revision")
            if self.current_run and self.runs[self.current_run]["status"] in ("RUNNING", "QUEUED"):
                raise AuthorityError("RUN_ACTIVE", "a run is already active; cancel it first")
            run_id = uuid.uuid4().hex[:16]
            run = {
                "run_id": run_id,
                "request_id": request_id,
                "revision": self.revision,
                "plan_hash": self.confirmation["plan_hash"],
                "status": "RUNNING",
                "authority": "current",
                "started_at": now(),
                "events": [],
                "result": None,
            }
            self.runs[run_id] = run
            self.request_index[request_id] = run_id
            self.current_run = run_id
            self._log("run_started", run_id=run_id, request_id=request_id)
            return run, False

    def add_event(self, run_id, stage, detail=""):
        with self.lock:
            run = self.runs[run_id]
            if run["status"] != "RUNNING":
                return False   # late progress is dropped
            run["events"].append({"t": now(), "stage": stage, "detail": detail})
            return True

    def complete_run(self, run_id, result):
        """Returns True only if this completion may be shown as current."""
        with self.lock:
            run = self.runs[run_id]
            run["result"] = result
            if run["status"] == "RUNNING" and run["revision"] == self.revision and self.current_run == run_id:
                run["status"] = "COMPLETE"
                run["finished_at"] = now()
                self._log("run_complete", run_id=run_id)
                return True
            # late: keep as historical evidence on its own revision
            if run["status"] == "RUNNING":
                run["status"] = "SUPERSEDED"
            run["authority"] = "none"
            run["late_completion"] = True
            self._log("run_late_completion_ignored", run_id=run_id, status=run["status"])
            return False

    def cancel(self, run_id=None):
        with self.lock:
            rid = run_id or self.current_run
            if not rid or rid not in self.runs:
                raise AuthorityError("NO_RUN", "no run to cancel")
            run = self.runs[rid]
            if run["status"] == "RUNNING":
                run["status"] = "CANCELLED"
                run["authority"] = "none"
                self._log("run_cancelled", run_id=rid)
            if self.current_run == rid:
                self.current_run = None
            return run

    def is_cancelled(self, run_id):
        with self.lock:
            return self.runs[run_id]["status"] != "RUNNING"

    def export(self, run_id):
        """Export is a function of the stored run, not of current edits."""
        with self.lock:
            run = self.runs[run_id]
            return {
                "export_version": 1,
                "session_id": self.id,
                "run": json.loads(canonical(run)),
                "evidence_context": {
                    "revision": run["revision"],
                    "plan_hash": run["plan_hash"],
                    "current_revision_now": self.revision,
                    "is_current": run["authority"] == "current" and run["revision"] == self.revision,
                },
                "exported_at": now(),
            }

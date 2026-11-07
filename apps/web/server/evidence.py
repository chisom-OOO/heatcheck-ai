"""Read-only access to Max's Referee evidence ledger for the UI.

The ledger format and its integrity rules belong to heatcheck/ledger/evidence.py (Max). This
module never writes: it opens an existing JSONL file and runs that module's own verification
(evidence_id and entry_hash recomputed for every line), so the UI can label an entry VERIFIED
only when Max's code says so. The browser does not recompute hashes: Python's canonical JSON
float formatting (e.g. 31.0) differs from JavaScript's.
"""
import os
import sys
from pathlib import Path

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _ledger_module():
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from heatcheck.ledger import evidence  # repo package, imported lazily
    return evidence


class EvidenceUnavailable(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


def configured_path():
    return os.environ.get("HEATCHECK_LEDGER") or None


def read_verified(path):
    """Return every entry of an existing ledger after Max's verification, or raise."""
    if not path:
        raise EvidenceUnavailable("NOT_CONFIGURED", "no evidence ledger configured; start the server with --ledger PATH")
    if not path.endswith(".jsonl") or not os.path.isfile(path):
        raise EvidenceUnavailable("NOT_FOUND", "evidence ledger must be an existing .jsonl file")
    ev = _ledger_module()
    # EvidenceLedger.__init__ creates and touches the file (it is the writer). Build the reader
    # without running it, so a read never creates or modifies anything; _entries() is the
    # module's own verifying reader.
    led = ev.EvidenceLedger.__new__(ev.EvidenceLedger)
    led.path = Path(path)
    try:
        entries = led._entries()
    except ev.LedgerError as e:
        raise EvidenceUnavailable("TAMPERED", str(e)) from None
    except (ValueError, KeyError, TypeError) as e:
        raise EvidenceUnavailable("MALFORMED", f"ledger unreadable: {type(e).__name__}: {e}") from None
    return {
        "ledger": os.path.relpath(os.path.abspath(path), REPO).replace(os.sep, "/"),
        "verified_by": "heatcheck.ledger.evidence: evidence_id and entry_hash recomputed for every line",
        "entries": entries,
    }

"""Add hash-chain fields to a legacy (unchained) evidence ledger, in line order.

    uv run --frozen python tools/migrate_ledger_chain.py <ledger.jsonl> [...]

For each line it first verifies the legacy rules (evidence_id and entry_hash recomputed). It
then adds only ``prev_chain_hash`` and ``chain_hash``. The identity, evidence_id, entry_hash
and created_at_utc are byte-for-byte the same values. The result must verify with the
chained reader, or nothing is written. The old file's sha256 and the new head are printed;
git history keeps the original bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatcheck.contracts.records import loads_strict  # noqa: E402
from heatcheck.ledger.evidence import (  # noqa: E402
    GENESIS,
    LEGACY_KEYS,
    EvidenceLedger,
    LedgerError,
    chain_hash,
    entry_hash,
    evidence_id,
)


def migrate(path: Path) -> None:
    raw = path.read_bytes()
    out, prev = [], GENESIS
    for n, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        e = loads_strict(line)
        if set(e) != LEGACY_KEYS:
            raise LedgerError(f"{path} line {n}: not a legacy line (fields {sorted(e)}); refusing")
        if evidence_id(e["identity"]) != e["evidence_id"] or \
                entry_hash(e["identity"], e["created_at_utc"]) != e["entry_hash"]:
            raise LedgerError(f"{path} line {n}: fails legacy verification; refusing")
        e["prev_chain_hash"] = prev
        e["chain_hash"] = prev = chain_hash(prev, e["entry_hash"])
        out.append(json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                              allow_nan=False) + "\n")
    tmp = path.with_name(path.name + ".migrating")
    tmp.write_text("".join(out), encoding="utf-8", newline="\n")
    try:
        check = EvidenceLedger.open_readonly(tmp).all()
        old = [loads_strict(x) for x in raw.decode("utf-8").splitlines() if x.strip()]
        assert [(c["evidence_id"], c["entry_hash"], c["created_at_utc"], c["identity"]) for c in check] == \
            [(o["evidence_id"], o["entry_hash"], o["created_at_utc"], o["identity"]) for o in old]
    except Exception:
        tmp.unlink()
        raise
    os.replace(tmp, path)
    print(f"{path}: {len(out)} lines; old sha256 {hashlib.sha256(raw).hexdigest()}; "
          f"new sha256 {hashlib.sha256(path.read_bytes()).hexdigest()}; head {prev}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        migrate(Path(p))

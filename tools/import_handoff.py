"""Import a team handoff ZIP byte-for-byte under incoming/<name>/ and write an import manifest.

    python -I tools/import_handoff.py <zip> <top_dir_in_zip> <dest_name> [--omit-glob GLOB ...]

Every zip member is hashed. Omitted members (e.g. raw upstream archives whose redistribution
rights are unverified) are listed with their sha256 so the omission is auditable. Members with
absolute paths or '..' are refused. Nothing is executed from the archive.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    zpath, top, dest_name = Path(argv[0]), argv[1].rstrip("/"), argv[2]
    omit = [argv[i + 1] for i, a in enumerate(argv) if a == "--omit-glob"]
    dest = ROOT / "incoming" / dest_name
    if dest.exists():
        print(f"refusing: {dest} already exists")
        return 1
    zip_sha = hashlib.sha256(zpath.read_bytes()).hexdigest()
    files, omitted = [], []
    with zipfile.ZipFile(zpath) as zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            if info.is_dir():
                continue
            p = PurePosixPath(info.filename)
            if p.is_absolute() or ".." in p.parts or p.parts[0] != top:
                print(f"refusing unsafe member {info.filename!r}")
                return 1
            rel = PurePosixPath(*p.parts[1:]).as_posix()
            data = zf.read(info)
            entry = {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            if any(fnmatch.fnmatch(rel, g) for g in omit):
                omitted.append(entry)
                continue
            target = dest.joinpath(*PurePosixPath(rel).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files.append(entry)
    manifest = {
        "source_zip": zpath.name,
        "source_zip_sha256": zip_sha,
        "zip_top_dir": top,
        "dest": f"incoming/{dest_name}",
        "imported": files,
        "omitted": omitted,
        "omit_globs": omit,
        "note": "Byte-for-byte import; files are exempt from EOL conversion (.gitattributes).",
    }
    out = ROOT / "incoming" / f"{dest_name}.IMPORT.json"
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"imported {len(files)} files, omitted {len(omitted)}; zip sha256 {zip_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

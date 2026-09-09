"""One atomic text write, shared by everything that mutates state on disk.

The ledger (`data/overrides.yaml`), the published snapshot, the promoted policy and the
ledger artefacts are all read by another process — the review tool's watch thread, a
second request, an auditor opening the file — so none of them may ever be seen half-written.
Write to a temp file in the same directory, then rename: POSIX and NTFS both make the
rename atomic, and a crash mid-write leaves the old file intact and a `.tmp` to sweep.
"""
from __future__ import annotations

import os
from pathlib import Path


def write_atomically(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

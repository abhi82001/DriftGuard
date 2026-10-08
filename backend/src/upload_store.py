"""Per-assessment upload storage with sanitized names and owner-scoped, removable directories.

Layout: <root>/u<user_id>/<assessment_id>/{NNN_<safe-name>, manifest.json, job.json, ckpt_*.json}.
Everything about one assessment lives in one directory, so deleting it removes files,
manifest and job checkpoints together. Original filenames are kept only in the manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import unicodedata
from pathlib import Path

_AID = re.compile(r"^[0-9a-f]{32}$")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def sanitize_filename(name: str, max_len: int = 100) -> str:
    """ASCII-only, no separators/control chars/leading dots/reserved device names; extension kept."""
    base = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    base = base.replace("\\", "/").rsplit("/", 1)[-1]
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "file"
    ext = re.sub(r"[^A-Za-z0-9]", "", ext).lower()[:10]
    if stem.lower() in _RESERVED:
        stem = "_" + stem
    stem = stem[: max(1, max_len - len(ext) - 1)]
    return f"{stem}.{ext}" if ext else stem


def default_root() -> Path:
    explicit = os.getenv("DRIFTGUARD_UPLOAD_DIR")
    if explicit:
        return Path(explicit)
    db = os.getenv("DRIFTGUARD_DATABASE_URL") or os.getenv("DRIFTGUARD_DB") or ""
    if db.startswith("sqlite:///"):
        db = db[len("sqlite:///"):]
    return (Path(db).expanduser().resolve().parent if db else Path.cwd()) / "driftguard_uploads"


class UploadStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else default_root()

    def dir_for(self, user_id: int, aid: str) -> Path:
        if not _AID.match(str(aid)) or not isinstance(user_id, int) or user_id < 0:
            raise ValueError("invalid assessment or user id")
        path = (self.root / f"u{user_id}" / aid).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("path escapes upload root")
        return path

    def save(self, user_id: int, aid: str, payloads) -> list[dict]:
        d = self.dir_for(user_id, aid)
        d.mkdir(parents=True, exist_ok=True)
        manifest = []
        for i, (name, data) in enumerate(payloads):
            stored = f"{i:03d}_{sanitize_filename(name)}"
            (d / stored).write_bytes(data)
            manifest.append(dict(original=name, stored=stored, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data)))
        (d / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        return manifest

    def load(self, user_id: int, aid: str) -> list[tuple[str, bytes]]:
        d = self.dir_for(user_id, aid)
        try:
            manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for m in manifest:
            data = (d / m["stored"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != m["sha256"]:
                raise ValueError("stored upload failed its integrity check")
            out.append((m["original"], data))
        return out

    def exists(self, user_id: int, aid: str) -> bool:
        return self.dir_for(user_id, aid).is_dir()

    def delete(self, user_id: int, aid: str) -> bool:
        d = self.dir_for(user_id, aid)
        if not d.is_dir():
            return False
        shutil.rmtree(d)
        return True

    def sweep(self, user_id: int, live_aids: set[str], grace_seconds: float = 600.0) -> int:
        """Remove directories of this user whose assessment no longer exists (e.g. dropped by the history cap).

        Directories touched within `grace_seconds`, or with a queued/running job, are never removed: the saved
        row is written after the files, so a brand-new directory legitimately has no row yet."""
        base = self.root / f"u{user_id}"
        removed = 0
        if not base.is_dir():
            return 0
        now = time.time()
        for child in base.iterdir():
            if not (child.is_dir() and _AID.match(child.name)) or child.name in live_aids:
                continue
            if now - max([child.stat().st_mtime] + [f.stat().st_mtime for f in child.iterdir()]) < grace_seconds:
                continue
            try:
                if json.loads((child / "job.json").read_text(encoding="utf-8")).get("state") in ("queued", "running"):
                    continue
            except (OSError, ValueError):
                pass
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        return removed

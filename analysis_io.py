"""Shared input verification and atomic report writing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any


def read_input(path: Path, expected_sha256: str | None) -> tuple[bytes, dict[str, Any]]:
    """Read exact bytes and report verification; callers decide how to handle mismatches."""
    content = path.read_bytes()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    digest_verified = bool(
        expected_sha256
        and re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256)
        and actual_sha256 == expected_sha256.lower()
    )
    return content, {
        "file": str(path),
        "sha256": actual_sha256,
        "expected_sha256": expected_sha256,
        "digest_verified": digest_verified,
    }


def write_text(path: Path, content: str) -> None:
    """Replace a UTF-8 file atomically, leaving no partial report on write failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, indent=2) + "\n")

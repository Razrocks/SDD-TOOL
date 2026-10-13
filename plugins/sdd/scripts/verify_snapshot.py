"""Local, on-demand snapshot integrity checker. Stdlib only; no network or model calls.

Manifest format (schema "sdd-snapshot/1"), paths relative to the manifest's directory:

{
  "schema": "sdd-snapshot/1",
  "created_at": "2026-10-11T12:00:00Z",
  "complete": false,
  "scope": "what was requested",
  "files": [
    {"path": "docs/<id>.md", "sha256": "<64 lowercase hex>", "bytes": 123,
     "linear_id": "<id or null>", "updated_at": "<ISO-8601 with zone>", "fetched_at": "<ISO-8601 with zone>"}
  ]
}

Exit codes: 0 valid, 1 invalid, 2 manifest unreadable or usage error.
VALID means local bytes match the manifest. It does not prove export completeness,
source authenticity, human approval, citation support, or factual truth.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime
from pathlib import Path

SCHEMA = "sdd-snapshot/1"
MAX_MANIFEST_BYTES = 10 * 1024 * 1024
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_FILES = 100_000
MAX_PATH_LEN = 1024
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DISCLAIMER = (
    "Local file integrity only. Does not prove export completeness, source authenticity, "
    "human approval, citation support, or factual truth."
)


class ManifestUnreadable(Exception):
    pass


def valid_timestamp(value):
    if not isinstance(value, str) or not value:
        return False
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def path_problem(path):
    if not isinstance(path, str) or not path:
        return "path must be a non-empty string"
    if len(path) > MAX_PATH_LEN:
        return "path too long"
    if "\\" in path or "\x00" in path or ":" in path:
        return "path contains backslash, NUL, or colon (drive letters and streams not allowed)"
    if path.startswith("/"):
        return "absolute path not allowed"
    for part in path.split("/"):
        if part in ("", ".", ".."):
            return "path has empty, '.' or '..' segment"
    return None


def load_manifest(manifest_path):
    try:
        size = os.stat(manifest_path).st_size
    except OSError as exc:
        raise ManifestUnreadable(f"cannot stat manifest: {exc.strerror}")
    if size > MAX_MANIFEST_BYTES:
        raise ManifestUnreadable(f"manifest larger than {MAX_MANIFEST_BYTES} bytes")
    try:
        raw = Path(manifest_path).read_bytes()
    except OSError as exc:
        raise ManifestUnreadable(f"cannot read manifest: {exc.strerror}")
    return raw


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_file(base, entry, rel):
    full = base / rel
    try:
        info = os.lstat(full)
    except FileNotFoundError:
        return "file missing"
    except OSError as exc:
        return f"file unreadable: {exc.strerror}"
    if stat.S_ISLNK(info.st_mode):
        return "symlink not allowed"
    if not stat.S_ISREG(info.st_mode):
        return "not a regular file"
    try:
        resolved = full.resolve(strict=True)
    except OSError as exc:
        return f"cannot resolve: {exc.strerror}"
    common = os.path.commonpath([str(resolved), str(base)])
    if os.path.normcase(common) != os.path.normcase(str(base)):
        return "resolves outside snapshot directory"
    if info.st_size > MAX_FILE_BYTES:
        return f"file larger than {MAX_FILE_BYTES} bytes"
    if info.st_size != entry["bytes"]:
        return f"size {info.st_size} != manifest {entry['bytes']}"
    try:
        actual = sha256_of(full)
    except OSError as exc:
        return f"file unreadable: {exc.strerror}"
    if actual != entry["sha256"]:
        return "sha256 mismatch"
    return None


def verify(manifest_path):
    """Return (errors, warnings). Raises ManifestUnreadable if the manifest cannot be read."""
    errors, warnings = [], []
    raw = load_manifest(manifest_path)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"manifest is not valid UTF-8 JSON: {exc}"], warnings

    if not isinstance(data, dict):
        return ["manifest top level must be an object"], warnings
    if data.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}")
    if not valid_timestamp(data.get("created_at")):
        errors.append("created_at must be ISO-8601 with timezone")
    if not isinstance(data.get("complete"), bool):
        errors.append("complete must be true or false")
    files = data.get("files")
    if not isinstance(files, list):
        errors.append("files must be a list")
        return errors, warnings
    if len(files) > MAX_FILES:
        errors.append(f"more than {MAX_FILES} files")
        return errors, warnings

    base = Path(manifest_path).resolve().parent
    seen_paths, seen_ids = set(), set()
    for index, entry in enumerate(files):
        label = f"files[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label}: must be an object")
            continue
        rel = entry.get("path")
        problem = path_problem(rel)
        if problem:
            errors.append(f"{label}: {problem}")
            continue
        label = f"{label} {rel}"
        key = rel.casefold()
        if key in seen_paths:
            errors.append(f"{label}: duplicate path")
            continue
        seen_paths.add(key)

        entry_ok = True
        if not isinstance(entry.get("sha256"), str) or not HEX64.match(entry["sha256"]):
            errors.append(f"{label}: sha256 must be 64 lowercase hex characters")
            entry_ok = False
        size = entry.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            errors.append(f"{label}: bytes must be a non-negative integer")
            entry_ok = False
        if "linear_id" not in entry:
            errors.append(f"{label}: linear_id key required (null allowed)")
            entry_ok = False
        linear_id = entry.get("linear_id")
        if linear_id is not None:
            if not isinstance(linear_id, str) or not linear_id:
                errors.append(f"{label}: linear_id must be a non-empty string or null")
                entry_ok = False
            elif linear_id in seen_ids:
                errors.append(f"{label}: duplicate linear_id")
                entry_ok = False
            else:
                seen_ids.add(linear_id)
            for field in ("updated_at", "fetched_at"):
                if not valid_timestamp(entry.get(field)):
                    errors.append(f"{label}: {field} must be ISO-8601 with timezone")
                    entry_ok = False
        if entry_ok:
            problem = check_file(base, entry, rel)
            if problem:
                errors.append(f"{label}: {problem}")

    if data.get("complete") is False:
        warnings.append("PARTIAL: manifest declares the export incomplete")
    return errors, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify a local snapshot manifest. " + DISCLAIMER)
    parser.add_argument("manifest", help="path to manifest.json")
    args = parser.parse_args(argv)
    try:
        errors, warnings = verify(args.manifest)
    except ManifestUnreadable as exc:
        print(f"ERROR: {exc}")
        return 2
    for message in errors:
        print(f"ERROR: {message}")
    for message in warnings:
        print(f"WARNING: {message}")
    print("RESULT: INVALID" if errors else "RESULT: VALID (local integrity only)")
    print(DISCLAIMER)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib import request

PIN_PATH = Path(__file__).resolve().parent.parent / "ludusavi-bundle.json"
CACHE_ROOT = Path("/var/tmp/sdh_ludusavi/ludusavi-bundle")


def verify_sha256(path: Path, expected: str) -> None:
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"SHA256 mismatch for {path}: expected {expected}, got {actual}")


def fetch_artifact(url: str, expected: str, path: Path) -> Path:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"Cached artifact is not a regular file: {path}")
    if path.is_file():
        verify_sha256(path, expected)
        return path

    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".download-", delete=False) as target:
        temporary = Path(target.name)
        try:
            with request.urlopen(url, timeout=60) as source:
                shutil.copyfileobj(source, target)
            target.flush()
            verify_sha256(temporary, expected)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


def fetch_bundle(
    pin_path: Path = PIN_PATH, cache_root: Path = CACHE_ROOT
) -> tuple[Path, Path, Path]:
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    version = pin["version"]
    if not isinstance(version, str) or version in ("", ".", "..") or Path(version).name != version:
        raise ValueError("Invalid Ludusavi bundle version")
    cache = cache_root / version
    cache.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for key, filename in (
        ("archive", "archive.tar.gz"),
        ("license", "LICENSE"),
        ("third_party", "third-party.txt"),
    ):
        artifact = pin[key]
        artifacts[key] = fetch_artifact(artifact["url"], artifact["sha256"], cache / filename)

    binary = cache / "ludusavi"
    if binary.is_symlink() or (binary.exists() and not binary.is_file()):
        raise ValueError(f"Cached binary is not a regular file: {binary}")
    with tarfile.open(artifacts["archive"], mode="r:gz") as archive:
        members = archive.getmembers()
        if (
            len(members) != 1
            or members[0].name != "ludusavi"
            or members[0].type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
        ):
            raise ValueError("Ludusavi archive must contain only the regular ludusavi member")
        if binary.is_file():
            verify_sha256(binary, pin["binary_sha256"])
        else:
            source = archive.extractfile(members[0])
            if source is None:
                raise ValueError("Unable to read Ludusavi archive member")
            with (
                source,
                tempfile.NamedTemporaryFile(dir=cache, prefix=".ludusavi-", delete=False) as target,
            ):
                temporary = Path(target.name)
                try:
                    shutil.copyfileobj(source, target)
                    target.flush()
                    verify_sha256(temporary, pin["binary_sha256"])
                    temporary.chmod(0o755)
                    temporary.replace(binary)
                finally:
                    temporary.unlink(missing_ok=True)
    binary.chmod(0o755)
    return binary, artifacts["license"], artifacts["third_party"]


def main() -> None:
    binary, license_path, third_party = fetch_bundle()
    print(f"LICENSE={license_path}")
    print(f"THIRD_PARTY={third_party}")
    print(binary)


if __name__ == "__main__":
    main()

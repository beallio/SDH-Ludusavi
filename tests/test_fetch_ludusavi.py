from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from urllib import request

import pytest

from scripts import fetch_ludusavi


BINARY = b"ludusavi fixture"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_tar(members: list[tuple[str, bytes, bytes]]) -> bytes:
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as archive:
        for name, member_type, data in members:
            info = tarfile.TarInfo(name)
            info.type = member_type
            if info.isfile():
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            else:
                info.linkname = "target"
                archive.addfile(info)
    return result.getvalue()


@pytest.fixture
def bundle(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    contents = {
        "archive": make_tar([("ludusavi", tarfile.REGTYPE, BINARY)]),
        "license": b"license fixture",
        "third_party": b"third-party fixture",
    }
    pin: dict[str, object] = {
        "version": "v-test",
        "source_repo": "https://example.invalid/ludusavi",
        "commit": "0123456789abcdef",
        "binary_sha256": sha256(BINARY),
    }
    for name, data in contents.items():
        path = source / name
        path.write_bytes(data)
        pin[name] = {"url": path.as_uri(), "sha256": sha256(data)}
    pin_path = tmp_path / "pin.json"
    pin_path.write_text(json.dumps(pin), encoding="utf-8")
    return pin_path, tmp_path / "cache"


def update_pin(pin_path: Path, name: str, data: bytes) -> None:
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    pin[name]["sha256"] = sha256(data)
    pin_path.write_text(json.dumps(pin), encoding="utf-8")


def test_fetch_verifies_and_reuses_cached_files(
    bundle: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    pin_path, cache = bundle
    binary, license_path, third_party = fetch_ludusavi.fetch_bundle(pin_path, cache)
    assert binary.read_bytes() == BINARY
    assert binary.stat().st_mode & 0o777 == 0o755
    assert license_path.read_bytes() == b"license fixture"
    assert third_party.read_bytes() == b"third-party fixture"

    def no_download(*args: object, **kwargs: object) -> None:
        raise AssertionError("verified cache should not download")

    monkeypatch.setattr(request, "urlopen", no_download)
    assert fetch_ludusavi.fetch_bundle(pin_path, cache) == (binary, license_path, third_party)


def test_fetch_cli_prints_bundle_paths(
    bundle: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = fetch_ludusavi.fetch_bundle(*bundle)
    monkeypatch.setattr(fetch_ludusavi, "fetch_bundle", lambda: paths)
    fetch_ludusavi.main()
    assert capsys.readouterr().out.splitlines() == [
        f"LICENSE={paths[1]}",
        f"THIRD_PARTY={paths[2]}",
        str(paths[0]),
    ]


@pytest.mark.parametrize("name", ["archive", "license", "third_party"])
def test_fetch_rejects_each_download_with_wrong_hash(bundle: tuple[Path, Path], name: str) -> None:
    pin_path, cache = bundle
    (pin_path.parent / "source" / name).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="(?i)sha256"):
        fetch_ludusavi.fetch_bundle(pin_path, cache)
    assert not (
        cache
        / "v-test"
        / {"archive": "archive.tar.gz", "license": "LICENSE", "third_party": "third-party.txt"}[
            name
        ]
    ).exists()


@pytest.mark.parametrize("name", ["archive.tar.gz", "LICENSE", "third-party.txt", "ludusavi"])
def test_fetch_rejects_corrupted_cached_files(bundle: tuple[Path, Path], name: str) -> None:
    pin_path, cache = bundle
    fetch_ludusavi.fetch_bundle(pin_path, cache)
    (cache / "v-test" / name).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="(?i)sha256"):
        fetch_ludusavi.fetch_bundle(pin_path, cache)


@pytest.mark.parametrize("name", ["archive.tar.gz", "LICENSE", "third-party.txt", "ludusavi"])
def test_fetch_rejects_symlinked_cached_files(bundle: tuple[Path, Path], name: str) -> None:
    pin_path, cache = bundle
    fetch_ludusavi.fetch_bundle(pin_path, cache)
    cached = cache / "v-test" / name
    target = cached.with_name("symlink-target")
    cached.rename(target)
    cached.symlink_to(target)
    with pytest.raises(ValueError, match="(?i)regular file"):
        fetch_ludusavi.fetch_bundle(pin_path, cache)


@pytest.mark.parametrize("version", ["", ".", "..", "../escape", "/absolute", "nested/path"])
def test_fetch_rejects_invalid_cache_version(bundle: tuple[Path, Path], version: str) -> None:
    pin_path, cache = bundle
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    pin["version"] = version
    pin_path.write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        fetch_ludusavi.fetch_bundle(pin_path, cache)


@pytest.mark.parametrize(
    "members",
    [
        [("ludusavi", tarfile.REGTYPE, BINARY), ("extra", tarfile.REGTYPE, b"extra")],
        [("../escape", tarfile.REGTYPE, BINARY)],
        [("/ludusavi", tarfile.REGTYPE, BINARY)],
        [("ludusavi", tarfile.SYMTYPE, b"")],
        [("ludusavi", tarfile.LNKTYPE, b"")],
        [("ludusavi", tarfile.DIRTYPE, b"")],
        [("ludusavi", tarfile.FIFOTYPE, b"")],
        [],
    ],
)
def test_fetch_rejects_unexpected_tar_members(
    bundle: tuple[Path, Path], members: list[tuple[str, bytes, bytes]]
) -> None:
    pin_path, cache = bundle
    data = make_tar(members)
    (pin_path.parent / "source" / "archive").write_bytes(data)
    update_pin(pin_path, "archive", data)
    with pytest.raises(ValueError, match="(?i)archive|tar|member"):
        fetch_ludusavi.fetch_bundle(pin_path, cache)
    assert not (cache / "v-test" / "ludusavi").exists()
    assert not (pin_path.parent / "escape").exists()


def test_fetch_rejects_wrong_extracted_binary_hash(bundle: tuple[Path, Path]) -> None:
    pin_path, cache = bundle
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    pin["binary_sha256"] = sha256(b"different binary")
    pin_path.write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(ValueError, match="(?i)sha256"):
        fetch_ludusavi.fetch_bundle(pin_path, cache)
    assert not (cache / "v-test" / "ludusavi").exists()

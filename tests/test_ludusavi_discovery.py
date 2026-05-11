from __future__ import annotations

import shutil
import subprocess

import pytest

from pyludusavi import discovery


def test_explicit_flatpak_id_uses_absolute_flatpak_when_path_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(shutil, "which", lambda name: None)

    def verify(prefix: list[str]) -> bool:
        calls.append(prefix)
        return prefix == ["/usr/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"]

    monkeypatch.setattr(discovery, "_verify", verify)

    assert discovery.find_ludusavi(
        explicit_flatpak_id="com.github.mtkennerly.ludusavi",
    ) == ["/usr/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"]
    assert ["/usr/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"] in calls


def test_default_flatpak_lookup_uses_absolute_flatpak_when_path_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(
        discovery,
        "_verify",
        lambda prefix: prefix == ["/usr/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"],
    )

    assert discovery.find_ludusavi() == [
        "/usr/bin/flatpak",
        "run",
        "com.github.mtkennerly.ludusavi",
    ]


def test_default_flatpak_lookup_falls_back_when_path_flatpak_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def which(name: str) -> str | None:
        if name == "flatpak":
            return "flatpak"
        return None

    def verify(prefix: list[str]) -> bool:
        calls.append(prefix)
        return prefix == ["/usr/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"]

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(discovery, "_verify", verify)

    assert discovery.find_ludusavi() == [
        "/usr/bin/flatpak",
        "run",
        "com.github.mtkennerly.ludusavi",
    ]
    assert calls[:2] == [
        ["flatpak", "run", "com.github.mtkennerly.ludusavi"],
        ["/usr/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"],
    ]


def test_default_flatpak_lookup_raises_when_all_candidates_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(shutil, "which", lambda name: None)

    def verify(prefix: list[str]) -> bool:
        calls.append(prefix)
        return False

    monkeypatch.setattr(discovery, "_verify", verify)

    with pytest.raises(discovery.LudusaviNotFoundError):
        discovery.find_ludusavi()

    assert calls == [
        ["/usr/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"],
        ["/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"],
        ["/usr/local/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"],
    ]


def test_verify_uses_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_timeout: list[float] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen_timeout.append(float(kwargs["timeout"]))
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)

    assert discovery._verify(["/usr/bin/flatpak", "run", "com.github.mtkennerly.ludusavi"]) is False
    assert seen_timeout == [5.0]

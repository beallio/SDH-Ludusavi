from __future__ import annotations

import shutil

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

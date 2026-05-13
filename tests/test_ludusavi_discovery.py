from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pyludusavi import discovery

APP_ID = "com.github.mtkennerly.ludusavi"
DECK_HOME = "/home/deck"
DECK_USER_FLATPAK_PREFIX = [
    "/usr/bin/env",
    f"HOME={DECK_HOME}",
    f"XDG_DATA_HOME={DECK_HOME}/.local/share",
    f"FLATPAK_USER_DIR={DECK_HOME}/.local/share/flatpak",
    "/usr/bin/flatpak",
    "run",
    "--user",
    APP_ID,
]


def test_explicit_flatpak_id_uses_absolute_flatpak_when_path_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(shutil, "which", lambda name: None)

    def verify(prefix: list[str]) -> bool:
        calls.append(prefix)
        return prefix == ["/usr/bin/flatpak", "run", APP_ID]

    monkeypatch.setattr(discovery, "_verify", verify)

    assert discovery.find_ludusavi(
        explicit_flatpak_id=APP_ID,
    ) == ["/usr/bin/flatpak", "run", APP_ID]
    assert ["/usr/bin/flatpak", "run", APP_ID] in calls


def test_explicit_flatpak_id_prefers_decky_user_flatpak_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(shutil, "which", lambda name: None)

    def verify(prefix: list[str]) -> bool:
        calls.append(prefix)
        return prefix == DECK_USER_FLATPAK_PREFIX

    monkeypatch.setattr(discovery, "_verify", verify)

    assert (
        discovery.find_ludusavi(
            explicit_flatpak_id=APP_ID,
            flatpak_user_home=DECK_HOME,
        )
        == DECK_USER_FLATPAK_PREFIX
    )
    assert calls[0] == DECK_USER_FLATPAK_PREFIX


def test_default_flatpak_lookup_uses_absolute_flatpak_when_path_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(
        discovery,
        "_verify",
        lambda prefix: prefix == ["/usr/bin/flatpak", "run", APP_ID],
    )

    assert discovery.find_ludusavi() == [
        "/usr/bin/flatpak",
        "run",
        APP_ID,
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
        return prefix == ["/usr/bin/flatpak", "run", APP_ID]

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(discovery, "_verify", verify)

    assert discovery.find_ludusavi() == [
        "/usr/bin/flatpak",
        "run",
        APP_ID,
    ]
    assert calls[:2] == [
        ["flatpak", "run", APP_ID],
        ["/usr/bin/flatpak", "run", APP_ID],
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
        ["/usr/bin/flatpak", "run", APP_ID],
        ["/bin/flatpak", "run", APP_ID],
        ["/usr/local/bin/flatpak", "run", APP_ID],
    ]


def test_verify_uses_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_timeout: list[float] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen_timeout.append(float(kwargs["timeout"]))
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)

    assert discovery._verify(["/usr/bin/flatpak", "run", APP_ID]) is False
    assert seen_timeout == [5.0]


def test_find_ludusavi_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def exists(path: Path) -> bool:
        return str(path) == "/usr/bin/ludusavi"

    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(os, "access", lambda path, mode: True)

    assert discovery.find_ludusavi_binary(APP_ID, None) == "/usr/bin/ludusavi"


def test_find_ludusavi_binary_flatpak(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = (
        "/var/lib/flatpak/app/com.github.mtkennerly.ludusavi/current/active/files/bin/ludusavi"
    )

    def exists(path: Path) -> bool:
        return str(path) == expected

    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(os, "access", lambda path, mode: True)

    assert discovery.find_ludusavi_binary(APP_ID, None) == expected


def test_find_ludusavi_config_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = "/home/deck/.var/app/com.github.mtkennerly.ludusavi/config/ludusavi"

    def exists(path: Path) -> bool:
        return str(path) == expected

    monkeypatch.setattr(Path, "exists", exists)

    assert discovery.find_ludusavi_config_dir(APP_ID, "/home/deck", "flatpak-path") == expected


def test_find_ludusavi_config_dir_returns_none_when_not_flatpak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert discovery.find_ludusavi_config_dir(APP_ID, "/home/deck", "/usr/bin/ludusavi") is None

from __future__ import annotations

import shutil
import inspect

import pytest

from pyludusavi import discovery

APP_ID = "com.github.mtkennerly.ludusavi"


def test_find_ludusavi_signature_is_clean_upstream() -> None:
    signature = inspect.signature(discovery.find_ludusavi)

    assert list(signature.parameters) == [
        "explicit_path",
        "explicit_flatpak_id",
        "flatpak_id",
        "env",
    ]
    assert not hasattr(discovery, "_should_sudo")
    assert not hasattr(discovery, "_flatpak_user_env")
    assert not hasattr(discovery, "find_ludusavi_binary")
    assert not hasattr(discovery, "find_ludusavi_config_dir")


def test_explicit_flatpak_id_uses_absolute_flatpak_when_path_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(discovery.LudusaviNotFoundError):
        discovery.find_ludusavi(explicit_flatpak_id=APP_ID)


def test_explicit_flatpak_id_uses_path_flatpak_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def which(name: str) -> str | None:
        if name == "flatpak":
            return "flatpak"
        return None

    def verify(prefix: list[str], env: dict[str, str] | None = None) -> bool:
        calls.append(prefix)
        assert env is None
        return prefix == ["flatpak", "run", APP_ID]

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(discovery, "_verify", verify)

    assert discovery.find_ludusavi(explicit_flatpak_id=APP_ID) == ["flatpak", "run", APP_ID]
    assert calls == [["flatpak", "run", APP_ID]]


def test_default_flatpak_lookup_raises_when_all_candidates_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(shutil, "which", lambda name: None)

    def verify(prefix: list[str], env: dict[str, str] | None = None) -> bool:
        calls.append(prefix)
        assert env is None
        return False

    monkeypatch.setattr(discovery, "_verify", verify)

    with pytest.raises(discovery.LudusaviNotFoundError):
        discovery.find_ludusavi()

    assert calls == []

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdh_ludusavi.status_theme import (
    ThemeOwnershipError,
    install_status_theme,
    uninstall_status_theme,
)


THEME_NAME = "SDH-Ludusavi Status"


def theme_preferences_dir(decky_home: Path) -> Path:
    return decky_home / "data" / "SDH-Ludusavi"


def bundled_theme(tmp_path: Path) -> Path:
    source = tmp_path / "plugin" / "theme"
    source.mkdir(parents=True)
    (source / "theme.json").write_text(
        json.dumps({"name": THEME_NAME, "manifest_version": 5}), encoding="utf-8"
    )
    (source / "clean.css").write_text(".row { background: #123; }", encoding="utf-8")
    (source / "custom.css").write_text(".row { background: #abc; }", encoding="utf-8")
    return source


def test_first_install_adds_theme_without_css_loader_plugin(tmp_path: Path) -> None:
    source = bundled_theme(tmp_path)
    decky_home = tmp_path / "homebrew"
    destination = decky_home / "themes" / THEME_NAME

    install_status_theme(source, decky_home, theme_preferences_dir(decky_home))

    assert (
        json.loads((destination / "theme.json").read_text(encoding="utf-8"))["name"] == THEME_NAME
    )
    assert (destination / "clean.css").read_bytes() == (source / "clean.css").read_bytes()
    assert (destination / "custom.css").read_bytes() == (source / "custom.css").read_bytes()
    assert json.loads((destination / "config_USER.json").read_text(encoding="utf-8")) == {
        "active": True
    }


def test_update_preserves_css_loader_choices_and_user_files(tmp_path: Path) -> None:
    source = bundled_theme(tmp_path)
    decky_home = tmp_path / "homebrew"
    destination = decky_home / "themes" / THEME_NAME
    install_status_theme(source, decky_home, theme_preferences_dir(decky_home))
    choices = {
        "active": False,
        "Save Status": {"value": "Custom", "components": {"Background": "#23456789"}},
    }
    (destination / "config_USER.json").write_text(json.dumps(choices), encoding="utf-8")
    (destination / "PRIORITY").write_text("25\n", encoding="utf-8")
    (source / "custom.css").write_text(".row { background: #def; }", encoding="utf-8")

    install_status_theme(source, decky_home, theme_preferences_dir(decky_home))
    install_status_theme(source, decky_home, theme_preferences_dir(decky_home))

    assert (destination / "custom.css").read_text(encoding="utf-8") == ".row { background: #def; }"
    assert json.loads((destination / "config_USER.json").read_text(encoding="utf-8")) == choices
    assert (destination / "PRIORITY").read_text(encoding="utf-8") == "25\n"


def test_existing_unowned_theme_is_not_overwritten_or_deleted(tmp_path: Path) -> None:
    source = bundled_theme(tmp_path)
    decky_home = tmp_path / "homebrew"
    destination = decky_home / "themes" / THEME_NAME
    destination.mkdir(parents=True)
    (destination / "theme.json").write_text("user theme", encoding="utf-8")

    with pytest.raises(ThemeOwnershipError):
        install_status_theme(source, decky_home, theme_preferences_dir(decky_home))
    uninstall_status_theme(decky_home, theme_preferences_dir(decky_home))

    assert (destination / "theme.json").read_text(encoding="utf-8") == "user theme"


def test_theme_directory_symlink_cannot_redirect_install_or_uninstall(tmp_path: Path) -> None:
    source = bundled_theme(tmp_path)
    decky_home = tmp_path / "homebrew"
    themes = decky_home / "themes"
    themes.mkdir(parents=True)
    other = tmp_path / "unrelated"
    other.mkdir()
    (other / "sentinel").write_text("keep", encoding="utf-8")
    (themes / THEME_NAME).symlink_to(other, target_is_directory=True)

    with pytest.raises(ThemeOwnershipError):
        install_status_theme(source, decky_home, theme_preferences_dir(decky_home))
    uninstall_status_theme(decky_home, theme_preferences_dir(decky_home))

    assert (other / "sentinel").read_text(encoding="utf-8") == "keep"
    assert (themes / THEME_NAME).is_symlink()


def test_uninstall_removes_owned_theme_but_not_other_themes(tmp_path: Path) -> None:
    source = bundled_theme(tmp_path)
    decky_home = tmp_path / "homebrew"
    other = decky_home / "themes" / "Clean Gameview"
    other.mkdir(parents=True)
    (other / "theme.json").write_text("upstream", encoding="utf-8")
    install_status_theme(source, decky_home, theme_preferences_dir(decky_home))
    destination = decky_home / "themes" / THEME_NAME
    (destination / "config_USER.json").write_text('{"active":false}', encoding="utf-8")
    (destination / "PRIORITY").write_text("25\n", encoding="utf-8")

    uninstall_status_theme(decky_home, theme_preferences_dir(decky_home))

    assert not destination.exists()
    assert (other / "theme.json").read_text(encoding="utf-8") == "upstream"


def test_uninstall_and_reinstall_restore_custom_choices_and_load_order(tmp_path: Path) -> None:
    source = bundled_theme(tmp_path)
    decky_home = tmp_path / "homebrew"
    preferences = theme_preferences_dir(decky_home)
    install_status_theme(source, decky_home, preferences)
    destination = decky_home / "themes" / THEME_NAME
    choices = {
        "active": False,
        "Save Status": {"value": "Custom", "components": {"Text Color": "#9abcdef0"}},
    }
    (destination / "config_USER.json").write_text(json.dumps(choices), encoding="utf-8")
    (destination / "PRIORITY").write_text("25\n", encoding="utf-8")

    uninstall_status_theme(decky_home, preferences)
    assert not destination.exists()

    install_status_theme(source, decky_home, preferences)
    assert json.loads((destination / "config_USER.json").read_text(encoding="utf-8")) == choices
    assert (destination / "PRIORITY").read_text(encoding="utf-8") == "25\n"


def test_uninstall_keeps_theme_if_user_added_files(tmp_path: Path) -> None:
    source = bundled_theme(tmp_path)
    decky_home = tmp_path / "homebrew"
    install_status_theme(source, decky_home, theme_preferences_dir(decky_home))
    destination = decky_home / "themes" / THEME_NAME
    (destination / "user.css").write_text(".mine {}", encoding="utf-8")

    with pytest.raises(ThemeOwnershipError):
        uninstall_status_theme(decky_home, theme_preferences_dir(decky_home))

    assert (destination / "user.css").read_text(encoding="utf-8") == ".mine {}"
    assert (destination / "theme.json").exists()


def test_uninstall_does_not_follow_redirected_preferences_backup(tmp_path: Path) -> None:
    source = bundled_theme(tmp_path)
    decky_home = tmp_path / "homebrew"
    preferences = theme_preferences_dir(decky_home)
    install_status_theme(source, decky_home, preferences)
    preferences.mkdir(parents=True)
    other = tmp_path / "private-data"
    other.write_text("keep", encoding="utf-8")
    (preferences / "status-theme-choices.json").symlink_to(other)

    with pytest.raises(ThemeOwnershipError):
        uninstall_status_theme(decky_home, preferences)

    assert other.read_text(encoding="utf-8") == "keep"
    assert (decky_home / "themes" / THEME_NAME / "theme.json").exists()

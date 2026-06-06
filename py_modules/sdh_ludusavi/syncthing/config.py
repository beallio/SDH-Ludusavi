from __future__ import annotations

import logging
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from ._types import (
    SyncthingConfig,
    COMMON_SYNCTHING_FLATPAK_IDS,
    DEFAULT_API_URL,
    bool_from_xml_attr,
)

logger = logging.getLogger(__name__)


def api_url_from_gui_address(address: str | None, tls: bool) -> str | None:
    if address is None:
        return None
    value = address.strip()
    if not value:
        return None

    if "://" in value:
        return value.rstrip("/")

    if value.startswith(":"):
        value = "127.0.0.1" + value
    elif value.startswith("0.0.0.0:"):
        value = "127.0.0.1:" + value.split(":", 1)[1]
    elif value == "0.0.0.0":
        value = "127.0.0.1:8384"
    elif value.startswith("[::]:"):
        value = "[::1]:" + value.rsplit(":", 1)[1]
    elif value == "[::]":
        value = "[::1]:8384"

    scheme = "https" if tls else "http"
    return f"{scheme}://{value}".rstrip("/")


def flatpak_ids_to_probe(extra_ids: Iterable[str] | None = None) -> list[str]:
    ids: list[str] = []
    current_flatpak_id = os.environ.get("FLATPAK_ID")
    if current_flatpak_id:
        ids.append(current_flatpak_id)
    ids.extend(COMMON_SYNCTHING_FLATPAK_IDS)
    if extra_ids:
        ids.extend(extra_ids)

    deduped: list[str] = []
    seen: set[str] = set()
    for app_id in ids:
        app_id = app_id.strip()
        if app_id and app_id not in seen:
            seen.add(app_id)
            deduped.append(app_id)
    return deduped


def candidate_config_files(extra_flatpak_ids: Iterable[str] | None = None) -> list[Path]:
    home = Path.home()
    paths: list[Path] = []

    explicit_config = os.environ.get("SYNCTHING_CONFIG_FILE")
    if explicit_config:
        paths.append(Path(explicit_config).expanduser())

    if os.environ.get("STCONFDIR"):
        paths.append(Path(os.environ["STCONFDIR"]).expanduser() / "config.xml")
    if os.environ.get("STHOMEDIR"):
        paths.append(Path(os.environ["STHOMEDIR"]).expanduser() / "config.xml")

    if sys.platform == "darwin":
        paths.append(home / "Library/Application Support/Syncthing/config.xml")
    elif os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        app_data = os.environ.get("APPDATA")
        if local_app_data:
            paths.append(Path(local_app_data) / "Syncthing/config.xml")
        if app_data:
            paths.append(Path(app_data) / "Syncthing/config.xml")
    else:
        xdg_state = os.environ.get("XDG_STATE_HOME")
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        xdg_data = os.environ.get("XDG_DATA_HOME")

        if xdg_state:
            paths.append(Path(xdg_state).expanduser() / "syncthing/config.xml")
        paths.append(home / ".local/state/syncthing/config.xml")

        if xdg_config:
            paths.append(Path(xdg_config).expanduser() / "syncthing/config.xml")
        paths.append(home / ".config/syncthing/config.xml")

        if xdg_data:
            paths.append(Path(xdg_data).expanduser() / "syncthing/config.xml")
        paths.append(home / ".local/share/syncthing/config.xml")

    for app_id in flatpak_ids_to_probe(extra_flatpak_ids):
        base = home / ".var/app" / app_id
        paths.extend(
            [
                base / "config/syncthing/config.xml",
                base / "data/syncthing/config.xml",
                base / ".config/syncthing/config.xml",
                base / ".local/state/syncthing/config.xml",
                base / ".local/share/syncthing/config.xml",
            ]
        )

    deduped_paths: list[Path] = []
    seen_paths: set[str] = set()
    for path in paths:
        expanded = path.expanduser()
        key = str(expanded)
        if key not in seen_paths:
            seen_paths.add(key)
            deduped_paths.append(expanded)

    return deduped_paths


def parse_syncthing_config(path: Path) -> SyncthingConfig | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    # Intentionally broad
    except Exception:
        return None

    gui = root.find("gui")
    if gui is None:
        return None

    api_key = gui.findtext("apikey")
    if not api_key or not api_key.strip():
        return None

    address = gui.findtext("address")
    tls = bool_from_xml_attr(gui.attrib.get("tls"), default=False)
    api_url = api_url_from_gui_address(address, tls)

    return SyncthingConfig(path=path, api_key=api_key.strip(), api_url=api_url)


def discover_syncthing_config(
    explicit_config: Path | None = None,
    extra_flatpak_ids: Iterable[str] | None = None,
) -> SyncthingConfig | None:
    if explicit_config is not None:
        parsed = parse_syncthing_config(explicit_config.expanduser())
        if parsed:
            return parsed
        return None

    for path in candidate_config_files(extra_flatpak_ids):
        parsed = parse_syncthing_config(path)
        if parsed:
            return parsed
    return None


def resolve_api_credentials(
    explicit_url: str | None = None,
    explicit_key: str | None = None,
    explicit_config: Path | None = None,
) -> tuple[str, str, SyncthingConfig | None]:
    parsed_config = discover_syncthing_config(explicit_config)

    api_key = explicit_key or os.environ.get("SYNCTHING_API_KEY")
    if not api_key and parsed_config:
        api_key = parsed_config.api_key

    if not api_key:
        raise RuntimeError("No Syncthing API key found.")

    api_url = explicit_url or os.environ.get("SYNCTHING_API_URL")
    if not api_url and parsed_config and parsed_config.api_url:
        api_url = parsed_config.api_url
    if not api_url:
        api_url = DEFAULT_API_URL

    return api_url.rstrip("/"), api_key.strip(), parsed_config

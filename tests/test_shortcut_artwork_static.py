from __future__ import annotations

from pathlib import Path


ARTWORK_DIR = Path("assets/steamgrid/ludusavi")
REQUIRED_ARTWORK = ("grid_p.png", "grid_l.png", "hero.png", "logo.png")
RUNTIME_SOURCE_ROOTS = (Path("src"),)
RUNTIME_SOURCE_SUFFIXES = (".ts", ".tsx")
SHORTCUT_ARTWORK = Path("src/shortcutArtwork.ts")
LAUNCHER = Path("src/ludusaviLauncher.ts")
STEAM_GLOBALS = Path("src/types/steam-globals.d.ts")


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")

    chunks: list[tuple[bytes, bytes]] = []
    offset = 8
    while offset < len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        chunks.append((chunk_type, chunk_data))
        offset += 12 + length
        if chunk_type == b"IEND":
            break
    return chunks


def _png_color_type(data: bytes) -> int:
    chunks = _png_chunks(data)
    ihdr = next(chunk_data for chunk_type, chunk_data in chunks if chunk_type == b"IHDR")
    return ihdr[9]


def _png_has_alpha(data: bytes) -> bool:
    color_type = _png_color_type(data)
    return color_type in {4, 6} or any(chunk_type == b"tRNS" for chunk_type, _ in _png_chunks(data))


def _runtime_source_text() -> str:
    source = []
    for root in RUNTIME_SOURCE_ROOTS:
        for path in sorted(root.rglob("*")):
            if path.suffix in RUNTIME_SOURCE_SUFFIXES:
                source.append(path.read_text(encoding="utf-8"))
    return "\n".join(source)


def test_required_ludusavi_artwork_png_assets_exist() -> None:
    for filename in REQUIRED_ARTWORK:
        path = ARTWORK_DIR / filename
        assert path.is_file(), filename
        data = path.read_bytes()
        assert len(data) > 0, filename
        assert data.startswith(b"\x89PNG\r\n\x1a\n"), filename


def test_ludusavi_logo_asset_preserves_transparency() -> None:
    data = (ARTWORK_DIR / "logo.png").read_bytes()

    assert _png_has_alpha(data)


def test_runtime_sources_do_not_fetch_steamgriddb_artwork() -> None:
    source = _runtime_source_text()

    for forbidden in [
        "steamgriddb.com",
        "SGDB_API_KEY",
        "download_as_base64",
        "read_file_as_base64",
    ]:
        assert forbidden not in source


def test_shortcut_artwork_helper_uses_local_base64_and_steam_artwork_api() -> None:
    source = SHORTCUT_ARTWORK.read_text(encoding="utf-8")

    for required_text in [
        "export const LOCAL_ARTWORK_ASSET_TYPES",
        "grid_p: 0",
        "hero: 1",
        "logo: 2",
        "grid_l: 3",
        "async function localAssetUrlToBase64(assetUrl: string): Promise<string>",
        "fetch(assetUrl)",
        "new FileReader()",
        "reader.readAsDataURL(blob)",
        'SetCustomArtworkForApp(appId, base64Data, "png", steamAssetType)',
        "SetCustomLogoPositionForApp(appId, JSON.stringify(LUDUSAVI_LOGO_POSITIONING))",
        "nVersion: 1",
        'pinnedPosition: "UpperLeft"',
        "nWidthPct: 100",
        "nHeightPct: 0.01",
    ]:
        assert required_text in source

    assert "ClearCustomArtworkForApp" not in source


def test_shortcut_artwork_logs_through_backend_logger() -> None:
    source = SHORTCUT_ARTWORK.read_text(encoding="utf-8")
    launcher_source = LAUNCHER.read_text(encoding="utf-8")

    for required_text in [
        "export type ArtworkLogger",
        "logger?.(",
        "`Applying ${assetType} artwork to shortcut ${appId}`",
        "`Applied ${assetType} artwork to shortcut ${appId}`",
        "`Failed to apply ${assetType} artwork to shortcut ${appId}: ${formatArtworkError(error)}`",
        '"artwork"',
    ]:
        assert required_text in source

    assert "logger?: ArtworkLogger" in launcher_source
    assert "logger: options?.logger" in launcher_source


def test_launcher_applies_artwork_only_to_managed_shortcuts_after_overview() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "applyLudusaviArtworkToShortcut" in source
    assert "if (state.managed)" in source
    assert "const appOverview = getAppOverview(appId);" in source
    artwork_call = (
        "await applyLudusaviArtworkToShortcut({ appId, appOverview, logger: options?.logger });"
    )
    assert artwork_call in source
    assert source.index("const appOverview = getAppOverview(appId);") < source.index(artwork_call)
    assert source.index("if (!state.managed)") < source.index(artwork_call)


def test_steam_globals_declare_custom_artwork_and_logo_position_apis() -> None:
    source = STEAM_GLOBALS.read_text(encoding="utf-8")

    for required_text in [
        "SetCustomArtworkForApp(",
        "SetCustomLogoPositionForApp?",
        "BIsShortcut?(): boolean;",
        "export type LogoPosition",
        "export type LogoPositionForApp",
    ]:
        assert required_text in source

    assert "GetCustomLogoPosition" not in source

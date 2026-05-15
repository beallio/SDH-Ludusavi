from __future__ import annotations

from pathlib import Path


ARTWORK_DIR = Path("assets/steamgrid/ludusavi")
REQUIRED_ARTWORK = ("grid_p.png", "grid_l.png", "hero.png", "logo.png")
RUNTIME_SOURCE_ROOTS = (Path("src"),)
RUNTIME_SOURCE_SUFFIXES = (".ts", ".tsx")


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

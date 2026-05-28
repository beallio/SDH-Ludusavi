from pathlib import Path


def test_frontend_format_date_mdy_exists_and_is_used() -> None:
    source = Path("src/index.tsx").read_text(encoding="utf-8")

    # Assert formatDateMDY helper is defined
    assert "function formatDateMDY" in source

    # Assert formatDateMDY is used on selectedHistory.timestamp
    assert "formatDateMDY(selectedHistory.timestamp)" in source

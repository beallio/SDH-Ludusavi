import re
from pathlib import Path


def test_frontend_format_date_mdy_exists_and_is_used() -> None:
    source = Path("src/index.tsx").read_text(encoding="utf-8")

    # Use regular expressions to handle potential spacing/formatting variation
    assert re.search(r"function\s+formatDateMDY\s*\(", source) is not None
    assert re.search(r"formatDateMDY\s*\(\s*selectedHistory\.timestamp\s*\)", source) is not None

    # Assert IIFE pattern is used for safe property/timestamp splitting
    assert (
        re.search(
            r"\(\s*\)\s*=>\s*\{\s*if\s*\(\s*!\s*selectedHistory(?:\.|\?\.)timestamp\s*\)",
            source,
        )
        is not None
    )

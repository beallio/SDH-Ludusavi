from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
PRODUCTION_ROOTS = (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "py_modules" / "sdh_ludusavi",
)
PRODUCTION_SUFFIXES = {".py", ".ts", ".tsx"}
MAX_PRODUCTION_MODULE_LINES = 1_000


def production_modules() -> list[Path]:
    modules = [PROJECT_ROOT / "main.py"]
    for root in PRODUCTION_ROOTS:
        modules.extend(
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix in PRODUCTION_SUFFIXES
            and not path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
        )
    return sorted(modules)


def assert_module_within_limit(path: Path, max_lines: int = MAX_PRODUCTION_MODULE_LINES) -> None:
    lines = len(path.read_text(encoding="utf-8").splitlines())
    assert lines <= max_lines, f"{path} has {lines} lines, exceeding broad ceiling of {max_lines}"


def test_production_modules_stay_below_broad_ceiling() -> None:
    modules = production_modules()
    assert modules
    for path in modules:
        assert_module_within_limit(path)


def test_broad_ceiling_allows_incidental_growth(tmp_path: Path) -> None:
    module = tmp_path / "module.py"
    module.write_text("line\n" * MAX_PRODUCTION_MODULE_LINES, encoding="utf-8")

    assert_module_within_limit(module)


def test_broad_ceiling_rejects_giant_module(tmp_path: Path) -> None:
    module = tmp_path / "giant.py"
    module.write_text("line\n" * (MAX_PRODUCTION_MODULE_LINES + 1), encoding="utf-8")

    with pytest.raises(AssertionError, match="exceeding broad ceiling"):
        assert_module_within_limit(module)

from __future__ import annotations

import ast
from pathlib import Path


def _get_project_source_files() -> list[Path]:
    root = Path(__file__).parent.parent / "py_modules" / "sdh_ludusavi"
    return list(root.glob("*.py"))


def test_no_imports_from_service() -> None:
    """Decomposed modules must not import from service.py."""
    for path in _get_project_source_files():
        if path.name == "service.py" or path.name == "__init__.py":
            continue

        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports_service_module = node.module in ("service", "sdh_ludusavi.service")
                imports_service_from_package = node.module in (None, "sdh_ludusavi") and any(
                    alias.name == "service" for alias in node.names
                )
                if imports_service_module or imports_service_from_package:
                    raise AssertionError(f"Forbidden import from service in {path.name}")
            elif isinstance(node, ast.Import):
                for name in node.names:
                    if name.name in ("service", "sdh_ludusavi.service") or name.name.startswith(
                        "sdh_ludusavi.service."
                    ):
                        raise AssertionError(f"Forbidden import from service in {path.name}")

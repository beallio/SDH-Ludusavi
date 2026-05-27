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


def test_no_service_sys_modules() -> None:
    """Decomposed modules must not use sys.modules to retrieve the service."""
    for path in _get_project_source_files():
        content = path.read_text(encoding="utf-8")
        if "sys.modules.get" in content and "sdh_ludusavi.service" in content:
            raise AssertionError(f"Forbidden sys.modules lookup for service in {path.name}")


def test_no_private_service_access() -> None:
    """Decomposed modules must not access private properties starting with _ on self._service."""
    for path in _get_project_source_files():
        if path.name == "service.py" or path.name == "__init__.py" or path.name == "lifecycle.py":
            # We'll refactor lifecycle.py to remove self._service entirely
            continue

        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Attribute) and node.value.attr == "_service":
                    if node.attr.startswith("_"):
                        raise AssertionError(
                            f"Forbidden private service access '{node.attr}' in {path.name}"
                        )


def test_lifecycle_has_no_service() -> None:
    """lifecycle.py must not reference self._service at all."""
    lifecycle_path = Path(__file__).parent.parent / "py_modules" / "sdh_ludusavi" / "lifecycle.py"
    if lifecycle_path.exists():
        content = lifecycle_path.read_text(encoding="utf-8")
        if "_service" in content:
            raise AssertionError("lifecycle.py must not reference _service")


def test_service_facade_class_size() -> None:
    """SDHLudusaviService class span must be under 400 lines."""
    service_path = Path(__file__).parent.parent / "py_modules" / "sdh_ludusavi" / "service.py"
    content = service_path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(service_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SDHLudusaviService":
            # node.end_lineno - node.lineno gives the span of the class
            span = node.end_lineno - node.lineno
            assert span < 400, f"SDHLudusaviService spans {span} lines, which is >= 400"
            break
    else:
        raise AssertionError("SDHLudusaviService class definition not found")


def test_no_registry_match_game_rebinding() -> None:
    """service.py must not contain _registry_match_game or assign to self._registry.match_game."""
    service_path = Path(__file__).parent.parent / "py_modules" / "sdh_ludusavi" / "service.py"
    content = service_path.read_text(encoding="utf-8")
    assert "_registry_match_game" not in content
    assert "self._registry.match_game =" not in content


def test_no_direct_service_log_in_gateway() -> None:
    """gateway.py must not contain self._service.log."""
    gateway_path = Path(__file__).parent.parent / "py_modules" / "sdh_ludusavi" / "gateway.py"
    content = gateway_path.read_text(encoding="utf-8")
    assert "self._service.log" not in content


def test_no_service_references_in_gateway() -> None:
    """gateway.py must not contain getattr(service, or service: Any."""
    gateway_path = Path(__file__).parent.parent / "py_modules" / "sdh_ludusavi" / "gateway.py"
    content = gateway_path.read_text(encoding="utf-8")
    assert "getattr(service," not in content
    assert "service: Any" not in content
    assert "self._service" not in content

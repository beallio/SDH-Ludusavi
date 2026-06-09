import re
from pathlib import Path


def test_no_direct_steam_global_casts() -> None:
    # no direct Steam global casts outside steamRuntime.ts
    frontend_dir = Path("src")
    pattern = re.compile(r"\(\s*(?:window|globalThis|Router)\s+as\s+any\s*\)")
    pattern2 = re.compile(r"(?:window|globalThis)\.(?:SteamClient|Steam3D|appStore)")

    for ts_file in frontend_dir.rglob("*.ts*"):
        if (
            ts_file.name in ("steamRuntime.ts", "steam.ts")
            or ts_file.name.endswith(".test.ts")
            or ts_file.name.endswith(".test.tsx")
        ):
            continue
        content = ts_file.read_text(encoding="utf-8")
        assert not pattern.search(content), f"Found direct any cast on global in {ts_file}"
        assert not pattern2.search(content), f"Found direct global reference in {ts_file}"


def test_no_updater_private_service_access() -> None:
    # no updater private-service access
    backend_dir = Path("py_modules/sdh_ludusavi")
    for py_file in backend_dir.rglob("*.py"):
        if py_file.name in ("updater.py", "updater_models.py", "service.py"):
            continue
        content = py_file.read_text(encoding="utf-8")
        assert "SDHLudusaviService" not in content and "PluginUpdater" not in content, (
            f"Found private service access in {py_file}"
        )


def test_no_updater_orchestration_in_main() -> None:
    # no updater orchestration in main.py
    main_py = Path("main.py")
    if main_py.exists():
        content = main_py.read_text(encoding="utf-8")
        assert "updater" not in content.lower() or "update_plugin" not in content, (
            "Found updater orchestration in main.py"
        )


def test_no_full_sha_logging() -> None:
    # no source patterns that log full SHA values
    # check that any log containing sha256 also slices it (e.g. sha256.slice)
    frontend_dir = Path("src")
    for ts_file in frontend_dir.rglob("*.ts*"):
        content = ts_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "log(" in line and "sha256" in line.lower():
                # Should not log raw sha256. It should be sliced or truncated.
                assert (
                    "slice(" in line or "substring(" in line or "substr(" in line or "trunc" in line
                ), f"Found full SHA logging in {ts_file}:{i + 1} : {line}"

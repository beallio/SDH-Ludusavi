from pathlib import Path


LAUNCHER = Path("src/ludusaviLauncher.ts")


def test_launcher_shortcut_cache_persistence_failures_abort_launch() -> None:
    source = LAUNCHER.read_text()

    assert (
        "throw new Error(`Failed to save shortcut ID: ${result.message || result.status}`);"
        in source
    )
    assert "err instanceof Error ? err.message : String(err)" in source
    assert "throw new Error(" in source

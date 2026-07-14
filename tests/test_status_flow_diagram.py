from pathlib import Path


DIAGRAM = Path("docs/status_bar_game_state_flows.html")
CONFLICT_DIAGRAM = Path("docs/plans/cloud_sync_conflict_resolution_flow.html")


def test_status_bar_game_state_flow_diagram_documents_lifecycle_paths() -> None:
    source = DIAGRAM.read_text(encoding="utf-8")

    for required_text in [
        "Status Bar Game State Flows",
        "Launch Flow",
        "Exit Flow",
        "App lifetime start",
        "App lifetime stop",
        "check_game_start",
        "restore_game_on_start",
        "check_game_exit",
        "backup_game_on_exit",
        "VERIFYING GAME SAVE",
        "RESTORING BACKUP SAVE",
        "BACKING UP LOCAL SAVE",
        "SAVE CONFLICT",
        "SYNC SKIPPED — CONFLICT UNRESOLVED",
        "Observe Syncthing activity",
        "Wait for three settled samples",
        "Re-run check_game_start",
        "GAME SAVE UP TO DATE",
        "UNKNOWN",
        "UNABLE TO SYNC",
        "auto_sync_disabled",
        "operation_running",
        "unmatched_game",
        "no_backup",
        "no_files_found",
        "not_in_preview",
        "ambiguous_recency",
        "game_error",
        "preview_failed",
    ]:
        assert required_text in source


def test_status_bar_game_state_flow_diagram_is_standalone_html() -> None:
    source = DIAGRAM.read_text(encoding="utf-8")

    assert source.startswith("<!doctype html>")
    assert "<style>" in source
    assert "</html>" in source
    assert "http://" not in source
    assert "https://" not in source


def test_backup_conflict_resolution_flow_diagram_documents_launch_gate() -> None:
    source = CONFLICT_DIAGRAM.read_text(encoding="utf-8")

    for required_text in [
        "Launch-Gated Backup Conflict Resolution",
        "App lifetime start",
        "systemctl --user freeze",
        "frozen Steam app scope",
        "check_game_start",
        "ambiguous_recency",
        "Conflict Detected",
        "Keep Local Save",
        "Restore Backup Save",
        "resolve_game_start_conflict",
        "systemctl --user thaw",
        "backupModifiedAt",
        "Ludusavi backup path",
    ]:
        assert required_text in source

    assert "Download Cloud Save" not in source
    assert "Cloud Save" not in source
    assert "SIGSTOP" not in source
    assert "SIGCONT" not in source
    assert "process tree" not in source


def test_backup_conflict_resolution_flow_diagram_is_standalone_html() -> None:
    source = CONFLICT_DIAGRAM.read_text(encoding="utf-8")

    assert source.startswith("<!doctype html>")
    assert "<style>" in source
    assert "</html>" in source
    assert "http://" not in source
    assert "https://" not in source

from pathlib import Path


README = Path("README.md")


def test_readme_enumerates_status_messages() -> None:
    source = README.read_text()

    for text in [
        "## Status Messages",
        "Game status values:",
        "Operation result values:",
        "Skip reasons:",
        "Operation status fields:",
        "Other UI states:",
        "`configured`",
        "`has_backup`",
        "`needs_first_backup`",
        "`error`",
        "`backed_up`",
        "`restored`",
        "`skipped`",
        "`failed`",
        "`auto_sync_disabled`",
        "`operation_running`",
        "`unmatched_game`",
        "`no_backup`",
        "`local_current`",
        "`ambiguous_recency`",
        "`is_running`",
        "`last_result`",
        "`last_error`",
        "`dependency_error`",
        "`No Ludusavi games found`",
        "`Unknown`",
    ]:
        assert text in source


def test_readme_documents_visible_ludusavi_shortcut() -> None:
    source = README.read_text()
    compact_source = " ".join(source.split())

    for text in ["## Ludusavi Launcher Shortcut", "does not hide the shortcut"]:
        assert text in source

    for text in [
        "## Ludusavi Launcher Shortcut",
        'visible non-Steam shortcut named `"Ludusavi"`',
        "adopts the matching shortcut and refreshes its cached AppID",
    ]:
        assert text in compact_source

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

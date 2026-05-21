from pathlib import Path

FRONTEND = Path("src/index.tsx")


def test_frontend_handles_refresh_dependency_error():
    source = FRONTEND.read_text()

    # Check that applyRefreshResult returns a boolean
    assert (
        "const applyRefreshResult = (result: RpcResult<RefreshResult>, preferredGame?: string): boolean =>"
        in source
    )

    # Check that it checks for dependency_error
    assert "if (result.dependency_error) {" in source
    assert (
        'notify("failures_errors", "SDH-Ludusavi refresh failed", result.dependency_error' in source
    )

    # Check that success toast is conditional
    # It should look something like: if (applyRefreshResult(result)) { ... success toast ... }
    assert "if (applyRefreshResult(result)) {" in source
    assert 'notify("refresh_status", "SDH-Ludusavi", "Ludusavi game status refreshed"' in source

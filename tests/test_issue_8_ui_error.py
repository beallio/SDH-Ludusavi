from pathlib import Path

FRONTEND_PATHS = [
    Path("src/index.tsx"),
    Path("src/components/qam/LudusaviContent.tsx"),
]


def test_frontend_handles_refresh_dependency_error():
    source = "\n".join(path.read_text() for path in FRONTEND_PATHS)

    # Check that applyRefreshResult returns a boolean
    assert "const applyRefreshResult = (" in source
    assert "result: RpcResult<RefreshResult>" in source
    assert "preferredGame?: string" in source
    assert "): boolean =>" in source

    # Check that it checks for dependency_error
    assert "if (result.dependency_error) {" in source
    assert '"failures_errors"' in source
    assert '"SDH-Ludusavi refresh failed"' in source
    assert "result.dependency_error" in source

    # Check that success toast is conditional
    # It should look something like: if (applyRefreshResult(result)) { ... success toast ... }
    assert "if (applyRefreshResult(result)) {" in source
    assert '"refresh_status"' in source
    assert '"SDH-Ludusavi"' in source
    assert '"Ludusavi game status refreshed"' in source

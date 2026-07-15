from __future__ import annotations

import pytest

from sdh_ludusavi.launch_gate import SteamAppScope
from sdh_ludusavi.launch_gate_acquire import ScopeAcquisitionResult


def test_successful_scope_acquisition_result_requires_a_scope() -> None:
    with pytest.raises(ValueError, match="successful scope acquisition requires a scope"):
        ScopeAcquisitionResult(True)

    scope = SteamAppScope(
        unit="app-steam-app123-456.scope",
        cgroup_path=(
            "/user.slice/user-1000.slice/user@1000.service/app.slice/app-steam-app123-456.scope"
        ),
        device=1,
        inode=2,
        root_pid=456,
    )
    assert ScopeAcquisitionResult(True, scope=scope).scope is scope

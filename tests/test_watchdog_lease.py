from types import SimpleNamespace

from sdh_ludusavi.watchdog_lease import _PauseLease, _lease_expiry_reason


def test_pause_lease_has_no_scope_iteration_for_stop_only_gate() -> None:
    lease = _PauseLease(None, paused_at=10.0, lease_id="lease", lease_deadline=40.0)

    assert lease.scopes == ()
    assert _lease_expiry_reason(lease, 39.0) is None
    assert _lease_expiry_reason(lease, 41.0) == "lease expired"


def test_pause_lease_iterates_primary_and_recovery_scopes() -> None:
    primary = SimpleNamespace(unit="primary")
    recovery = SimpleNamespace(unit="recovery")
    lease = _PauseLease(
        primary,
        paused_at=10.0,
        lease_id="lease",
        lease_deadline=40.0,
        recovery_scopes=(recovery,),
    )

    assert lease.scopes == (primary, recovery)

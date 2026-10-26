use crate::{
    launch_gate::parse_start_ticks,
    lifecycle::{RestorePreview, TimestampDirection, classify_restore_change, timestamp_direction},
    singleton::same_commandline,
    watchdog::lease_expiry_reason,
};

#[test]
fn restore_preview_decisions_match_python_contract() {
    for (change, expected) in [
        (Some("Same"), RestorePreview::LocalCurrent),
        (Some("New"), RestorePreview::BackupNewer),
        (Some("Different"), RestorePreview::BackupDiffers),
        (None, RestorePreview::Ambiguous),
        (Some("unknown"), RestorePreview::Ambiguous),
    ] {
        assert_eq!(classify_restore_change(change), expected);
    }
}

#[test]
fn timestamp_direction_keeps_strict_120_second_margin() {
    for (local, backup, expected) in [
        (
            Some("2026-06-01T00:00:00Z"),
            Some("2026-06-01T00:02:01Z"),
            TimestampDirection::BackupNewer,
        ),
        (
            Some("2026-06-01T00:00:00Z"),
            Some("2026-06-01T00:02:00Z"),
            TimestampDirection::NotNewer,
        ),
        (
            Some("2026-06-01T00:00:00Z"),
            Some("2026-05-31T23:59:59Z"),
            TimestampDirection::NotNewer,
        ),
        (
            None,
            Some("2026-06-01T00:03:00Z"),
            TimestampDirection::Unknown,
        ),
        (
            Some("bad"),
            Some("2026-06-01T00:03:00Z"),
            TimestampDirection::Unknown,
        ),
    ] {
        assert_eq!(timestamp_direction(local, backup), expected);
    }
}

#[test]
fn timestamp_direction_accepts_naive_offsets_and_rejects_truncated_times() {
    assert_eq!(
        timestamp_direction(
            Some("2026-06-01 00:00:00"),
            Some("2026-06-01T00:02:01+00:00"),
        ),
        TimestampDirection::BackupNewer
    );
    assert_eq!(
        timestamp_direction(Some("2026-06-01T00:00:00z"), Some("2026-06-01T00:02:01Z"),),
        TimestampDirection::BackupNewer
    );
    assert_eq!(
        timestamp_direction(Some("2026-06-01T"), Some("2026-06-01T00:02:01Z"),),
        TimestampDirection::Unknown
    );
}
#[test]
fn proc_start_ticks_use_field_22_after_the_last_comm_parenthesis() {
    let stat = "57 (worker (nested) name) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 991";
    assert_eq!(parse_start_ticks(stat, 57), Some(991));
    assert_eq!(parse_start_ticks(stat, 58), None);
    assert_eq!(parse_start_ticks("malformed", 57), None);
}

#[test]
fn lease_expiry_preserves_strict_deadline_and_absolute_ceiling() {
    assert_eq!(lease_expiry_reason(0.0, 30.0, 30.0), None);
    assert_eq!(
        lease_expiry_reason(0.0, 30.0, 30.001),
        Some("lease expired")
    );
    assert_eq!(lease_expiry_reason(0.0, 500.0, 240.0), None);
    assert_eq!(
        lease_expiry_reason(0.0, 500.0, 240.001),
        Some("absolute ceiling")
    );
    assert_eq!(
        lease_expiry_reason(0.0, 500.0, 241.0),
        Some("absolute ceiling")
    );
}

#[test]
fn singleton_requires_byte_identical_full_commandline() {
    let current = b"/runtime/backend\0--plugin\0SDH-Ludusavi\0";
    assert!(same_commandline(current, current));
    assert!(!same_commandline(current, b"/runtime/backend\0--plugin\0"));
    assert!(!same_commandline(
        current,
        b"/runtime/backend-other\0--plugin\0SDH-Ludusavi\0"
    ));
}

use time::{OffsetDateTime, format_description::well_known::Rfc3339};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RestorePreview {
    LocalCurrent,
    BackupNewer,
    BackupDiffers,
    Ambiguous,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TimestampDirection {
    BackupNewer,
    NotNewer,
    Unknown,
}

pub(crate) fn classify_restore_change(change: Option<&str>) -> RestorePreview {
    match change {
        Some("Same") => RestorePreview::LocalCurrent,
        Some("New") => RestorePreview::BackupNewer,
        Some("Different") => RestorePreview::BackupDiffers,
        _ => RestorePreview::Ambiguous,
    }
}

pub(crate) fn timestamp_direction(
    local_modified_at: Option<&str>,
    backup_modified_at: Option<&str>,
) -> TimestampDirection {
    let (Some(local), Some(backup)) = (
        local_modified_at.and_then(parse_iso_timestamp),
        backup_modified_at.and_then(parse_iso_timestamp),
    ) else {
        return TimestampDirection::Unknown;
    };
    if backup.unix_timestamp_nanos() - local.unix_timestamp_nanos() > 120_000_000_000 {
        TimestampDirection::BackupNewer
    } else {
        TimestampDirection::NotNewer
    }
}

fn parse_iso_timestamp(value: &str) -> Option<OffsetDateTime> {
    let value = value.trim();
    let normalized = if value.contains(' ') && !value.contains('T') {
        value.replacen(' ', "T", 1)
    } else {
        value.to_owned()
    };
    if normalized.is_empty() {
        return None;
    }
    let normalized = if let Some(prefix) = normalized.strip_suffix('z') {
        format!("{prefix}Z")
    } else {
        normalized
    };
    let candidate = if normalized.contains('T') {
        let time = normalized.split_once('T')?.1;
        if time.ends_with('Z') || time.contains('+') || time.contains('-') {
            normalized
        } else {
            format!("{normalized}Z")
        }
    } else {
        format!("{normalized}T00:00:00Z")
    };
    OffsetDateTime::parse(&candidate, &Rfc3339).ok()
}

#[cfg(test)]
mod tests {
    use super::{RestorePreview, TimestampDirection, classify_restore_change, timestamp_direction};

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
    fn restore_preview_decisions_classify_changes() {
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
}

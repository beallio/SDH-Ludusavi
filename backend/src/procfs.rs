use std::{fs, os::unix::fs::MetadataExt, path::Path};

pub(crate) fn read_identity(dir: &Path, pid: i32) -> Option<(u32, u64, String)> {
    let uid = fs::metadata(dir).ok()?.uid();
    let stat = fs::read_to_string(dir.join("stat")).ok()?;
    let start_ticks = parse_start_ticks(&stat, pid)?;
    Some((uid, start_ticks, stat))
}

pub(crate) fn parse_start_ticks(stat: &str, expected_pid: i32) -> Option<u64> {
    let open = stat.find('(')?;
    let close = stat.rfind(')')?;
    if open == 0 || close <= open || stat[..open].trim().parse::<i32>().ok()? != expected_pid {
        return None;
    }
    stat[close + 1..].split_whitespace().nth(19)?.parse().ok()
}

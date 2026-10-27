use serde_json::{Map, Value};

pub(crate) fn valid_history_entry(value: &Value) -> Option<Value> {
    let operation = value.get("operation")?.as_str()?;
    if !matches!(operation, "backup" | "restore" | "start" | "exit") {
        return None;
    }
    let trigger = value.get("trigger")?.as_str()?;
    if !matches!(
        trigger,
        "manual_backup" | "manual_restore" | "auto_start" | "auto_exit"
    ) {
        return None;
    }
    let status = value.get("status")?.as_str()?;
    if !matches!(status, "backed_up" | "restored" | "skipped" | "failed") {
        return None;
    }
    let timestamp = value.get("timestamp")?.as_str()?;
    let mut entry = Map::new();
    entry.insert("operation".to_owned(), Value::String(operation.to_owned()));
    entry.insert("trigger".to_owned(), Value::String(trigger.to_owned()));
    entry.insert("status".to_owned(), Value::String(status.to_owned()));
    for key in ["reason", "message"] {
        entry.insert(
            key.to_owned(),
            value
                .get(key)
                .filter(|value| value.is_null() || value.is_string())
                .cloned()
                .unwrap_or(Value::Null),
        );
    }
    entry.insert("timestamp".to_owned(), Value::String(timestamp.to_owned()));
    Some(Value::Object(entry))
}

export function formatConflictTime(value?: string | null) {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function formatTimestamp(value?: string | null) {
  return formatConflictTime(value);
}

export function formatHistoryTimestamp(
  value?: string | null,
  opts?: { timeZone?: string }
): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const timeZone = opts?.timeZone;
  const datePart = date.toLocaleDateString("en-US", {
    month: "2-digit",
    day: "2-digit",
    year: "numeric",
    timeZone,
  });
  const timePart = date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone,
  });
  return `${datePart} ${timePart}`;
}

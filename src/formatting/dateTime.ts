export function formatTime12h(timeStr: string): string {
  const parts = timeStr.split(":");
  if (parts.length < 2) return timeStr;
  let hours = parseInt(parts[0], 10);
  const minutes = parts[1];
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12;
  hours = hours ? hours : 12;
  return `${hours}:${minutes} ${ampm}`;
}

export function formatDateMDY(timestampStr: string): string {
  const datePart = timestampStr.split(/[T ]/)[0];
  if (!datePart) return "";
  const isIsoDate = /^\d{4}-\d{2}-\d{2}$/.test(datePart);
  if (!isIsoDate) return datePart;
  const parts = datePart.split("-");
  return `${parts[1]}/${parts[2]}/${parts[0]}`;
}

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

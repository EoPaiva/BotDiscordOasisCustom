export function duration(milliseconds: number | null | undefined): string {
  const totalMinutes = Math.max(0, Math.floor(Number(milliseconds ?? 0) / 60_000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours}h ${String(minutes).padStart(2, "0")}m` : `${minutes}m`;
}

export function dateTime(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(epoch));
}

export function isoDateTime(value: unknown): string | undefined {
  const timestamp = Number(value);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return undefined;
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
}

export function label(value: unknown): string {
  return String(value ?? "—").replaceAll("_", " ");
}

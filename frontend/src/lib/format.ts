export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z"); // API timestamps are UTC
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function fmtNum(n: number | undefined | null): string {
  return (n ?? 0).toLocaleString();
}

export function duration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const s = new Date(start.endsWith("Z") ? start : start + "Z").getTime();
  const e = end ? new Date(end.endsWith("Z") ? end : end + "Z").getTime() : Date.now();
  const sec = Math.max(0, Math.round((e - s) / 1000));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

export const JOB_TYPE_LABEL: Record<string, string> = {
  website: "Website scrape",
  url_list: "URL list",
  directory: "Directory scrape",
  upload: "File extract",
  upload_crawl: "File → crawl",
};

export function splitLines(text: string): string[] {
  return text
    .split(/[\r\n,;\t ]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

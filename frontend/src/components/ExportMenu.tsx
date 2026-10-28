"use client";
import { ChevronDown, FileSpreadsheet } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, downloadUrl } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import type { ExportRecord } from "@/lib/types";

export interface ExportChoice {
  label: string;
  description?: string;
  body: Record<string, unknown>;
  disabled?: boolean;
}

/** Creates a real .xlsx on the server and starts the download. Failures are shown as an error toast. */
export function useExporter() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function run(body: Record<string, unknown>) {
    setBusy(true);
    try {
      const rec = await api.post<ExportRecord>("/api/exports", body);
      toast.success(`Exported ${fmtNum(rec.row_count)} lead${rec.row_count === 1 ? "" : "s"} to ${rec.filename}`);
      const a = document.createElement("a");
      a.href = downloadUrl(rec.download_url);
      a.download = rec.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      return rec;
    } catch (e) {
      toast.error(`Export failed: ${e instanceof ApiError ? e.message : "unexpected error"}`);
    } finally {
      setBusy(false);
    }
  }
  return { run, busy };
}

export function ExportMenu({ choices, label = "Export to Excel", variant = "primary", size = "md" }: { choices: ExportChoice[]; label?: string; variant?: "primary" | "outline" | "secondary"; size?: "sm" | "md" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { run, busy } = useExporter();
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <div className="relative" ref={ref}>
      <Button variant={variant} size={size} loading={busy} icon={<FileSpreadsheet className="h-4 w-4" />} onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}>
        {label}
        <ChevronDown className="h-4 w-4" />
      </Button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-2 w-72 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-xl">
          {choices.map((c) => (
            <button
              key={c.label}
              role="menuitem"
              disabled={c.disabled}
              onClick={() => {
                setOpen(false);
                run(c.body);
              }}
              className="block w-full px-4 py-2.5 text-left hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span className="block text-sm font-medium text-slate-800">{c.label}</span>
              {c.description && <span className="block text-xs text-slate-500">{c.description}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

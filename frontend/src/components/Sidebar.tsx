"use client";
import clsx from "clsx";
import { Activity, FileSpreadsheet, FolderSearch, Globe, LayoutDashboard, ListPlus, Menu, Package, Settings, UploadCloud, Users, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";
import { usePolling } from "@/lib/hooks";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/website-scraper", label: "Website Scraper", icon: Globe },
  { href: "/directory-scraper", label: "Directory Scraper", icon: FolderSearch },
  { href: "/upload", label: "Upload & Extract", icon: UploadCloud },
  { href: "/url-import", label: "URL List Import", icon: ListPlus },
  { href: "/leads", label: "All Leads", icon: Users },
  { href: "/jobs", label: "Scraping Jobs", icon: Activity },
  { href: "/exports", label: "Export History", icon: FileSpreadsheet },
  { href: "/settings", label: "Settings", icon: Settings },
];

function ApiStatus() {
  const [state, setState] = useState<"checking" | "online" | "offline">("checking");
  usePolling(async () => {
    try {
      const r = await fetch(`${API_URL}/health`, { cache: "no-store" });
      setState(r.ok ? "online" : "offline");
    } catch {
      setState("offline");
    }
  }, 15000);
  return (
    <div className="rounded-lg bg-navy-800/60 px-3 py-2 text-xs text-navy-100">
      <div className="flex items-center gap-2">
        <span className={clsx("h-2 w-2 rounded-full", state === "online" ? "bg-emerald-400" : state === "offline" ? "bg-red-400" : "bg-amber-300 animate-pulse")} />
        {state === "online" ? "API online" : state === "offline" ? "API offline" : "Checking API…"}
      </div>
      {state === "offline" && <p className="mt-1 text-navy-200">Start the backend (see README) — expected at {API_URL}</p>}
    </div>
  );
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="flex-1 space-y-0.5 px-3" aria-label="Main">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(href + "/");
        return (
          <Link key={href} href={href} onClick={onNavigate} aria-current={active ? "page" : undefined}
            className={clsx("flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors", active ? "bg-brand-600 text-white shadow-sm" : "text-navy-100 hover:bg-navy-800 hover:text-white")}>
            <Icon className="h-[18px] w-[18px]" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

export function Sidebar() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  useEffect(() => setOpen(false), [pathname]);
  const brand = (
    <Link href="/" className="flex items-center gap-2.5 px-6 py-5 text-white">
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-500"><Package className="h-5 w-5" /></span>
      <span className="text-lg font-semibold tracking-tight">PackLead <span className="font-normal text-navy-200">Scraper</span></span>
    </Link>
  );
  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col bg-navy-900 lg:flex">
        {brand}
        <NavList />
        <div className="p-3"><ApiStatus /></div>
      </aside>
      <header className="sticky top-0 z-30 flex items-center justify-between bg-navy-900 px-4 py-3 text-white lg:hidden">
        <Link href="/" className="flex items-center gap-2 font-semibold"><Package className="h-5 w-5 text-brand-400" /> PackLead Scraper</Link>
        <button onClick={() => setOpen(true)} aria-label="Open menu" className="rounded p-1.5 hover:bg-navy-800"><Menu className="h-6 w-6" /></button>
      </header>
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-navy-950/60" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-navy-900">
            <div className="flex items-center justify-between pr-3">{brand}<button onClick={() => setOpen(false)} aria-label="Close menu" className="rounded p-1.5 text-white hover:bg-navy-800"><X className="h-6 w-6" /></button></div>
            <NavList onNavigate={() => setOpen(false)} />
            <div className="p-3"><ApiStatus /></div>
          </aside>
        </div>
      )}
    </>
  );
}

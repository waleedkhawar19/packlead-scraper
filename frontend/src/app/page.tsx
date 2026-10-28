import { ArrowRight, BadgeCheck, FileSpreadsheet, FolderSearch, Globe, ListPlus, Package, ShieldCheck, UploadCloud } from "lucide-react";
import Link from "next/link";

const FEATURES = [
  { icon: Globe, title: "Website scraper", text: "Paste one URL or thousands. PackLead visits the homepage and contact, about, sales and support pages and records every public business email with the page it came from.", href: "/website-scraper" },
  { icon: FolderSearch, title: "Directory scraper", text: "Collect business names, websites, emails, phones and addresses from public directory pages, following pagination only where robots.txt allows.", href: "/directory-scraper" },
  { icon: UploadCloud, title: "Upload & extract", text: "Drop in PDFs, Word, Excel, CSV, text, HTML, JSON or XML. Emails and website links are pulled out with file, sheet, row and page references.", href: "/upload" },
  { icon: ListPlus, title: "URL list import", text: "Turn a list of company websites — pasted or uploaded as Excel/CSV — into a deduplicated, searchable table of email leads.", href: "/url-import" },
  { icon: BadgeCheck, title: "Honest email checks", text: "Syntax, domain and MX checks with clear statuses. We never claim a mailbox exists just because the syntax is valid.", href: "/leads" },
  { icon: FileSpreadsheet, title: "Excel export", text: "Export everything, a filtered view or your selection to a real .xlsx — with unique-email and by-domain sheets.", href: "/exports" },
];

export default function Home() {
  return (
    <div className="min-h-screen">
      <header className="bg-navy-900 text-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
          <span className="flex items-center gap-2.5 text-lg font-semibold">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-500"><Package className="h-5 w-5" /></span> PackLead Scraper
          </span>
          <Link href="/dashboard" className="rounded-lg px-3 py-2 text-sm font-medium text-navy-100 hover:bg-navy-800">Open dashboard</Link>
        </div>
        <div className="mx-auto max-w-6xl px-5 pb-20 pt-14 sm:pt-20">
          <p className="mb-3 inline-block rounded-full bg-navy-800 px-3 py-1 text-xs font-medium text-brand-200">Lead research for packaging suppliers · United States</p>
          <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">Find the right buyers for your packaging — from emails they already publish.</h1>
          <p className="mt-5 max-w-2xl text-lg text-navy-100">
            PackLead Scraper collects <b>publicly listed business email addresses</b> from websites, public directories and your own files, removes duplicates, organises them as leads and exports them to Excel. No paid APIs, no API keys.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/website-scraper" className="inline-flex h-12 items-center gap-2 rounded-lg bg-brand-500 px-6 text-base font-semibold text-white shadow-lg hover:bg-brand-600">
              Start Scraping <ArrowRight className="h-5 w-5" />
            </Link>
            <Link href="/upload" className="inline-flex h-12 items-center gap-2 rounded-lg border border-navy-400 px-6 text-base font-medium text-white hover:bg-navy-800">Upload a file</Link>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-5 py-14">
        <h2 className="text-2xl font-semibold text-navy-900">Everything in one place</h2>
        <div className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, text, href }) => (
            <Link key={title} href={href} className="group rounded-xl border border-slate-200 bg-white p-5 shadow-card transition hover:border-brand-300 hover:shadow-md">
              <span className="mb-3 inline-flex rounded-lg bg-brand-50 p-2.5 text-brand-600"><Icon className="h-5 w-5" /></span>
              <h3 className="text-base font-semibold text-navy-900">{title}</h3>
              <p className="mt-1.5 text-sm text-slate-600">{text}</p>
              <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand-700 group-hover:gap-2">Open <ArrowRight className="h-4 w-4" /></span>
            </Link>
          ))}
        </div>
      </section>

      <section className="border-t border-slate-200 bg-white">
        <div className="mx-auto grid max-w-6xl gap-8 px-5 py-14 lg:grid-cols-2">
          <div>
            <h2 className="text-2xl font-semibold text-navy-900">How it works</h2>
            <ol className="mt-5 space-y-4 text-slate-700">
              {["Give it websites, a public directory or a file.", "A background job crawls politely: robots.txt respected, small delays, bounded page counts. You watch live progress and can pause or cancel.", "Emails are deduplicated, validated (syntax + DNS), tagged with evidence-based categories, and kept with their source page.", "Filter, edit, tag and export your leads to Excel."].map((t, i) => (
                <li key={i} className="flex gap-3"><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-navy-900 text-sm font-semibold text-white">{i + 1}</span><span className="pt-0.5">{t}</span></li>
              ))}
            </ol>
          </div>
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-6">
            <h3 className="flex items-center gap-2 text-lg font-semibold text-emerald-900"><ShieldCheck className="h-5 w-5" /> Built to be a good web citizen</h3>
            <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm text-emerald-900">
              <li>Only publicly displayed business contact details are collected.</li>
              <li>It never bypasses CAPTCHAs, logins, paywalls or anti-bot protection — those sites are skipped and reported.</li>
              <li>Private networks and cloud-metadata addresses are blocked at every request and redirect.</li>
              <li>It does <b>not</b> send emails. Use the leads for research; follow CAN-SPAM and each site’s terms when you reach out.</li>
            </ul>
          </div>
        </div>
      </section>
      <footer className="bg-navy-950 py-6 text-center text-xs text-navy-300">PackLead Scraper · self-hosted lead research tool</footer>
    </div>
  );
}

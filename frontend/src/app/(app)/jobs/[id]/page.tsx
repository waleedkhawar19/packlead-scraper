"use client";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { JobPanel } from "@/components/JobPanel";
import { PageHeader } from "@/components/ui";

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);
  return (
    <>
      <Link href="/jobs" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-600 hover:text-navy-900"><ArrowLeft className="h-4 w-4" /> All jobs</Link>
      <PageHeader title={`Job #${Number.isFinite(id) ? id : ""}`} />
      {Number.isFinite(id) ? <JobPanel jobId={id} /> : <p className="text-sm text-red-700">That is not a valid job ID.</p>}
    </>
  );
}

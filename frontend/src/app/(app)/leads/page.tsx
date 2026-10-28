"use client";
import { LeadsTable } from "@/components/LeadsTable";
import { PageHeader } from "@/components/ui";

export default function LeadsPage() {
  return (
    <>
      <PageHeader title="All Leads" description="Search, filter, edit, tag and export every lead collected. Click a row to see where the email was found and to edit its details." />
      <LeadsTable />
    </>
  );
}

"use client";
import { UploadWizard } from "@/components/UploadWizard";
import { Notice, PageHeader } from "@/components/ui";

export default function UrlImportPage() {
  return (
    <>
      <PageHeader title="URL List Import" description="Upload a list of company websites (TXT, CSV or Excel — 500+ is fine) and turn it into a deduplicated table of email leads. Processing runs as a background job, so you can leave the page." />
      <div className="space-y-5">
        <Notice title="Example input">One website per line — <code>company1.com</code>, <code>https://example.org/contact</code> — or a spreadsheet with a “Website” column. If the URLs are in several columns, tick each of them in the mapping step.</Notice>
        <UploadWizard mode="urls" />
      </div>
    </>
  );
}

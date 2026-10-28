"use client";
import { UploadWizard } from "@/components/UploadWizard";
import { PageHeader } from "@/components/ui";

export default function UploadPage() {
  return (
    <>
      <PageHeader title="Upload & Extract" description="Pull emails and website links out of PDFs, Word documents, spreadsheets and text files. Preview everything before anything is saved or exported." />
      <UploadWizard mode="extract" />
    </>
  );
}

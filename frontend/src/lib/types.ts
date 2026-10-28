export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type JobStatus = "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";

export interface Job {
  id: number;
  name: string;
  type: string;
  status: JobStatus;
  params: Record<string, unknown>;
  input_filename: string | null;
  is_test: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  total_urls: number;
  processed_urls: number;
  successful_urls: number;
  failed_urls: number;
  skipped_urls: number;
  pages_visited: number;
  pages_skipped: number;
  emails_found: number;
  unique_leads: number;
  duplicates_removed: number;
  error: string | null;
}

export interface JobCreated {
  job: Job;
  valid_urls: number;
  invalid_urls: number;
  duplicate_urls: number;
}

export interface JobUrl {
  id: number;
  url: string;
  original_input: string | null;
  status: "pending" | "success" | "failed" | "skipped";
  pages_visited: number;
  pages_skipped: number;
  emails_found: number;
  error: string | null;
  note: string | null;
  row_ref: string | null;
  finished_at: string | null;
}

export interface JobProgress {
  job_id: number;
  status: JobStatus;
  percent: number;
  total_urls: number;
  processed_urls: number;
  pending_urls: number;
  successful_urls: number;
  failed_urls: number;
  skipped_urls: number;
  pages_visited: number;
  pages_skipped: number;
  emails_found: number;
  unique_leads: number;
  duplicates_removed: number;
  error: string | null;
  recent: { id: number; url: string; status: string; error: string | null; note: string | null; pages_visited: number; pages_skipped: number; emails_found: number }[];
}

export interface LeadSource {
  id: number;
  source_type: string | null;
  source_url: string | null;
  source_filename: string | null;
  sheet_name: string | null;
  row_number: number | null;
  page_number: number | null;
  snippet: string | null;
  extra: Record<string, unknown> | null;
  collected_at: string;
}

export interface Lead {
  id: number;
  email: string;
  original_email: string;
  email_domain: string;
  is_role_based: boolean;
  business_name: string | null;
  website: string | null;
  contact_page_url: string | null;
  category: string | null;
  category_source: string | null;
  category_evidence: { category?: string; confidence?: string; keywords?: string[]; snippets?: string[] } | null;
  city: string | null;
  state: string | null;
  country: string | null;
  address: string | null;
  phone: string | null;
  source_type: string;
  source_filename: string | null;
  source_url: string | null;
  collected_at: string;
  verification_status: string;
  verification_detail: string | null;
  notes: string | null;
  tags: string | null;
  job_id: number | null;
  is_test: boolean;
  matched_keywords?: string[] | null;
}

export interface LeadDetail extends Lead {
  sources: LeadSource[];
}

export interface LeadFilters {
  q?: string;
  category?: string;
  state?: string;
  city?: string;
  domain?: string;
  source_type?: string;
  verification_status?: string;
  date_from?: string;
  date_to?: string;
  has_website?: string; // "", "true", "false"
  role_based?: string;
  tag?: string;
  job_id?: number;
  keywords?: string;
  keyword_mode?: "any" | "all";
  include_test?: boolean;
}

export interface FilterOptions {
  categories: string[];
  states: string[];
  cities: string[];
  domains: string[];
  source_types: string[];
  verification_statuses: string[];
  has_test_data: boolean;
}

export interface DashboardStats {
  total_leads_collected: number;
  unique_emails: number;
  unique_businesses: number;
  websites_processed: number;
  successful_crawls: number;
  failed_websites: number;
  skipped_websites: number;
  pending_jobs: number;
  leads_today: number;
  duplicates_removed: number;
  categories: { name: string; count: number }[];
  recent_jobs: Job[];
  includes_test_data: boolean;
}

export interface Column {
  index: number;
  name: string;
  sample: string[];
  url_ratio: number;
  email_ratio: number;
}

export interface Sheet {
  name: string;
  rows: number;
  has_header: boolean;
  columns: Column[];
  suggested_url_columns: number[];
  suggested_email_columns: number[];
  suggested_name_column: number | null;
}

export interface UploadInfo {
  upload_id: string;
  filename: string;
  extension: string;
  kind: string;
  size_bytes: number;
  sheets: Sheet[];
}

export interface PreviewEmail {
  email: string;
  original: string;
  occurrences: number;
  sources: { filename: string; sheet: string | null; row: number | null; page: number | null; context: string }[];
  business_name: string;
  website: string;
}

export interface PreviewResult {
  filename: string;
  kind: string;
  emails_total: number;
  unique_emails: number;
  duplicate_emails: number;
  urls_total: number;
  emails: PreviewEmail[];
  urls: { url: string; original: string; sheet: string | null; row: number | null; page: number | null; business_name: string }[];
  warnings: string[];
  needs_ocr: boolean;
  pages: number | null;
  truncated: boolean;
}

export interface ExportRecord {
  id: number;
  filename: string;
  scope: string;
  description: string | null;
  row_count: number;
  size_bytes: number;
  created_at: string;
  download_url: string;
}

export interface SettingsPayload {
  settings: {
    default_max_pages: number;
    default_max_depth: number;
    default_delay_seconds: number;
    default_concurrency: number;
    default_validate_mx: boolean;
    default_tags: string;
    category_keywords: Record<string, string[]>;
  };
  default_category_keywords: Record<string, string[]>;
  server_limits: Record<string, string | number | boolean | string[]>;
}

export interface CrawlSettings {
  max_pages: number;
  max_depth: number;
  delay: number;
  concurrency: number;
  follow_external: boolean;
  keywords: string[];
  keyword_filter: boolean;
  validate_mx: boolean;
  tags: string;
}

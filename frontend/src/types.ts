export type User = {
  id: string;
  email: string;
  display_name: string;
};

export type Dashboard = {
  documents: number;
  unread: number;
  needs_review: number;
  queued_jobs: number;
  failed_jobs: number;
  projects: number;
};

export type Domain = {
  id: string;
  parent_id: string | null;
  name: string;
  description?: string | null;
  color?: string | null;
  sort_order: number;
  document_count: number;
};

export type Tag = {
  id: string;
  name: string;
  kind: string;
  color?: string | null;
};

export type DocumentSummary = {
  id: string;
  title: string;
  authors: Array<Record<string, string | null>>;
  publication_year?: number | null;
  journal?: string | null;
  doi?: string | null;
  rich_summary?: string | null;
  apa_citation?: string | null;
  citation_status: string;
  metadata_confidence?: number | null;
  original_filename: string;
  checksum_sha256: string;
  page_count: number;
  processing_status: string;
  read_status: string;
  priority: string;
  created_at: string;
  tags: Tag[];
  domains: Domain[];
};

export type DocumentDetail = DocumentSummary & {
  subtitle?: string | null;
  universities: string[];
  publisher?: string | null;
  source_url?: string | null;
  abstract?: string | null;
  metadata_evidence: Record<string, unknown>;
  gcs_uri?: string | null;
  storage_status: string;
  search_text?: string | null;
};

export type Project = {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  due_at?: string | null;
  item_count: number;
};

export type ImportJob = {
  id: string;
  batch_id: string;
  document_id?: string | null;
  status: string;
  current_step: string;
  attempts: number;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
};

export type CitationCandidate = {
  id: string;
  document_id: string;
  source: string;
  citation_text?: string | null;
  metadata: Record<string, unknown>;
  confidence?: number | null;
  status: string;
  created_at: string;
};

export type Bibliography = {
  project_id: string;
  apa: string;
  bibtex: string;
  ris: string;
  csl_json: Record<string, unknown>[];
};

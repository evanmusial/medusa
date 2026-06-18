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
  active_import_jobs: number;
  active_concordance_jobs: number;
  failed_jobs: number;
  failed_import_jobs: number;
  failed_concordance_jobs: number;
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

export type DocumentFilters = {
  domain_id?: string;
  tag_id?: string;
  read_status?: string;
  priority?: string;
  citation_status?: string;
  duplicate_status?: string;
};

export type SavedSearch = {
  id: string;
  name: string;
  query?: string | null;
  filters: DocumentFilters;
  sort_order: number;
  created_at: string;
};

export type AttributeDefinition = {
  id: string;
  name: string;
  value_type: string;
  description?: string | null;
};

export type DocumentAttributeValue = {
  id: string;
  attribute_definition_id: string;
  value: Record<string, unknown>;
  definition: AttributeDefinition;
};

export type DocumentVersion = {
  id: string;
  version_number: number;
  change_note?: string | null;
  metadata_snapshot: Record<string, unknown>;
  created_at: string;
};

export type Figure = {
  id: string;
  page_number?: number | null;
  figure_label?: string | null;
  caption?: string | null;
  gist?: string | null;
  asset_uri?: string | null;
};

export type DocumentPage = {
  id: string;
  page_number: number;
  text?: string | null;
  normalized_text?: string | null;
  text_source: string;
  low_text: boolean;
  image_uri?: string | null;
};

export type Annotation = {
  id: string;
  document_id: string;
  page_number?: number | null;
  kind: string;
  body?: string | null;
  geometry: Record<string, unknown>;
  color?: string | null;
  created_at: string;
  updated_at: string;
};

export type AnnotationPayload = {
  page_number?: number | null;
  kind?: string;
  body?: string | null;
  geometry?: Record<string, unknown>;
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
  duplicate_count: number;
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
  attributes: DocumentAttributeValue[];
  versions: DocumentVersion[];
  pages: DocumentPage[];
  figures: Figure[];
  annotations: Annotation[];
  duplicate_document_ids: string[];
};

export type DocumentUpdatePayload = Partial<DocumentDetail> & {
  tag_names?: string[];
  domain_ids?: string[];
  attribute_values?: Record<string, unknown>;
};

export type Project = {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  due_at?: string | null;
  item_count: number;
};

export type ProjectItem = {
  id: string;
  project_id: string;
  document_id: string;
  status: string;
  priority: string;
  used_in_output: boolean;
  note?: string | null;
  created_at: string;
  updated_at: string;
  document?: DocumentSummary | null;
};

export type ProjectDetail = Project & {
  items: ProjectItem[];
};

export type Note = {
  id: string;
  title: string;
  body: string;
  kind: string;
  document_id?: string | null;
  domain_id?: string | null;
  project_id?: string | null;
  reminder_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type NotePayload = {
  title: string;
  body: string;
  kind?: string;
  document_id?: string | null;
  domain_id?: string | null;
  project_id?: string | null;
  reminder_at?: string | null;
};

export type ImportJob = {
  id: string;
  batch_id: string;
  document_id?: string | null;
  document_title?: string | null;
  original_filename?: string | null;
  file_size_bytes?: number | null;
  status: string;
  current_step: string;
  attempts: number;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
};

export type DuplicateImportStrategy = "skip" | "overwrite" | "import_anyway";

export type ImportDuplicateDocument = {
  id: string;
  title: string;
  original_filename: string;
  created_at: string;
  processing_status: string;
};

export type ImportDuplicateFile = {
  filename: string;
  checksum_sha256: string;
  file_size_bytes: number;
  existing_documents: ImportDuplicateDocument[];
  duplicate_in_upload: boolean;
};

export type ImportDuplicateCheck = {
  files: ImportDuplicateFile[];
  duplicate_file_count: number;
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

export type ConcordanceCapability = {
  key: string;
  label: string;
  version: number;
  description: string;
};

export type ConcordanceRun = {
  id: string;
  label?: string | null;
  scope_type: string;
  scope_data: Record<string, unknown>;
  capability_keys: string[];
  status: string;
  total_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  created_at: string;
  updated_at: string;
};

export type ConcordanceJob = {
  id: string;
  run_id: string;
  document_id: string;
  capability_key: string;
  target_version: number;
  status: string;
  attempts: number;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
};

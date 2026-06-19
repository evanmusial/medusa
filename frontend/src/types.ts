export type User = {
  id: string;
  email: string;
  display_name: string;
};

export type RuntimeLocation = {
  app_name: string;
  expansion: string;
  network_context: "local" | "lan" | "remote" | string;
  ipv4?: string | null;
  title: string;
};

export type Dashboard = {
  documents: number;
  unread: number;
  needs_review: number;
  queued_jobs: number;
  active_import_jobs: number;
  import_queued_jobs: number;
  import_running_jobs: number;
  import_progress_total: number;
  import_progress_completed: number;
  import_progress_failed: number;
  import_active_step?: string | null;
  import_active_elapsed_seconds?: number | null;
  import_active_cost_usd: number;
  active_concordance_jobs: number;
  active_accessory_summary_jobs: number;
  failed_jobs: number;
  failed_import_jobs: number;
  failed_concordance_jobs: number;
  failed_accessory_summary_jobs: number;
  projects: number;
};

export type AppPreferences = {
  import_worker_concurrency: number;
  recommended_import_worker_concurrency: number;
  import_worker_cost_warning_threshold: number;
  accent_color_day: string;
  accent_color_night: string;
  document_cache_size_mb: number;
  library_alternating_rows: boolean;
  gcs_bucket: string;
  gcs_bucket_saved: boolean;
  google_service_account_name: string;
  google_service_account_project_id?: string | null;
  google_service_account_uploaded: boolean;
  google_service_account_source: string;
  google_service_account_uploaded_at?: string | null;
  analysis_models: Record<string, string>;
  analysis_model_tasks: AnalysisModelTask[];
  model_options: Record<string, string[]>;
};

export type AnalysisModelTask = {
  key: string;
  label: string;
  model_kind: "gpt" | "embedding" | "raw_text_extraction" | string;
  default_model: string;
  selected_model: string;
  description: string;
  option_groups: ModelOptionGroup[];
};

export type ModelOptionGroup = {
  label: string;
  options: string[];
};

export type DocumentCompositionEntry = {
  label?: string | null;
  stage_key?: string | null;
  stage_label?: string | null;
  provider?: string | null;
  method?: string | null;
  model?: string | null;
  record_kind?: string | null;
  status?: string | null;
  message?: string | null;
  amount_usd: number;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  call_count: number;
  sequence?: number | null;
  created_at?: string | null;
};

export type DocumentComposition = {
  document_id: string;
  available: boolean;
  total_estimated_cost_usd: number;
  total_duration_seconds: number;
  cost_entries: DocumentCompositionEntry[];
  provider_breakdown: DocumentCompositionEntry[];
  local_duration_entries: DocumentCompositionEntry[];
  pipeline: DocumentCompositionEntry[];
  errata: DocumentCompositionEntry[];
};

export type OpenAIUsageTotals = {
  request_count: number;
  successful_request_count: number;
  failed_request_count: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  reasoning_output_tokens: number;
  total_tokens: number;
  input_file_bytes: number;
  input_text_characters: number;
  output_text_characters: number;
  oldest_created_at?: string | null;
  newest_created_at?: string | null;
  estimated_cost_usd: number;
  priced_request_count: number;
  unpriced_request_count: number;
};

export type OpenAIUsageGroup = {
  group_key?: string | null;
  label?: string | null;
  request_count: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  reasoning_output_tokens: number;
  total_tokens: number;
  input_file_bytes: number;
  failed_request_count: number;
  task_key?: string | null;
  model?: string | null;
  provider?: string | null;
  document_id?: string | null;
  calendar_start?: string | null;
  estimated_cost_usd: number;
  priced_request_count: number;
  unpriced_request_count: number;
};

export type OpenAIUsageRecent = {
  id: string;
  created_at: string;
  document_id?: string | null;
  source?: string | null;
  task_key: string;
  operation: string;
  provider: string;
  model: string;
  endpoint: string;
  status: string;
  page_number?: number | null;
  used_pdf_file: boolean;
  input_file_bytes: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  reasoning_output_tokens: number;
  total_tokens: number;
  estimated_cost_usd?: number | null;
  error_message?: string | null;
};

export type OpenAIUsagePeriod = "last_day" | "last_month" | "last_3_months" | "all_time";

export type OpenAIUsage = {
  period: OpenAIUsagePeriod;
  summary: OpenAIUsageTotals;
  by_task: OpenAIUsageGroup[];
  by_model: OpenAIUsageGroup[];
  by_document: OpenAIUsageGroup[];
  by_calendar_day: OpenAIUsageGroup[];
  by_calendar_hour: OpenAIUsageGroup[];
  recent: OpenAIUsageRecent[];
  pricing: {
    basis: string;
    source_url: string;
    source_urls?: Record<string, string>;
    updated_at: string;
  };
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
  geometry: Record<string, unknown>;
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

export type DocumentPageUpdatePayload = {
  normalized_text: string;
};

export type DocumentTextScrubPayload = {
  text: string;
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

export type AccessorySummary = {
  id: string;
  document_id: string;
  title?: string | null;
  prompt: string;
  summary?: string | null;
  model: string;
  status: string;
  attempts: number;
  last_error?: string | null;
  evidence: Record<string, unknown>;
  locked_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type AccessorySummaryPayload = {
  prompt: string;
  model?: string | null;
  title?: string | null;
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
  apa_citation_model?: string | null;
  apa_citation_source?: string | null;
  apa_in_text_citation?: string | null;
  apa_in_text_citation_model?: string | null;
  apa_in_text_citation_source?: string | null;
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
  accessory_summaries: AccessorySummary[];
  annotations: Annotation[];
  duplicate_document_ids: string[];
};

export type DocumentRecommendation = {
  id: string;
  source_document_id: string;
  existing_document_id?: string | null;
  imported_document_id?: string | null;
  existing_document_title?: string | null;
  title: string;
  doi?: string | null;
  authors: Array<Record<string, string | null>>;
  publication_year?: number | null;
  journal?: string | null;
  description?: string | null;
  source_provider: string;
  source_relation?: string | null;
  external_id?: string | null;
  source_url?: string | null;
  pdf_url?: string | null;
  score?: number | null;
  status: string;
  raw_metadata: Record<string, unknown>;
  has_pdf: boolean;
  last_seen_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type DocumentRecommendationRefresh = {
  document_id: string;
  recommendation_count: number;
  recommendations: DocumentRecommendation[];
};

export type DocumentRecommendationDownload = {
  batch_id: string;
  queued_count: number;
  skipped_existing_count: number;
  unavailable_count: number;
  failed_count: number;
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
  document_page_count?: number | null;
  status: string;
  current_step: string;
  current_model?: string | null;
  estimated_cost_usd: number;
  attempts: number;
  last_error?: string | null;
  locked_at?: string | null;
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
  document_title?: string | null;
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

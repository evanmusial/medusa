export type User = {
  id: string;
  email: string;
  display_name: string;
  two_factor_enabled: boolean;
  two_factor_recovery_codes_remaining: number;
};

export type AccountUpdatePayload = {
  email?: string | null;
  current_password: string;
  new_password?: string | null;
  new_password_confirmation?: string | null;
};

export type TwoFactorSetupPayload = {
  current_password: string;
};

export type TwoFactorSetup = {
  secret: string;
  otpauth_uri: string;
};

export type TwoFactorEnablePayload = {
  current_password: string;
  secret: string;
  otp_code: string;
};

export type TwoFactorEnableResult = {
  user: User;
  recovery_codes: string[];
};

export type TwoFactorDisablePayload = {
  current_password: string;
  otp_code: string;
};

export type RuntimeLocation = {
  app_name: string;
  expansion: string;
  network_context: "local" | "lan" | "remote" | string;
  ipv4?: string | null;
  title: string;
};

export type ReleaseVersion = {
  version?: string | null;
  git_sha?: string | null;
  git_sha_short?: string | null;
  branch?: string | null;
  built_at?: string | null;
  source: string;
};

export type ReleaseStatus = {
  checked_at: string;
  running: ReleaseVersion;
  available?: ReleaseVersion | null;
  update_available: boolean;
  apply_available: boolean;
  browser_reload_recommended: boolean;
  phase: string;
  message: string;
  status_source: string;
  requested_at?: string | null;
  request_id?: string | null;
  last_error?: string | null;
  dirty: boolean;
  maintenance_phase: string;
  maintenance_message?: string | null;
  maintenance_auto_apply_eligible: boolean;
  maintenance_requires_approval: boolean;
  maintenance_update_classification: string;
  maintenance_backup_required: boolean;
  maintenance_backup_status: string;
  maintenance_backup_run_id?: string | null;
  maintenance_idle: boolean;
  maintenance_active_session_count: number;
  maintenance_blockers: string[];
  maintenance_window?: string | null;
  maintenance_last_checked_at?: string | null;
  docker_engine_version?: string | null;
  docker_compose_version?: string | null;
  docker_host_updates: string;
};

export type AIFailureNotice = {
  id: string;
  created_at: string;
  document_id?: string | null;
  document_title?: string | null;
  source?: string | null;
  task_key: string;
  operation: string;
  provider: string;
  model: string;
  endpoint: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  error_message?: string | null;
  estimated_cost_usd?: number | null;
};

export type Dashboard = {
  documents: number;
  unread: number;
  needs_review: number;
  domains: number;
  tags: number;
  notes: number;
  review_items: number;
  stashes: number;
  queued_jobs: number;
  queue_import_jobs: number;
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
  recent_failed_ai_calls: AIFailureNotice[];
  projects: number;
};

export type LibraryFunStats = {
  checked_at: string;
  document_count: number;
  page_count: number;
  page_record_count: number;
  figure_count: number;
  bibliography_reference_count: number;
  bibliography_document_count: number;
  parsed_word_count: number;
  indexed_word_count: number;
  parsed_character_count: number;
  indexed_character_count: number;
  text_chunk_count: number;
  text_chunk_token_count: number;
  doi_count: number;
  verified_citation_count: number;
  unique_author_count: number;
  annotation_count: number;
  note_count: number;
  project_resource_count: number;
  used_project_resource_count: number;
  domain_count: number;
  tag_count: number;
};

export type CacheFamilyStats = {
  family: string;
  hits: number;
  misses: number;
  bypasses: number;
  errors: number;
  writes: number;
  hit_rate: number;
};

export type CacheRequestMetric = {
  route: string;
  count: number;
  p95_ms: number;
  average_ms: number;
  slow_count: number;
  last_status?: number | null;
};

export type CacheQueueStat = {
  queue: string;
  active_count: number;
  oldest_age_seconds?: number | null;
};

export type CacheDatabaseFootprint = {
  name: string;
  kind: string;
  total_bytes: number;
  relation_bytes: number;
};

export type CacheStorageFootprint = {
  label: string;
  path: string;
  exists: boolean;
  size_bytes: number;
  file_count: number;
};

export type CacheStatus = {
  checked_at: string;
  backend: string;
  enabled: boolean;
  reachable: boolean;
  mode: string;
  message: string;
  version?: string | null;
  uptime_seconds?: number | null;
  used_memory_bytes?: number | null;
  peak_memory_bytes?: number | null;
  rss_memory_bytes?: number | null;
  maxmemory_bytes?: number | null;
  maxmemory_policy?: string | null;
  key_count: number;
  hit_count: number;
  miss_count: number;
  hit_rate: number;
  evicted_keys: number;
  expired_keys: number;
  connected_clients: number;
  ops_per_second: number;
  latency_ms?: number | null;
  last_refresh_at?: string | null;
  last_hydration_at?: string | null;
  last_invalidation_at?: string | null;
  families: CacheFamilyStats[];
  request_metrics: CacheRequestMetric[];
  queue_stats: CacheQueueStat[];
  database_footprints: CacheDatabaseFootprint[];
  storage_footprints: CacheStorageFootprint[];
};

export type SlipstreamClient = {
  id: string;
  name: string;
  version?: string | null;
  capabilities: string[];
  capacity: number;
  status: string;
  last_check_in_at?: string | null;
  online: boolean;
  revoked_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type SlipstreamLease = {
  id: string;
  client_id?: string | null;
  client_name?: string | null;
  worker_kind: string;
  job_type: string;
  job_id: string;
  status: string;
  claimed_at: string;
  heartbeat_at: string;
  expires_at: string;
  completed_at?: string | null;
  canceled_at?: string | null;
  last_error?: string | null;
};

export type SlipstreamStatus = {
  enabled: boolean;
  public_base_url?: string | null;
  heartbeat_seconds: number;
  lease_ttl_seconds: number;
  require_tls: boolean;
  clients: SlipstreamClient[];
  active_leases: SlipstreamLease[];
  online_client_count: number;
  active_lease_count: number;
  oldest_active_lease_age_seconds?: number | null;
  failed_or_expired_lease_count: number;
};

export type SlipstreamEnrollment = {
  id: string;
  label?: string | null;
  status: string;
  expires_at: string;
  used_at?: string | null;
  client_id?: string | null;
  token?: string | null;
  created_at: string;
};

export type CacheRefreshResult = {
  status: string;
  message: string;
  refreshed_at: string;
  refreshed_families: string[];
  warmed_keys: number;
  before: CacheStatus;
  after: CacheStatus;
};

export type CacheHydrateResult = {
  status: string;
  message: string;
  hydrated_at: string;
  hydrated_keys: number;
  base_keys: number;
  document_count: number;
  document_detail_keys: number;
  list_page_keys: number;
  saved_search_keys: number;
  organization_keys: number;
  skipped_payloads: number;
  errored_payloads: number;
  before: CacheStatus;
  after: CacheStatus;
};

export type AppPreferences = {
  import_worker_concurrency: number;
  recommended_import_worker_concurrency: number;
  import_worker_cost_warning_threshold: number;
  accent_color_day: string;
  accent_color_night: string;
  document_cache_size_mb: number;
  valkey_maxmemory: string;
  library_alternating_rows: boolean;
  library_page_size: number;
  library_density: "compact" | "comfortable" | "reading";
  detail_sticky_fields: string[];
  download_naming_template: string;
  citation_convention: string;
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
  model_pricing: ModelPricingStatus;
  import_processing_presets: ImportProcessingPreset[];
  default_import_processing_preset_id: string;
  import_processing_steps: ImportProcessingStep[];
  second_pass_processing_enabled: boolean;
};

export type GcsBucketLifecycleRule = {
  index: number;
  action_type: string;
  action_label: string;
  storage_class?: string | null;
  condition_labels: string[];
  summary: string;
};

export type GcsBucketLifecycle = {
  bucket: string;
  available: boolean;
  status: string;
  summary: string;
  rules: GcsBucketLifecycleRule[];
  checked_at: string;
  error?: string | null;
  storage_class?: string | null;
  location?: string | null;
};

export type ImportProcessingPreset = {
  id: string;
  name: string;
  mode: string;
  built_in: boolean;
  description?: string;
  cleanup: Record<string, unknown>;
  ocr: Record<string, unknown>;
  structured_tables: Record<string, unknown>;
  bibliography: Record<string, unknown>;
  visuals: Record<string, unknown>;
  cost: Record<string, unknown>;
  snapshot_version?: number;
  snapshot_at?: string;
  second_pass_enabled?: boolean;
};

export type ImportProcessingStep = {
  key: string;
  label: string;
  description: string;
  accomplishes: string;
  tooltip: string;
  default_enabled: boolean;
  configurable: boolean;
};

export type IngestionHistory = {
  batch_id: string;
  label?: string | null;
  status: string;
  active: boolean;
  total_files: number;
  completed_files: number;
  failed_files: number;
  queued_files: number;
  running_files: number;
  staged_files: number;
  cleared_files: number;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  cost_variance_usd?: number | null;
  cost_per_document_usd?: number | null;
  total_size_bytes: number;
  processing_preset_id?: string | null;
  processing_preset_name?: string | null;
  processing_preset_mode?: string | null;
  latest_stage?: string | null;
  duration_seconds?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type DocumentCacheStatus = {
  current_size_bytes: number;
  current_size_mb: number;
  file_count: number;
};

export type BackupRun = {
  id: string;
  kind: "backup" | "restore" | string;
  reason?: string | null;
  status: "queued" | "running" | "complete" | "failed" | string;
  phase: string;
  progress: number;
  status_detail?: string | null;
  hostname?: string | null;
  filename?: string | null;
  object_key?: string | null;
  gcs_uri?: string | null;
  size_bytes?: number | null;
  sha256?: string | null;
  source_kind?: string | null;
  source_filename?: string | null;
  source_uri?: string | null;
  safety_backup_id?: string | null;
  backup_metadata: Record<string, unknown>;
  last_error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type BackupArtifact = {
  id: string;
  filename: string;
  object_key: string;
  uri: string;
  storage_kind: string;
  gcs_uri?: string | null;
  local_path?: string | null;
  size_bytes: number;
  sha256?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  hostname?: string | null;
  verified: boolean;
  manifest: Record<string, unknown>;
};

export type BackupEstimate = {
  database_size_bytes?: number | null;
  estimated_size_bytes?: number | null;
  latest_backup_size_bytes?: number | null;
  latest_backup_completed_at?: string | null;
  basis: "latest_backup_ratio" | "latest_backup" | "database_size_upper_bound" | "unavailable" | string;
  storage_kind?: string | null;
  storage_label?: string | null;
};

export type DatabaseMaintenanceStatus = {
  import_cache_count: number;
  document_hash_missing_count: number;
  hidden_project_item_count: number;
  terminal_import_job_count: number;
  orphan_import_job_count: number;
  database_size_bytes?: number | null;
  active_operation?: string | null;
  active_operation_label?: string | null;
  active_operation_started_at?: string | null;
  active_operation_elapsed_seconds?: number | null;
  active_operation_status_detail?: string | null;
  last_operation?: string | null;
  last_operation_status?: string | null;
  last_operation_completed_at?: string | null;
  last_operation_status_detail?: string | null;
  last_operation_error?: string | null;
  last_operation_database_size_before_bytes?: number | null;
  last_operation_database_size_after_bytes?: number | null;
};

export type DatabaseMaintenanceResult = DatabaseMaintenanceStatus & {
  operation: string;
  status: string;
  message: string;
  database_size_before_bytes?: number | null;
  database_size_after_bytes?: number | null;
  removed_import_documents: number;
  removed_project_items: number;
  removed_import_jobs: number;
  removed_orphan_import_jobs: number;
  deleted_cache_files: number;
  deleted_original_objects: number;
};

export type ContainerFilesystem = {
  path: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
};

export type ContainerPathFootprint = {
  label: string;
  path: string;
  exists: boolean;
  size_bytes: number;
  file_count: number;
  directory_count: number;
};

export type ContainerRuntimeVersion = {
  name: string;
  version: string;
  source: string;
  status: string;
  note?: string | null;
};

export type ContainerDockerLayer = {
  id: string;
  created_by?: string | null;
  size_bytes: number;
  tags: string[];
  comment?: string | null;
};

export type ContainerDockerImage = {
  id: string;
  repo_tags: string[];
  size_bytes?: number | null;
  virtual_size_bytes?: number | null;
  shared_size_bytes?: number | null;
  unique_size_bytes?: number | null;
  containers?: number | null;
  layer_count: number;
  layers: ContainerDockerLayer[];
};

export type ContainerFootprintStatus = {
  checked_at: string;
  hostname: string;
  containerized: boolean;
  docker_socket_available: boolean;
  docker_engine_note: string;
  docker_image?: ContainerDockerImage | null;
  restart_available: boolean;
  restart_mode: string;
  restart_note: string;
  restart_requested_at?: string | null;
  process_uptime_seconds: number;
  memory_current_bytes?: number | null;
  memory_limit_bytes?: number | null;
  memory_peak_bytes?: number | null;
  process_rss_bytes?: number | null;
  cpu_limit_cores?: number | null;
  cpu_usage_seconds?: number | null;
  process_count?: number | null;
  thread_count?: number | null;
  platform: string;
  python_version: string;
  data_dir: string;
  data_dir_size_bytes: number;
  data_filesystem?: ContainerFilesystem | null;
  root_filesystem?: ContainerFilesystem | null;
  paths: ContainerPathFootprint[];
  runtime_versions: ContainerRuntimeVersion[];
};

export type ContainerRestartResult = {
  status: string;
  message: string;
  restart_mode: string;
  poll_after_seconds: number;
};

export type HAProxyServiceStat = {
  proxy_name: string;
  service_name: string;
  kind: string;
  status?: string | null;
  current_sessions: number;
  max_sessions: number;
  total_sessions: number;
  session_rate: number;
  bytes_in: number;
  bytes_out: number;
  denied_requests: number;
  denied_responses: number;
  error_requests: number;
  error_connections: number;
  error_responses: number;
  retries: number;
  redispatches: number;
  active_servers?: number | null;
  backup_servers?: number | null;
  check_status?: string | null;
  check_code?: number | null;
  check_duration_ms?: number | null;
  last_change_seconds?: number | null;
  downtime_seconds?: number | null;
};

export type HAProxyStatsStatus = {
  checked_at: string;
  available: boolean;
  message: string;
  public_url: string;
  stats_url: string;
  total_current_sessions: number;
  total_sessions: number;
  total_bytes_in: number;
  total_bytes_out: number;
  total_errors: number;
  services: HAProxyServiceStat[];
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

export type DocumentCompositionEstimate = {
  estimated_cost_usd: number;
  actual_cost_usd: number;
  variance_usd?: number | null;
  variance_percent?: number | null;
  actual_to_estimate_ratio?: number | null;
  estimated_page_count?: number | null;
  basis?: string | null;
  status: string;
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
  estimate_comparison?: DocumentCompositionEstimate | null;
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

export type ModelPricingStatus = {
  basis: string;
  price_basis?: string;
  openai_pricing_tier?: string;
  source_url: string;
  source_urls?: Record<string, string>;
  updated_at: string;
  last_refreshed_at?: string | null;
  stale: boolean;
  stale_after_days: number;
  model_count: number;
  current_model_count: number;
  missing_current_model_count?: number;
  provider_counts: Record<string, number>;
  checked_count?: number;
  inserted_count?: number;
  changed_count?: number;
  unchanged_count?: number;
};

export type OpenAIUsage = {
  period: OpenAIUsagePeriod;
  summary: OpenAIUsageTotals;
  by_task: OpenAIUsageGroup[];
  by_model: OpenAIUsageGroup[];
  by_document: OpenAIUsageGroup[];
  by_calendar_day: OpenAIUsageGroup[];
  by_calendar_hour: OpenAIUsageGroup[];
  recent: OpenAIUsageRecent[];
  pricing: ModelPricingStatus;
};

export type Domain = {
  id: string;
  parent_id: string | null;
  name: string;
  description?: string | null;
  color?: string | null;
  sort_order: number;
  document_count: number;
  subtree_document_count: number;
  tags: Tag[];
};

export type DomainUpdatePayload = {
  name?: string | null;
  parent_id?: string | null;
  description?: string | null;
  color?: string | null;
  sort_order?: number | null;
  tag_ids?: string[] | null;
};

export type DomainReorderItem = {
  id: string;
  parent_id?: string | null;
  sort_order: number;
};

export type DomainDeleteResult = {
  deleted_id: string;
  updated_documents: number;
};

export type Tag = {
  id: string;
  name: string;
  color?: string | null;
  status: string;
  definition?: string | null;
  use_guidance?: string | null;
  avoid_guidance?: string | null;
  document_count: number;
};

export type TagOperationResult = {
  tag: Tag;
  updated_documents: number;
  removed_tag_ids: string[];
};

export type TagOptimizationSuggestion = {
  id: string;
  target_name: string;
  target_tag_id?: string | null;
  source_tag_ids: string[];
  source_tags: Tag[];
  affected_documents: number;
  rationale: string;
  confidence: number;
};

export type TagRelationshipSuggestion = {
  id: string;
  source_tag: Tag;
  target_tag: Tag;
  relationship_type: string;
  rationale: string;
  confidence: number;
};

export type TagStatusSuggestion = {
  id: string;
  tag: Tag;
  suggested_status: string;
  rationale: string;
  confidence: number;
};

export type TagPruneSuggestion = {
  id: string;
  document_id: string;
  document_title: string;
  tag: Tag;
  rationale: string;
  confidence: number;
  relevance_score: number;
  library_fit_score: number;
  novelty_score: number;
  overall_score: number;
};

export type TagOrphanPruneSuggestion = {
  id: string;
  tag: Tag;
  rationale: string;
  confidence: number;
};

export type TagOptimizationResult = {
  model: string;
  considered_tags: number;
  suggestions: TagOptimizationSuggestion[];
  singleton_suggestions?: TagOptimizationSuggestion[];
  orphan_merge_suggestions?: TagOptimizationSuggestion[];
  relationship_suggestions?: TagRelationshipSuggestion[];
  status_suggestions?: TagStatusSuggestion[];
  pruning_suggestions?: TagPruneSuggestion[];
  orphan_prune_suggestions?: TagOrphanPruneSuggestion[];
  health_summary?: Record<string, number>;
};

export type TagOptimizationApproveAllPayload = {
  merge_suggestions: {
    id?: string | null;
    source_tag_ids: string[];
    target_tag_id?: string | null;
    target_name?: string | null;
  }[];
  relationship_suggestions: {
    id?: string | null;
    source_tag_id: string;
    target_tag_id: string;
    relationship_type: string;
    rationale?: string | null;
    confidence?: number | null;
  }[];
  status_suggestions: {
    id?: string | null;
    tag_id: string;
    suggested_status: string;
    rationale?: string | null;
  }[];
  pruning_suggestions: {
    id?: string | null;
    document_id: string;
    tag_id: string;
    rationale?: string | null;
  }[];
  orphan_prune_suggestions: {
    id?: string | null;
    tag_id: string;
    rationale?: string | null;
  }[];
};

export type TagOptimizationApproveAllResult = {
  merges_applied: number;
  relationships_applied: number;
  statuses_applied: number;
  prunes_applied: number;
  orphans_pruned: number;
  updated_documents: number;
  removed_tag_ids: string[];
  skipped: { kind: string; id: string; reason: string }[];
};

export type DocumentFilters = {
  domain_id?: string;
  tag_id?: string;
  read_status?: string;
  priority?: string;
  citation_status?: string;
  duplicate_status?: string;
  health_status?: string;
};

export type SavedSearch = {
  id: string;
  name: string;
  query?: string | null;
  filters: DocumentFilters;
  sort_order: number;
  created_at: string;
};

export type ReconEvidence = {
  id: string;
  run_id: string;
  document_id?: string | null;
  text_chunk_id?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  evidence_kind: string;
  rank: number;
  score?: number | null;
  document_title?: string | null;
  snippet: string;
  citation_text?: string | null;
  relevance_label: string;
  evidence_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ReconAnswerVersion = {
  id: string;
  run_id: string;
  answer: string;
  confidence?: number | null;
  limitations: string[];
  answer_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ReconRun = {
  id: string;
  inquiry_id: string;
  mode: string;
  model: string;
  status: string;
  progress: number;
  resolved_document_count: number;
  evidence_count: number;
  estimated_input_tokens: number;
  estimated_cost_usd?: number | null;
  answer_summary?: string | null;
  scope_snapshot: Record<string, unknown>;
  run_metadata: Record<string, unknown>;
  last_error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  cancelled_at?: string | null;
  evidence: ReconEvidence[];
  answers: ReconAnswerVersion[];
  created_at: string;
  updated_at: string;
};

export type ReconInquiry = {
  id: string;
  title: string;
  question: string;
  instructions?: string | null;
  scope_type: string;
  scope: Record<string, unknown>;
  default_mode: string;
  model: string;
  status: string;
  inquiry_metadata: Record<string, unknown>;
  runs: ReconRun[];
  created_at: string;
  updated_at: string;
};

export type ReconInquiryPayload = {
  title?: string | null;
  question: string;
  instructions?: string | null;
  scope_type?: string;
  scope?: Record<string, unknown>;
  default_mode?: string;
  model?: string | null;
};

export type ReconInquiryPatch = Partial<{
  title: string | null;
  question: string;
  instructions: string | null;
  scope_type: string;
  scope: Record<string, unknown>;
  default_mode: string;
  model: string;
  status: string;
}>;

export type ReconEstimate = {
  mode: string;
  scope_type: string;
  resolved_document_count: number;
  estimated_evidence_count: number;
  estimated_input_tokens: number;
  estimated_cost_usd?: number | null;
  warnings: string[];
};

export type ReconRunPayload = {
  mode?: string | null;
  model?: string | null;
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

export type FigurePatchPayload = {
  figure_label?: string | null;
  caption?: string | null;
  gist?: string | null;
};

export type VisualScanCandidate = {
  candidate_id: string;
  page_number: number;
  figure_label?: string | null;
  caption?: string | null;
  gist?: string | null;
  geometry: Record<string, unknown>;
  image_data_url: string;
};

export type VisualScanReview = {
  document_id: string;
  page_number: number;
  figures: number;
  replaced_figures: number;
  preserved_existing: boolean;
  candidates: VisualScanCandidate[];
  replaced_page_figures: Figure[];
  audit_warnings: Array<Record<string, unknown>>;
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

export type DocumentTrashResult = {
  trashed: number;
  document_ids: string[];
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
  no_doi: boolean;
  original_filename: string;
  checksum_sha256: string;
  checksum_md5?: string | null;
  page_count: number;
  processing_status: string;
  read_status: string;
  priority: string;
  created_at: string;
  updated_at: string;
  duplicate_count: number;
  duplicate_reasons: string[];
  tags: Tag[];
  domains: Domain[];
  projects?: Project[];
};

export type DocumentListRow = {
  id: string;
  title: string;
  authors: Array<Record<string, string | null>>;
  publication_year?: number | null;
  rich_summary?: string | null;
  citation_status: string;
  no_doi: boolean;
  page_count: number;
  processing_status: string;
  read_status: string;
  priority: string;
  updated_at: string;
  duplicate_count: number;
  duplicate_reasons: string[];
  tags: Tag[];
  domains: Domain[];
  projects?: Project[];
};

export type DocumentListSort = "title" | "date" | "page_count";

export type DocumentListResponse = {
  items: DocumentListRow[];
  total_count: number;
  total_page_count: number;
  offset: number;
  limit: number;
  has_more: boolean;
  revision: string;
  focus_document_id?: string | null;
  focus_index?: number | null;
};

export type DocumentDetail = DocumentSummary & {
  subtitle?: string | null;
  universities: string[];
  publisher?: string | null;
  source_url?: string | null;
  abstract?: string | null;
  bibliography?: string | null;
  bibliography_generated_at?: string | null;
  doi_verified_at?: string | null;
  doi_verified_by?: string | null;
  apa_citation_verified_at?: string | null;
  apa_citation_verified_by?: string | null;
  apa_in_text_citation_verified_at?: string | null;
  apa_in_text_citation_verified_by?: string | null;
  bibliography_verified_at?: string | null;
  bibliography_verified_by?: string | null;
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

export type PortfolioVersionEdge = {
  id: string;
  parent_version_id: string;
  child_version_id: string;
  relation_type: string;
  edge_metadata: Record<string, unknown>;
  created_at: string;
};

export type PortfolioVersion = {
  id: string;
  portfolio_item_id: string;
  document_id: string;
  version_number: number;
  label?: string | null;
  upload_note?: string | null;
  source_filename: string;
  source_content_type: string;
  source_checksum_sha256: string;
  source_checksum_md5?: string | null;
  source_storage_uri?: string | null;
  source_size_bytes: number;
  processing_status: string;
  version_metadata: Record<string, unknown>;
  document?: DocumentSummary | null;
  parent_edges: PortfolioVersionEdge[];
  created_at: string;
  updated_at: string;
};

export type PortfolioMaterial = {
  id: string;
  portfolio_item_id: string;
  version_id?: string | null;
  document_id: string;
  role: string;
  label?: string | null;
  required_for_assessment: boolean;
  notes?: string | null;
  material_metadata: Record<string, unknown>;
  document?: DocumentSummary | null;
  created_at: string;
  updated_at: string;
};

export type PortfolioSuggestion = {
  id: string;
  portfolio_item_id: string;
  version_id?: string | null;
  library_document_id?: string | null;
  source_type: string;
  title: string;
  source_url?: string | null;
  relation_family: string;
  score?: number | null;
  status: string;
  evidence: Record<string, unknown>;
  library_document?: DocumentSummary | null;
  created_at: string;
  updated_at: string;
};

export type PortfolioAssessmentFinding = {
  id: string;
  assessment_run_id: string;
  category: string;
  severity: string;
  title: string;
  body?: string | null;
  evidence: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
};

export type PortfolioAssessmentRun = {
  id: string;
  portfolio_item_id: string;
  version_id?: string | null;
  mode: string;
  model_ids: string[];
  status: string;
  summary?: string | null;
  assessment_metadata: Record<string, unknown>;
  last_error?: string | null;
  completed_at?: string | null;
  findings: PortfolioAssessmentFinding[];
  created_at: string;
  updated_at: string;
};

export type PortfolioItem = {
  id: string;
  title: string;
  description?: string | null;
  status: string;
  current_version_id?: string | null;
  project_ids: string[];
  domain_ids: string[];
  tag_ids: string[];
  portfolio_metadata: Record<string, unknown>;
  current_version?: PortfolioVersion | null;
  versions: PortfolioVersion[];
  materials: PortfolioMaterial[];
  suggestions: PortfolioSuggestion[];
  assessment_runs: PortfolioAssessmentRun[];
  created_at: string;
  updated_at: string;
};

export type PortfolioItemPayload = {
  title: string;
  description?: string | null;
  project_ids?: string[];
  domain_ids?: string[];
  tag_ids?: string[];
};

export type PortfolioItemPatchPayload = Partial<{
  title: string;
  description: string | null;
  status: string;
  current_version_id: string;
  project_ids: string[];
  domain_ids: string[];
  tag_ids: string[];
}>;

export type PortfolioSuggestionRefresh = {
  portfolio_item_id: string;
  suggestion_count: number;
  suggestions: PortfolioSuggestion[];
};

export type PortfolioAssessmentPayload = {
  mode?: string;
  version_id?: string | null;
  model_ids?: string[] | null;
};

export type RecommendationView = "discover" | "known" | "all";
export type RecommendationFamily =
  | "diverse"
  | "closest"
  | "newer"
  | "foundational"
  | "methods"
  | "contrasting"
  | "open_pdf"
  | "reference_material";

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
  relation_family: RecommendationFamily | string;
  reason_chips: string[];
  known_status: "new" | "in_library" | "active_import" | "stashed" | string;
  hidden_reason?: string | null;
  diversity_score?: number | null;
  scholar_url: string;
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

export type DoiStash = {
  id: string;
  doi: string;
  title?: string | null;
  authors: Array<Record<string, string | null>>;
  publication_year?: number | null;
  journal?: string | null;
  description?: string | null;
  page_count?: number | null;
  metadata_source?: string | null;
  source_url?: string | null;
  source_provider?: string | null;
  source_document_id?: string | null;
  recommendation_id?: string | null;
  imported_document_id?: string | null;
  imported_document_title?: string | null;
  library_match_basis?: "doi" | "title" | "doi_title" | string | null;
  import_job_id?: string | null;
  import_job_status?: string | null;
  status: string;
  uploaded_filename?: string | null;
  imported_at?: string | null;
  stash_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type DoiStashImportResult = {
  stash: DoiStash;
  batch_id: string;
  queued_count: number;
  skipped_existing_count: number;
  unavailable_count: number;
  failed_count: number;
  message?: string | null;
};

export type DoiStashPayload = {
  doi: string;
  title?: string | null;
  source_url?: string | null;
  source_provider?: string | null;
  source_document_id?: string | null;
  recommendation_id?: string | null;
};

export type DocumentUpdatePayload = Partial<DocumentDetail> & {
  tag_names?: string[];
  domain_ids?: string[];
  project_ids?: string[];
  attribute_values?: Record<string, unknown>;
  confirm_verified_doi_edit?: boolean;
  confirm_verified_apa_citation_edit?: boolean;
  confirm_verified_apa_in_text_citation_edit?: boolean;
  confirm_verified_bibliography_edit?: boolean;
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
  estimated_cost_basis: string;
  estimated_cost_page_count?: number | null;
  processing_preset_id?: string | null;
  processing_preset_name?: string | null;
  processing_preset_mode?: string | null;
  attempts: number;
  last_error?: string | null;
  locked_at?: string | null;
  assigned_worker_kind?: string | null;
  assigned_client_id?: string | null;
  assigned_client_name?: string | null;
  lease_heartbeat_at?: string | null;
  lease_expires_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type ImportQueueActionResult = {
  matched_count: number;
  updated_count: number;
  skipped_running_count: number;
  skipped_unretryable_count: number;
  deleted_documents?: number;
  deleted_cache_files?: number;
  deleted_original_objects?: number;
  hashed_documents?: number;
  hash_failed_documents?: number;
};

export type DuplicateImportStrategy = "skip" | "overwrite" | "import_anyway";

export type ImportDuplicateDocument = {
  id: string;
  title: string;
  original_filename: string;
  created_at: string;
  processing_status: string;
  match_reasons: string[];
  match_basis?: string | null;
  match_score: number;
};

export type ImportDuplicateFile = {
  filename: string;
  checksum_sha256: string;
  checksum_md5?: string | null;
  file_size_bytes: number;
  source_kind: string;
  stored_filename?: string | null;
  detected_title?: string | null;
  existing_documents: ImportDuplicateDocument[];
  duplicate_in_upload: boolean;
  duplicate_reasons: string[];
};

export type ImportDuplicateCheck = {
  files: ImportDuplicateFile[];
  duplicate_file_count: number;
};

export type DuplicateDocument = {
  id: string;
  title: string;
  authors: Array<Record<string, string | null>>;
  publication_year?: number | null;
  journal?: string | null;
  doi?: string | null;
  original_filename: string;
  checksum_sha256: string;
  checksum_md5?: string | null;
  page_count: number;
  processing_status: string;
  citation_status: string;
  created_at: string;
  updated_at: string;
  version_count: number;
  latest_version_at?: string | null;
};

export type DuplicatePair = {
  id: string;
  left: DuplicateDocument;
  right: DuplicateDocument;
  match_reasons: string[];
  match_basis: string;
  match_score: number;
};

export type DuplicateScan = {
  pairs: DuplicatePair[];
  pair_count: number;
  document_count: number;
};

export type DuplicateResolveResult = {
  keep_document_id: string;
  duplicate_document_id: string;
  status: string;
};

export type DuplicateDismissResult = {
  left_document_id: string;
  right_document_id: string;
  status: string;
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

export type ConcordanceEstimateItem = {
  document_id: string;
  document_title?: string | null;
  capability_key: string;
  capability_label: string;
  target_version: number;
  status: string;
  reason?: string | null;
  estimated_cost_usd: number;
  estimate_basis: string;
  requirements: Record<string, unknown>[];
  cost_steps: Record<string, unknown>[];
};

export type ConcordanceRunEstimate = {
  scope_type: string;
  scope_data: Record<string, unknown>;
  capability_keys: string[];
  document_count: number;
  planned_jobs: number;
  skipped_jobs: number;
  model_no_op_jobs: number;
  already_queued_jobs: number;
  current_version_jobs: number;
  estimated_cost_usd: number;
  priced_call_count: number;
  unpriced_call_count: number;
  local_job_count: number;
  items: ConcordanceEstimateItem[];
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
  locked_at?: string | null;
  assigned_worker_kind?: string | null;
  assigned_client_id?: string | null;
  assigned_client_name?: string | null;
  lease_heartbeat_at?: string | null;
  lease_expires_at?: string | null;
  created_at: string;
  updated_at: string;
};

import type {
  AccessorySummary,
  AccessorySummaryPayload,
  Annotation,
  AnnotationPayload,
  AppPreferences,
  BackupArtifact,
  BackupEstimate,
  BackupRun,
  Bibliography,
  CitationCandidate,
  ConcordanceCapability,
  ConcordanceJob,
  ConcordanceRun,
  ConcordanceRunEstimate,
  ContainerFootprintStatus,
  ContainerRestartResult,
  Dashboard,
  DatabaseMaintenanceResult,
  DatabaseMaintenanceStatus,
  DocumentDetail,
  DocumentCacheStatus,
  DocumentComposition,
  DocumentFilters,
  DocumentPageUpdatePayload,
  DocumentRecommendation,
  DocumentRecommendationDownload,
  DocumentRecommendationRefresh,
  DocumentSummary,
  DocumentTextScrubPayload,
  DocumentUpdatePayload,
  DoiStash,
  DoiStashImportResult,
  DoiStashPayload,
  Domain,
  DomainDeleteResult,
  DomainReorderItem,
  DomainUpdatePayload,
  DuplicateImportStrategy,
  HAProxyStatsStatus,
  ImportDuplicateCheck,
  ImportJob,
  ImportQueueActionResult,
  Note,
  NotePayload,
  ModelPricingStatus,
  OpenAIUsage,
  OpenAIUsagePeriod,
  Project,
  ProjectDetail,
  ProjectItem,
  RuntimeLocation,
  SavedSearch,
  Tag,
  TagOptimizationApproveAllPayload,
  TagOptimizationApproveAllResult,
  TagOptimizationResult,
  TagOperationResult,
  User,
} from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<User>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<{ status: string }>("/api/auth/logout", { method: "POST" }),
  me: () => request<User>("/api/me"),
  runtimeLocation: (browserHost: string) =>
    request<RuntimeLocation>(`/api/runtime-location?browser_host=${encodeURIComponent(browserHost)}`),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  preferences: () => request<AppPreferences>("/api/preferences"),
  documentCacheStatus: () => request<DocumentCacheStatus>("/api/document-cache/status"),
  backupRuns: () => request<BackupRun[]>("/api/backups/runs"),
  backupEstimate: () => request<BackupEstimate>("/api/backups/estimate"),
  databaseMaintenanceStatus: () => request<DatabaseMaintenanceStatus>("/api/utilities/database/status"),
  compactDatabase: () =>
    request<DatabaseMaintenanceResult>("/api/utilities/database/compact", { method: "POST" }),
  optimizeDatabase: () =>
    request<DatabaseMaintenanceResult>("/api/utilities/database/optimize", { method: "POST" }),
  clearImportCache: () =>
    request<DatabaseMaintenanceResult>("/api/utilities/import-cache/clear", { method: "POST" }),
  containerFootprintStatus: () => request<ContainerFootprintStatus>("/api/utilities/container/status"),
  restartContainer: () => request<ContainerRestartResult>("/api/utilities/container/restart", { method: "POST" }),
  haproxyStatus: () => request<HAProxyStatsStatus>("/api/utilities/haproxy/status"),
  gcsBackups: () => request<BackupArtifact[]>("/api/backups/gcs"),
  startDatabaseBackup: () => request<BackupRun>("/api/backups/database", { method: "POST" }),
  startDatabaseRestore: (gcsUri: string) =>
    request<BackupRun>("/api/restores/database", { method: "POST", body: JSON.stringify({ gcs_uri: gcsUri }) }),
  startDatabaseRestoreUpload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<BackupRun>("/api/restores/database/upload", { method: "POST", body: form });
  },
  openaiUsage: (period: OpenAIUsagePeriod = "all_time") => request<OpenAIUsage>(`/api/openai/usage?period=${period}`),
  refreshModelsAndPricing: () => request<ModelPricingStatus>("/api/model-pricing/refresh", { method: "POST" }),
  updatePreferences: (
    body: Partial<
      Pick<
        AppPreferences,
        | "import_worker_concurrency"
        | "accent_color_day"
        | "accent_color_night"
        | "document_cache_size_mb"
        | "library_alternating_rows"
        | "download_naming_template"
        | "citation_convention"
        | "gcs_bucket"
        | "analysis_models"
        | "import_processing_presets"
        | "default_import_processing_preset_id"
        | "second_pass_processing_enabled"
      >
    >,
  ) =>
    request<AppPreferences>("/api/preferences", { method: "PATCH", body: JSON.stringify(body) }),
  uploadGoogleServiceAccount: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<AppPreferences>("/api/preferences/google-service-account", { method: "POST", body: form });
  },
  domains: () => request<Domain[]>("/api/domains"),
  createDomain: (name: string, parentId?: string | null, color?: string | null, description?: string | null) =>
    request<Domain>("/api/domains", {
      method: "POST",
      body: JSON.stringify({ name, parent_id: parentId || null, color: color || null, description: description || null }),
    }),
  updateDomain: (id: string, body: DomainUpdatePayload) =>
    request<Domain>(`/api/domains/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  reorderDomains: (domains: DomainReorderItem[]) =>
    request<Domain[]>("/api/domains/reorder", { method: "POST", body: JSON.stringify({ domains }) }),
  deleteDomain: (id: string) => request<DomainDeleteResult>(`/api/domains/${id}`, { method: "DELETE" }),
  tags: () => request<Tag[]>("/api/tags"),
  createTag: (name: string) => request<Tag>("/api/tags", { method: "POST", body: JSON.stringify({ name }) }),
  renameTag: (id: string, name: string) =>
    request<TagOperationResult>(`/api/tags/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  updateTagGovernance: (id: string, body: { status?: string | null; definition?: string | null; use_guidance?: string | null; avoid_guidance?: string | null }) =>
    request<Tag>(`/api/tags/${id}/governance`, { method: "PATCH", body: JSON.stringify(body) }),
  mergeTags: (body: { source_tag_ids: string[]; target_tag_id?: string | null; target_name?: string | null }) =>
    request<TagOperationResult>("/api/tags/merge", { method: "POST", body: JSON.stringify(body) }),
  createTagRelationship: (body: { source_tag_id: string; target_tag_id: string; relationship_type: string; rationale?: string | null; confidence?: number | null }) =>
    request<unknown>("/api/tags/relationships", { method: "POST", body: JSON.stringify(body) }),
  pruneTagAssignment: (body: { document_id: string; tag_id: string; rationale?: string | null }) =>
    request<unknown>("/api/tags/assignments/prune", { method: "POST", body: JSON.stringify(body) }),
  pruneOrphanTag: (body: { tag_id: string; rationale?: string | null }) =>
    request<{ tag_id: string; tag_name: string; removed_tag_ids: string[] }>("/api/tags/orphans/prune", { method: "POST", body: JSON.stringify(body) }),
  optimizeTags: (body: { tag_ids?: string[] | null }) =>
    request<TagOptimizationResult>("/api/tags/optimize", { method: "POST", body: JSON.stringify(body) }),
  approveAllTagOptimizations: (body: TagOptimizationApproveAllPayload) =>
    request<TagOptimizationApproveAllResult>("/api/tags/optimize/approve-all", { method: "POST", body: JSON.stringify(body) }),
  savedSearches: () => request<SavedSearch[]>("/api/saved-searches"),
  createSavedSearch: (body: { name: string; query?: string | null; filters?: DocumentFilters }) =>
    request<SavedSearch>("/api/saved-searches", { method: "POST", body: JSON.stringify(body) }),
  updateSavedSearch: (id: string, body: Partial<SavedSearch>) =>
    request<SavedSearch>(`/api/saved-searches/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSavedSearch: (id: string) => request<{ status: string }>(`/api/saved-searches/${id}`, { method: "DELETE" }),
  projects: () => request<Project[]>("/api/projects"),
  createProject: (name: string, description?: string) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name, description }) }),
  project: (id: string) => request<ProjectDetail>(`/api/projects/${id}`),
  addProjectItems: (projectId: string, documentIds: string[], defaults: Record<string, unknown> = {}) =>
    request<ProjectDetail>(`/api/projects/${projectId}/items`, {
      method: "POST",
      body: JSON.stringify({ document_ids: documentIds, ...defaults }),
    }),
  updateProjectItem: (projectId: string, itemId: string, body: Partial<ProjectItem>) =>
    request<ProjectItem>(`/api/projects/${projectId}/items/${itemId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProjectItem: (projectId: string, itemId: string) =>
    request<{ status: string }>(`/api/projects/${projectId}/items/${itemId}`, { method: "DELETE" }),
  documents: (query: string, filters: DocumentFilters = {}) => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    const suffix = params.toString();
    return request<DocumentSummary[]>(`/api/documents${suffix ? `?${suffix}` : ""}`);
  },
  document: (id: string) => request<DocumentDetail>(`/api/documents/${id}`),
  documentComposition: (id: string) => request<DocumentComposition>(`/api/documents/${id}/composition`),
  cleanupDocumentTitles: () => request<{ updated: number }>("/api/documents/title-cleanup", { method: "POST" }),
  updateDocument: (id: string, body: DocumentUpdatePayload) =>
    request<DocumentDetail>(`/api/documents/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  updateDocumentPageText: (documentId: string, pageId: string, body: DocumentPageUpdatePayload) =>
    request<DocumentDetail>(`/api/documents/${documentId}/pages/${pageId}`, { method: "PATCH", body: JSON.stringify(body) }),
  scrubDocumentText: (documentId: string, body: DocumentTextScrubPayload) =>
    request<DocumentDetail>(`/api/documents/${documentId}/pages/scrub`, { method: "POST", body: JSON.stringify(body) }),
  restoreDocumentVersion: (documentId: string, versionId: string) =>
    request<DocumentDetail>(`/api/documents/${documentId}/versions/${versionId}/restore`, { method: "POST" }),
  refreshDocumentCitation: (id: string) =>
    request<ConcordanceRun>(`/api/documents/${id}/citation-refresh`, { method: "POST" }),
  createAccessorySummary: (documentId: string, body: AccessorySummaryPayload) =>
    request<AccessorySummary>(`/api/documents/${documentId}/accessory-summaries`, { method: "POST", body: JSON.stringify(body) }),
  updateAccessorySummary: (id: string, body: Partial<AccessorySummaryPayload>) =>
    request<AccessorySummary>(`/api/accessory-summaries/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  documentRecommendations: (id: string, hideExisting = false) =>
    request<DocumentRecommendation[]>(`/api/documents/${id}/recommendations${hideExisting ? "?hide_existing=true" : ""}`),
  refreshDocumentRecommendations: (id: string) =>
    request<DocumentRecommendationRefresh>(`/api/documents/${id}/recommendations/refresh`, { method: "POST" }),
  downloadRecommendations: (
    id: string,
    body: { recommendation_ids?: string[]; mode?: "selected" | "new"; skip_existing?: boolean },
  ) =>
    request<DocumentRecommendationDownload>(`/api/documents/${id}/recommendations/download`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  doiStashes: () => request<DoiStash[]>("/api/doi-stashes"),
  createDoiStash: (body: DoiStashPayload) =>
    request<DoiStash>("/api/doi-stashes", { method: "POST", body: JSON.stringify(body) }),
  deleteDoiStash: (id: string) => request<{ status: string }>(`/api/doi-stashes/${id}`, { method: "DELETE" }),
  importDoiStash: (id: string) => request<DoiStashImportResult>(`/api/doi-stashes/${id}/import`, { method: "POST" }),
  uploadDoiStashPdf: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DoiStash>(`/api/doi-stashes/${id}/upload`, { method: "POST", body: form });
  },
  annotations: (documentId: string) => request<Annotation[]>(`/api/documents/${documentId}/annotations`),
  createAnnotation: (documentId: string, body: AnnotationPayload) =>
    request<Annotation>(`/api/documents/${documentId}/annotations`, { method: "POST", body: JSON.stringify(body) }),
  updateAnnotation: (id: string, body: AnnotationPayload) =>
    request<Annotation>(`/api/annotations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteAnnotation: (id: string) => request<{ status: string }>(`/api/annotations/${id}`, { method: "DELETE" }),
  bulkUpdateDocuments: (documentIds: string[], updates: Record<string, unknown>) =>
    request<{ updated: number }>("/api/documents/bulk", {
      method: "POST",
      body: JSON.stringify({ document_ids: documentIds, updates }),
    }),
  notes: (filters: { document_id?: string; domain_id?: string; project_id?: string } = {}) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    const suffix = params.toString();
    return request<Note[]>(`/api/notes${suffix ? `?${suffix}` : ""}`);
  },
  createNote: (body: NotePayload) => request<Note>("/api/notes", { method: "POST", body: JSON.stringify(body) }),
  updateNote: (id: string, body: Partial<NotePayload>) =>
    request<Note>(`/api/notes/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteNote: (id: string) => request<{ status: string }>(`/api/notes/${id}`, { method: "DELETE" }),
  jobs: () => request<ImportJob[]>("/api/imports/jobs"),
  processStagedImportJobs: () => request<ImportQueueActionResult>("/api/imports/jobs/process-staged", { method: "POST" }),
  rescueImportJob: (id: string) => request<ImportJob>(`/api/imports/jobs/${id}/rescue`, { method: "POST" }),
  cancelImportJob: (id: string) => request<ImportJob>(`/api/imports/jobs/${id}/cancel`, { method: "POST" }),
  retryFailedImportJobs: () => request<ImportQueueActionResult>("/api/imports/jobs/retry-failed", { method: "POST" }),
  clearStagedImportJobs: () => request<ImportQueueActionResult>("/api/imports/jobs/clear-staged", { method: "POST" }),
  clearImportQueue: () => request<ImportQueueActionResult>("/api/imports/jobs/clear", { method: "POST" }),
  clearFailedImportJobs: () => request<ImportQueueActionResult>("/api/imports/jobs/clear-failed", { method: "POST" }),
  checkImportDuplicates: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<ImportDuplicateCheck>("/api/imports/duplicates", { method: "POST", body: form });
  },
  concordanceCapabilities: () => request<ConcordanceCapability[]>("/api/concordance/capabilities"),
  concordanceRuns: () => request<ConcordanceRun[]>("/api/concordance/runs"),
  concordanceJobs: () => request<ConcordanceJob[]>("/api/concordance/jobs"),
  estimateConcordanceRun: (body: {
    scope_type?: string;
    scope_data?: Record<string, unknown>;
    capability_keys?: string[];
    force?: boolean;
  }) => request<ConcordanceRunEstimate>("/api/concordance/runs/estimate", { method: "POST", body: JSON.stringify(body) }),
  createConcordanceRun: (body: {
    label?: string;
    scope_type?: string;
    scope_data?: Record<string, unknown>;
    capability_keys?: string[];
    force?: boolean;
  }) => request<ConcordanceRun>("/api/concordance/runs", { method: "POST", body: JSON.stringify(body) }),
  reviewQueue: () => request<CitationCandidate[]>("/api/review-queue"),
  updateCitationCandidate: (id: string, body: { status?: string; apply_to_document?: boolean }) =>
    request<CitationCandidate>(`/api/review-queue/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  bibliography: (projectId: string, usedOnly = false) =>
    request<Bibliography>(`/api/projects/${projectId}/bibliography${usedOnly ? "?used_only=true" : ""}`),
  uploadBatch: (files: File[], defaults: Record<string, unknown> & { duplicate_strategy?: DuplicateImportStrategy }) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    form.append("label", String(defaults.label || ""));
    form.append("domain_ids", JSON.stringify(defaults.domain_ids || []));
    form.append("tag_ids", JSON.stringify(defaults.tag_ids || []));
    form.append("project_ids", JSON.stringify(defaults.project_ids || []));
    form.append("priority", String(defaults.priority || "normal"));
    form.append("read_status", String(defaults.read_status || "unread"));
    form.append("attributes", JSON.stringify(defaults.attributes || {}));
    form.append("duplicate_strategy", defaults.duplicate_strategy || "skip");
    form.append("processing_preset_id", String(defaults.processing_preset_id || ""));
    return request<{ id: string }>("/api/imports/batches", { method: "POST", body: form });
  },
};

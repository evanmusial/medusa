import type {
  AccessorySummary,
  AccessorySummaryPayload,
  AccountUpdatePayload,
  Annotation,
  AnnotationPayload,
  AppPreferences,
  BackupArtifact,
  BackupEstimate,
  BackupRun,
  Bibliography,
  CacheHydrateResult,
  CacheRefreshResult,
  CacheStatus,
  CitationCandidate,
  CloudRunWorkerScalePlan,
  CloudRunWorkerStatus,
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
  DocumentLockPayload,
  DocumentListResponse,
  DocumentListSort,
  DocumentPageUpdatePayload,
  DocumentRecommendation,
  DocumentRecommendationDownload,
  DocumentRecommendationRefresh,
  DuplicateDismissResult,
  DuplicateResolveResult,
  DuplicateScan,
  DocumentSummary,
  DocumentTextScrubPayload,
  DocumentTrashResult,
  DocumentUpdatePayload,
  DoiStash,
  DoiStashImportResult,
  DoiStashPayload,
  Domain,
  DomainDeleteResult,
  DomainReorderItem,
  DomainUpdatePayload,
  DuplicateImportStrategy,
  FigurePatchPayload,
  GcsBucketLifecycle,
  HAProxyStatsStatus,
  IngestionHistory,
  ImportDuplicateCheck,
  ImportJob,
  ImportQueueActionResult,
  LibraryFunStats,
  Note,
  NotePayload,
  ModelPricingStatus,
  OpenAIUsage,
  OpenAIUsagePeriod,
  PortfolioAssessmentPayload,
  PortfolioAssessmentRun,
  PortfolioItem,
  PortfolioItemPatchPayload,
  PortfolioItemPayload,
  PortfolioSuggestionRefresh,
  PublicationListRow,
  Project,
  ProjectDetail,
  ProjectItem,
  RecommendationFamily,
  RecommendationView,
  ReconEstimate,
  ReconInquiry,
  ReconInquiryPatch,
  ReconInquiryPayload,
  ReconRun,
  ReconRunPayload,
  ReleaseStatus,
  RuntimeLocation,
  SavedSearch,
  SlipstreamEnrollment,
  SlipstreamStatus,
  Tag,
  TagOptimizationApproveAllPayload,
  TagOptimizationApproveAllResult,
  TagOptimizationResult,
  TagOperationResult,
  TwoFactorDisablePayload,
  TwoFactorEnablePayload,
  TwoFactorEnableResult,
  TwoFactorSetup,
  TwoFactorSetupPayload,
  User,
  VisualScanCandidate,
  VisualScanReview,
  WorkControlResult,
} from "../types";

export class ApiError extends Error {
  path: string;
  status: number;

  constructor(message: string, status: number, path: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
  }
}

export type BackendAvailabilityEvent =
  | {
      type: "unavailable";
      reason: "gateway" | "network" | "restart";
      message: string;
      observedAt: number;
      path?: string;
      status?: number;
    }
  | {
      type: "available";
      observedAt: number;
      path?: string;
    };

const DEFAULT_API_PREFIX = "/api";
const BACKEND_AVAILABILITY_EVENT = "medusa:backend-availability";
const BACKEND_AVAILABILITY_CHANNEL = "medusa-backend-availability";
const BACKEND_AVAILABILITY_STORAGE_KEY = "medusa-backend-availability";
let backendAvailabilityChannel: BroadcastChannel | null | undefined;
let lastBackendAvailabilityType: BackendAvailabilityEvent["type"] = "available";

function normalizeApiPrefix(value: string | undefined) {
  const trimmed = (value || DEFAULT_API_PREFIX).trim();
  if (!trimmed || trimmed === "/") return DEFAULT_API_PREFIX;
  return `/${trimmed.replace(/^\/+|\/+$/g, "")}`;
}

const apiPrefix = normalizeApiPrefix(import.meta.env.VITE_MEDUSA_API_PREFIX);

export function apiPath(path: string) {
  if (!path.startsWith(DEFAULT_API_PREFIX)) return path;
  return `${apiPrefix}${path.slice(DEFAULT_API_PREFIX.length)}`;
}

function getBackendAvailabilityChannel() {
  if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") return null;
  if (backendAvailabilityChannel !== undefined) return backendAvailabilityChannel;
  backendAvailabilityChannel = new BroadcastChannel(BACKEND_AVAILABILITY_CHANNEL);
  return backendAvailabilityChannel;
}

function parseBackendAvailabilityEvent(value: unknown): BackendAvailabilityEvent | null {
  if (!value || typeof value !== "object") return null;
  const event = value as Partial<BackendAvailabilityEvent>;
  if (event.type === "available" && typeof event.observedAt === "number") return event as BackendAvailabilityEvent;
  if (
    event.type === "unavailable" &&
    typeof event.observedAt === "number" &&
    typeof event.message === "string" &&
    (event.reason === "gateway" || event.reason === "network" || event.reason === "restart")
  ) {
    return event as BackendAvailabilityEvent;
  }
  return null;
}

function emitBackendAvailabilityEvent(event: BackendAvailabilityEvent) {
  if (typeof window === "undefined") return;
  const shouldBroadcast = event.type === "unavailable" || lastBackendAvailabilityType === "unavailable";
  lastBackendAvailabilityType = event.type;
  window.dispatchEvent(new CustomEvent<BackendAvailabilityEvent>(BACKEND_AVAILABILITY_EVENT, { detail: event }));
  if (!shouldBroadcast) return;
  getBackendAvailabilityChannel()?.postMessage(event);
  try {
    window.localStorage.setItem(BACKEND_AVAILABILITY_STORAGE_KEY, JSON.stringify(event));
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}

export function subscribeBackendAvailability(listener: (event: BackendAvailabilityEvent) => void) {
  if (typeof window === "undefined") return () => undefined;
  const notify = (event: BackendAvailabilityEvent) => {
    lastBackendAvailabilityType = event.type;
    listener(event);
  };
  const handleCustomEvent = (event: Event) => {
    const parsed = parseBackendAvailabilityEvent((event as CustomEvent<BackendAvailabilityEvent>).detail);
    if (parsed) notify(parsed);
  };
  const handleMessage = (event: MessageEvent) => {
    const parsed = parseBackendAvailabilityEvent(event.data);
    if (parsed) notify(parsed);
  };
  const handleStorage = (event: StorageEvent) => {
    if (event.key !== BACKEND_AVAILABILITY_STORAGE_KEY || !event.newValue) return;
    try {
      const parsed = parseBackendAvailabilityEvent(JSON.parse(event.newValue));
      if (parsed) notify(parsed);
    } catch {
      // Ignore malformed cross-tab payloads.
    }
  };
  const channel = getBackendAvailabilityChannel();
  window.addEventListener(BACKEND_AVAILABILITY_EVENT, handleCustomEvent);
  window.addEventListener("storage", handleStorage);
  channel?.addEventListener("message", handleMessage);
  return () => {
    window.removeEventListener(BACKEND_AVAILABILITY_EVENT, handleCustomEvent);
    window.removeEventListener("storage", handleStorage);
    channel?.removeEventListener("message", handleMessage);
  };
}

function isBackendUnavailableStatus(status: number) {
  return status === 502 || status === 503 || status === 504;
}

export function isLikelyBackendUnavailableError(error: unknown) {
  if (error instanceof ApiError) return error.status === 0 || isBackendUnavailableStatus(error.status);
  const message = error instanceof Error ? error.message.toLowerCase() : String(error || "").toLowerCase();
  return message.includes("failed to fetch") || message.includes("load failed") || message.includes("network");
}

function reportBackendUnavailable(event: Omit<Extract<BackendAvailabilityEvent, { type: "unavailable" }>, "type" | "observedAt">) {
  emitBackendAvailabilityEvent({ ...event, type: "unavailable", observedAt: Date.now() });
}

function reportBackendAvailable(path?: string) {
  emitBackendAvailabilityEvent({ type: "available", observedAt: Date.now(), path });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiPath(path), {
      ...init,
      credentials: "include",
      headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    reportBackendUnavailable({
      message: "Medusa backend is not reachable.",
      path,
      reason: "network",
      status: 0,
    });
    throw new ApiError("Medusa backend is not reachable.", 0, path);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    const detail = typeof body.detail === "string" ? body.detail : response.statusText;
    if (isBackendUnavailableStatus(response.status)) {
      reportBackendUnavailable({
        message: detail || response.statusText || `HTTP ${response.status}`,
        path,
        reason: "gateway",
        status: response.status,
      });
    }
    throw new ApiError(detail || response.statusText || `HTTP ${response.status}`, response.status, path);
  }
  reportBackendAvailable(path);
  return response.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string, otpCode?: string) =>
    request<User>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password, otp_code: otpCode || null }) }),
  logout: () => request<{ status: string }>("/api/auth/logout", { method: "POST" }),
  me: () => request<User>("/api/me"),
  heartbeat: () => request<{ status: string; last_seen_at?: string | null }>("/api/activity/heartbeat", { method: "POST" }),
  updateMe: (body: AccountUpdatePayload) =>
    request<User>("/api/me", { method: "PATCH", body: JSON.stringify(body) }),
  startTwoFactorSetup: (body: TwoFactorSetupPayload) =>
    request<TwoFactorSetup>("/api/me/two-factor/setup", { method: "POST", body: JSON.stringify(body) }),
  enableTwoFactor: (body: TwoFactorEnablePayload) =>
    request<TwoFactorEnableResult>("/api/me/two-factor/enable", { method: "POST", body: JSON.stringify(body) }),
  disableTwoFactor: (body: TwoFactorDisablePayload) =>
    request<User>("/api/me/two-factor/disable", { method: "POST", body: JSON.stringify(body) }),
  runtimeLocation: (browserHost: string) =>
    request<RuntimeLocation>(`/api/runtime-location?browser_host=${encodeURIComponent(browserHost)}`),
  releaseStatus: (clientVersion: string) =>
    request<ReleaseStatus>(`/api/release/status?client_version=${encodeURIComponent(clientVersion)}`),
  requestReleaseUpgrade: (clientVersion: string) =>
    request<ReleaseStatus>(`/api/release/upgrade?client_version=${encodeURIComponent(clientVersion)}`, { method: "POST" }),
  requestReleaseCheck: (clientVersion: string) =>
    request<ReleaseStatus>(`/api/release/check?client_version=${encodeURIComponent(clientVersion)}`, { method: "POST" }),
  requestMaintenanceRun: (clientVersion: string) =>
    request<ReleaseStatus>(`/api/release/maintenance?client_version=${encodeURIComponent(clientVersion)}`, { method: "POST" }),
  health: () => request<{ status: string; app: string }>(`/api/health?release_check=${Date.now()}`),
  cacheStatus: () => request<CacheStatus>("/api/cache/status"),
  hydrateCache: () => request<CacheHydrateResult>("/api/cache/hydrate", { method: "POST" }),
  pauseCacheHydration: () => request<WorkControlResult>("/api/cache/hydrate/pause", { method: "POST" }),
  resumeCacheHydration: () => request<WorkControlResult>("/api/cache/hydrate/resume", { method: "POST" }),
  stopCacheHydration: () => request<WorkControlResult>("/api/cache/hydrate/stop", { method: "POST" }),
  refreshCache: () => request<CacheRefreshResult>("/api/cache/refresh", { method: "POST" }),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  preferences: () => request<AppPreferences>("/api/preferences"),
  gcsBucketLifecycle: () => request<GcsBucketLifecycle>("/api/preferences/gcs-lifecycle"),
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
  backfillDocumentHashes: () =>
    request<DatabaseMaintenanceResult>("/api/utilities/document-hashes/backfill", { method: "POST" }),
  containerFootprintStatus: () => request<ContainerFootprintStatus>("/api/utilities/container/status"),
  restartContainer: async () => {
    const path = "/api/utilities/container/restart";
    const result = await request<ContainerRestartResult>(path, { method: "POST" });
    reportBackendUnavailable({
      message: result.message || "Backend restart requested. Waiting for Medusa to return.",
      path,
      reason: "restart",
    });
    return result;
  },
  haproxyStatus: () => request<HAProxyStatsStatus>("/api/utilities/haproxy/status"),
  libraryFunStats: () => request<LibraryFunStats>("/api/status/library-fun"),
  slipstreamStatus: () => request<SlipstreamStatus>("/api/slipstream/status"),
  cloudRunWorkerStatus: () => request<CloudRunWorkerStatus>("/api/cloud-run/workers/status"),
  cloudRunWorkerScalePlan: (body: { desired_instances: number; force?: boolean }) =>
    request<CloudRunWorkerScalePlan>("/api/cloud-run/workers/scale-plan", { method: "POST", body: JSON.stringify(body) }),
  createSlipstreamEnrollment: (body: { label?: string | null; ttl_minutes?: number; capabilities?: string[]; max_capacity?: number }) =>
    request<SlipstreamEnrollment>("/api/slipstream/enrollments", { method: "POST", body: JSON.stringify(body) }),
  disableSlipstreamClient: (id: string) =>
    request<SlipstreamStatus>(`/api/slipstream/clients/${id}/disable`, { method: "POST" }).then(() => api.slipstreamStatus()),
  revokeSlipstreamClient: (id: string) =>
    request<SlipstreamStatus>(`/api/slipstream/clients/${id}/revoke`, { method: "POST" }).then(() => api.slipstreamStatus()),
  cancelSlipstreamLease: (id: string) =>
    request<SlipstreamStatus>(`/api/slipstream/leases/${id}/cancel`, { method: "POST" }).then(() => api.slipstreamStatus()),
  ingestionHistory: () => request<IngestionHistory[]>("/api/utilities/ingestion-history"),
  backupArtifacts: () => request<BackupArtifact[]>("/api/backups/artifacts"),
  gcsBackups: () => request<BackupArtifact[]>("/api/backups/gcs"),
  startDatabaseBackup: () => request<BackupRun>("/api/backups/database", { method: "POST" }),
  startDatabaseRestore: (uri: string) =>
    request<BackupRun>("/api/restores/database", { method: "POST", body: JSON.stringify({ uri }) }),
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
        | "cloud_run_workers_enabled"
        | "cloud_run_worker_concurrency"
        | "cloud_run_worker_flavor"
        | "accent_color_day"
        | "accent_color_night"
        | "document_cache_size_mb"
        | "valkey_maxmemory"
        | "library_alternating_rows"
        | "library_page_size"
        | "library_density"
        | "detail_sticky_fields"
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
  createDomain: (name: string, parentId?: string | null, color?: string | null, description?: string | null, tagIds: string[] = []) =>
    request<Domain>("/api/domains", {
      method: "POST",
      body: JSON.stringify({ name, parent_id: parentId || null, color: color || null, description: description || null, tag_ids: tagIds }),
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
  reconInquiries: () => request<ReconInquiry[]>("/api/recon/inquiries"),
  createReconInquiry: (body: ReconInquiryPayload) =>
    request<ReconInquiry>("/api/recon/inquiries", { method: "POST", body: JSON.stringify(body) }),
  updateReconInquiry: (id: string, body: ReconInquiryPatch) =>
    request<ReconInquiry>(`/api/recon/inquiries/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  estimateReconRun: (id: string, body: ReconRunPayload = {}) =>
    request<ReconEstimate>(`/api/recon/inquiries/${id}/estimate`, { method: "POST", body: JSON.stringify(body) }),
  startReconRun: (id: string, body: ReconRunPayload = {}) =>
    request<ReconRun>(`/api/recon/inquiries/${id}/runs`, { method: "POST", body: JSON.stringify(body) }),
  reconRun: (id: string) => request<ReconRun>(`/api/recon/runs/${id}`),
  cancelReconRun: (id: string) => request<ReconRun>(`/api/recon/runs/${id}/cancel`, { method: "POST" }),
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
  documents: (
    query: string,
    filters: DocumentFilters = {},
    options: { includeDuplicateSummary?: boolean; includeProjects?: boolean } = {},
  ) => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    if (options.includeDuplicateSummary === false) params.set("include_duplicate_summary", "false");
    if (options.includeProjects === false) params.set("include_projects", "false");
    const suffix = params.toString();
    return request<DocumentSummary[]>(`/api/documents${suffix ? `?${suffix}` : ""}`);
  },
  documentList: (
    query: string,
    filters: DocumentFilters = {},
    options: { all?: boolean; focusDocumentId?: string | null; offset?: number; limit?: number; sort?: DocumentListSort } = {},
  ) => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    if (options.focusDocumentId) params.set("focus_document_id", options.focusDocumentId);
    if (options.sort) params.set("sort", options.sort);
    if (options.all) {
      params.set("all", "true");
    } else {
      params.set("offset", String(Math.max(0, options.offset ?? 0)));
      params.set("limit", String(Math.max(1, options.limit ?? 50)));
    }
    return request<DocumentListResponse>(`/api/documents/list?${params.toString()}`);
  },
  document: (id: string) => request<DocumentDetail>(`/api/documents/${id}`),
  publications: (query = "", limit = 200) => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    params.set("limit", String(limit));
    return request<PublicationListRow[]>(`/api/publications?${params.toString()}`);
  },
  scanDocumentDuplicates: () => request<DuplicateScan>("/api/documents/duplicates/scan"),
  resolveDocumentDuplicate: (keepDocumentId: string, duplicateDocumentId: string) =>
    request<DuplicateResolveResult>("/api/documents/duplicates/resolve", {
      method: "POST",
      body: JSON.stringify({ keep_document_id: keepDocumentId, duplicate_document_id: duplicateDocumentId }),
    }),
  dismissDocumentDuplicate: (leftDocumentId: string, rightDocumentId: string) =>
    request<DuplicateDismissResult>("/api/documents/duplicates/dismiss", {
      method: "POST",
      body: JSON.stringify({ left_document_id: leftDocumentId, right_document_id: rightDocumentId }),
    }),
  documentComposition: (id: string) => request<DocumentComposition>(`/api/documents/${id}/composition`),
  cleanupDocumentTitles: () => request<{ updated: number }>("/api/documents/title-cleanup", { method: "POST" }),
  updateDocument: (id: string, body: DocumentUpdatePayload) =>
    request<DocumentDetail>(`/api/documents/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  updateDocumentLock: (id: string, body: DocumentLockPayload) =>
    request<DocumentDetail>(`/api/documents/${id}/lock`, { method: "POST", body: JSON.stringify(body) }),
  replaceDocument: (id: string, file: File, options: { processingPresetId?: string | null } = {}) => {
    const form = new FormData();
    form.append("file", file);
    if (options.processingPresetId) form.append("processing_preset_id", options.processingPresetId);
    return request<ImportJob>(`/api/documents/${id}/replace`, { method: "POST", body: form });
  },
  updateDocumentPageText: (documentId: string, pageId: string, body: DocumentPageUpdatePayload) =>
    request<DocumentDetail>(`/api/documents/${documentId}/pages/${pageId}`, { method: "PATCH", body: JSON.stringify(body) }),
  scrubDocumentText: (documentId: string, body: DocumentTextScrubPayload) =>
    request<DocumentDetail>(`/api/documents/${documentId}/pages/scrub`, { method: "POST", body: JSON.stringify(body) }),
  scanDocumentVisualPage: (documentId: string, pageNumber: number) =>
    request<VisualScanReview>(`/api/documents/${documentId}/figures/page-scan`, {
      method: "POST",
      body: JSON.stringify({ page_number: pageNumber }),
    }),
  applyDocumentVisualPageScan: (documentId: string, pageNumber: number, candidates: VisualScanCandidate[]) =>
    request<DocumentDetail>(`/api/documents/${documentId}/figures/page-scan/apply`, {
      method: "POST",
      body: JSON.stringify({ page_number: pageNumber, candidates }),
    }),
  updateFigure: (figureId: string, body: FigurePatchPayload) =>
    request<DocumentDetail>(`/api/figures/${figureId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteFigure: (figureId: string) => request<DocumentDetail>(`/api/figures/${figureId}`, { method: "DELETE" }),
  restoreDocumentVersion: (documentId: string, versionId: string) =>
    request<DocumentDetail>(`/api/documents/${documentId}/versions/${versionId}/restore`, { method: "POST" }),
  refreshDocumentCitation: (id: string, options: { confirmVerified?: boolean } = {}) =>
    request<ConcordanceRun>(`/api/documents/${id}/citation-refresh${options.confirmVerified ? "?confirm_verified=true" : ""}`, {
      method: "POST",
    }),
  verifyDocumentField: (id: string, field: "doi" | "apa_citation" | "apa_in_text_citation" | "bibliography") =>
    request<DocumentDetail>(`/api/documents/${id}/field-verifications/${field}`, { method: "POST" }),
  verifyDocumentBibliography: (id: string) =>
    request<DocumentDetail>(`/api/documents/${id}/bibliography-verification`, { method: "POST" }),
  verifyDocumentPublication: (id: string) =>
    request<DocumentDetail>(`/api/documents/${id}/publication-verification`, { method: "POST" }),
  validateDocumentSummary: (id: string) =>
    request<DocumentDetail>(`/api/documents/${id}/summary-validation`, { method: "POST" }),
  refreshDocumentSummary: (id: string, options: { confirmValidated?: boolean } = {}) =>
    request<ConcordanceRun>(`/api/documents/${id}/summary-refresh${options.confirmValidated ? "?confirm_validated=true" : ""}`, {
      method: "POST",
    }),
  refreshDocumentBibliography: (id: string, options: { confirmVerified?: boolean } = {}) =>
    request<ConcordanceRun>(
      `/api/documents/${id}/bibliography-refresh${options.confirmVerified ? "?confirm_verified=true" : ""}`,
      { method: "POST" },
    ),
  refreshDocumentPublication: (id: string, options: { confirmVerified?: boolean } = {}) =>
    request<ConcordanceRun>(
      `/api/documents/${id}/publication-refresh${options.confirmVerified ? "?confirm_verified=true" : ""}`,
      { method: "POST" },
    ),
  createAccessorySummary: (documentId: string, body: AccessorySummaryPayload) =>
    request<AccessorySummary>(`/api/documents/${documentId}/inquests`, { method: "POST", body: JSON.stringify(body) }),
  updateAccessorySummary: (id: string, body: Partial<AccessorySummaryPayload>) =>
    request<AccessorySummary>(`/api/accessory-summaries/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  documentRecommendations: (
    id: string,
    options: { hideExisting?: boolean; view?: RecommendationView; family?: RecommendationFamily } = {},
  ) => {
    const params = new URLSearchParams();
    if (options.hideExisting) params.set("hide_existing", "true");
    if (options.view) params.set("view", options.view);
    if (options.family) params.set("family", options.family);
    const suffix = params.toString();
    return request<DocumentRecommendation[]>(`/api/documents/${id}/recommendations${suffix ? `?${suffix}` : ""}`);
  },
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
  portfolioItems: () => request<PortfolioItem[]>("/api/portfolio"),
  createPortfolioItem: (body: PortfolioItemPayload) =>
    request<PortfolioItem>("/api/portfolio", { method: "POST", body: JSON.stringify(body) }),
  updatePortfolioItem: (id: string, body: PortfolioItemPatchPayload) =>
    request<PortfolioItem>(`/api/portfolio/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  uploadPortfolioVersion: (
    id: string,
    file: File,
    options: { label?: string; uploadNote?: string; parentVersionId?: string | null } = {},
  ) => {
    const form = new FormData();
    form.append("file", file);
    if (options.label) form.append("label", options.label);
    if (options.uploadNote) form.append("upload_note", options.uploadNote);
    if (options.parentVersionId) form.append("parent_version_id", options.parentVersionId);
    return request<PortfolioItem>(`/api/portfolio/${id}/versions`, { method: "POST", body: form });
  },
  uploadPortfolioMaterial: (
    id: string,
    file: File,
    options: { role?: string; label?: string; notes?: string; versionId?: string | null; requiredForAssessment?: boolean } = {},
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("role", options.role || "reference");
    if (options.label) form.append("label", options.label);
    if (options.notes) form.append("notes", options.notes);
    if (options.versionId) form.append("version_id", options.versionId);
    form.append("required_for_assessment", String(Boolean(options.requiredForAssessment)));
    return request<PortfolioItem>(`/api/portfolio/${id}/materials`, { method: "POST", body: form });
  },
  refreshPortfolioSuggestions: (id: string) =>
    request<PortfolioSuggestionRefresh>(`/api/portfolio/${id}/suggestions/refresh`, { method: "POST" }),
  createPortfolioAssessment: (id: string, body: PortfolioAssessmentPayload = {}) =>
    request<PortfolioAssessmentRun>(`/api/portfolio/${id}/assessments`, { method: "POST", body: JSON.stringify(body) }),
  downloadPortfolioBundle: async (id: string) => {
    const path = `/api/portfolio/${id}/bundle`;
    let response: Response;
    try {
      response = await fetch(apiPath(path), { method: "POST", credentials: "include" });
    } catch {
      reportBackendUnavailable({
        message: "Medusa backend is not reachable.",
        path,
        reason: "network",
        status: 0,
      });
      throw new ApiError("Medusa backend is not reachable.", 0, path);
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: response.statusText }));
      const detail = typeof body.detail === "string" ? body.detail : response.statusText;
      if (isBackendUnavailableStatus(response.status)) {
        reportBackendUnavailable({
          message: detail || response.statusText || `HTTP ${response.status}`,
          path,
          reason: "gateway",
          status: response.status,
        });
      }
      throw new ApiError(detail || response.statusText || `HTTP ${response.status}`, response.status, path);
    }
    reportBackendAvailable(path);
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match?.[1] ? decodeURIComponent(match[1]) : `portfolio-${id}.zip`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return { filename, sha256: response.headers.get("x-medusa-bundle-sha256") || undefined };
  },
  annotations: (documentId: string) => request<Annotation[]>(`/api/documents/${documentId}/annotations`),
  createAnnotation: (documentId: string, body: AnnotationPayload) =>
    request<Annotation>(`/api/documents/${documentId}/annotations`, { method: "POST", body: JSON.stringify(body) }),
  updateAnnotation: (id: string, body: AnnotationPayload) =>
    request<Annotation>(`/api/annotations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteAnnotation: (id: string) => request<{ status: string }>(`/api/annotations/${id}`, { method: "DELETE" }),
  trashDocuments: (documentIds: string[]) =>
    request<DocumentTrashResult>("/api/documents/trash", { method: "POST", body: JSON.stringify({ document_ids: documentIds }) }),
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
  pauseImportQueue: () => request<WorkControlResult>("/api/imports/jobs/pause", { method: "POST" }),
  resumeImportQueue: () => request<WorkControlResult>("/api/imports/jobs/resume", { method: "POST" }),
  stopImportQueue: () => request<WorkControlResult>("/api/imports/jobs/stop", { method: "POST" }),
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
  pauseConcordanceRuns: () => request<WorkControlResult>("/api/concordance/runs/pause", { method: "POST" }),
  resumeConcordanceRuns: () => request<WorkControlResult>("/api/concordance/runs/resume", { method: "POST" }),
  stopConcordanceRuns: () => request<WorkControlResult>("/api/concordance/runs/stop", { method: "POST" }),
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

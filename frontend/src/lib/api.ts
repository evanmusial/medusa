import type {
  Annotation,
  AnnotationPayload,
  AppPreferences,
  Bibliography,
  CitationCandidate,
  ConcordanceCapability,
  ConcordanceJob,
  ConcordanceRun,
  Dashboard,
  DocumentDetail,
  DocumentFilters,
  DocumentRecommendation,
  DocumentRecommendationDownload,
  DocumentRecommendationRefresh,
  DocumentSummary,
  DocumentUpdatePayload,
  Domain,
  DuplicateImportStrategy,
  ImportDuplicateCheck,
  ImportJob,
  Note,
  NotePayload,
  OpenAIUsage,
  OpenAIUsagePeriod,
  Project,
  ProjectDetail,
  ProjectItem,
  SavedSearch,
  Tag,
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
  dashboard: () => request<Dashboard>("/api/dashboard"),
  preferences: () => request<AppPreferences>("/api/preferences"),
  openaiUsage: (period: OpenAIUsagePeriod = "all_time") => request<OpenAIUsage>(`/api/openai/usage?period=${period}`),
  updatePreferences: (
    body: Partial<
      Pick<
        AppPreferences,
        | "import_worker_concurrency"
        | "accent_color_day"
        | "accent_color_night"
        | "document_cache_size_mb"
        | "library_alternating_rows"
        | "analysis_models"
      >
    >,
  ) =>
    request<AppPreferences>("/api/preferences", { method: "PATCH", body: JSON.stringify(body) }),
  domains: () => request<Domain[]>("/api/domains"),
  createDomain: (name: string, parentId?: string | null) =>
    request<Domain>("/api/domains", { method: "POST", body: JSON.stringify({ name, parent_id: parentId || null }) }),
  tags: () => request<Tag[]>("/api/tags"),
  createTag: (name: string, kind = "keyword") =>
    request<Tag>("/api/tags", { method: "POST", body: JSON.stringify({ name, kind }) }),
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
  updateDocument: (id: string, body: DocumentUpdatePayload) =>
    request<DocumentDetail>(`/api/documents/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  refreshDocumentCitation: (id: string) =>
    request<ConcordanceRun>(`/api/documents/${id}/citation-refresh`, { method: "POST" }),
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
  rescueImportJob: (id: string) => request<ImportJob>(`/api/imports/jobs/${id}/rescue`, { method: "POST" }),
  checkImportDuplicates: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<ImportDuplicateCheck>("/api/imports/duplicates", { method: "POST", body: form });
  },
  concordanceCapabilities: () => request<ConcordanceCapability[]>("/api/concordance/capabilities"),
  concordanceRuns: () => request<ConcordanceRun[]>("/api/concordance/runs"),
  concordanceJobs: () => request<ConcordanceJob[]>("/api/concordance/jobs"),
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
    return request<{ id: string }>("/api/imports/batches", { method: "POST", body: form });
  },
};

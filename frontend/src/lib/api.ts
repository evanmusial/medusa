import type {
  Bibliography,
  CitationCandidate,
  Dashboard,
  DocumentDetail,
  DocumentSummary,
  Domain,
  ImportJob,
  Project,
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
  domains: () => request<Domain[]>("/api/domains"),
  tags: () => request<Tag[]>("/api/tags"),
  projects: () => request<Project[]>("/api/projects"),
  createProject: (name: string, description?: string) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name, description }) }),
  documents: (query: string) => request<DocumentSummary[]>(`/api/documents${query ? `?q=${encodeURIComponent(query)}` : ""}`),
  document: (id: string) => request<DocumentDetail>(`/api/documents/${id}`),
  updateDocument: (id: string, body: Partial<DocumentDetail>) =>
    request<DocumentDetail>(`/api/documents/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  jobs: () => request<ImportJob[]>("/api/imports/jobs"),
  reviewQueue: () => request<CitationCandidate[]>("/api/review-queue"),
  bibliography: (projectId: string) => request<Bibliography>(`/api/projects/${projectId}/bibliography`),
  uploadBatch: (files: File[], defaults: Record<string, unknown>) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    form.append("label", String(defaults.label || ""));
    form.append("domain_ids", JSON.stringify(defaults.domain_ids || []));
    form.append("tag_ids", JSON.stringify(defaults.tag_ids || []));
    form.append("project_ids", JSON.stringify(defaults.project_ids || []));
    form.append("priority", String(defaults.priority || "normal"));
    form.append("read_status", String(defaults.read_status || "unread"));
    form.append("attributes", JSON.stringify(defaults.attributes || {}));
    return request<{ id: string }>("/api/imports/batches", { method: "POST", body: form });
  },
};

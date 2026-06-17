import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, DragEvent, PointerEvent as ReactPointerEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  BookOpen,
  CheckCircle2,
  Clipboard,
  Cloud,
  FileSearch,
  FolderTree,
  Gauge,
  Library,
  ListChecks,
  LogOut,
  Moon,
  Plus,
  Search,
  Settings,
  Sparkles,
  Sun,
  Tags,
  UploadCloud,
} from "lucide-react";
import { api } from "./lib/api";
import type { Bibliography, CitationCandidate, DocumentDetail, DocumentSummary, Domain, ImportJob, Project, Tag } from "./types";

type View = "library" | "domains" | "projects" | "review" | "notes" | "import" | "settings";

const navItems: Array<{ id: View; label: string; icon: typeof Library }> = [
  { id: "library", label: "Library", icon: Library },
  { id: "domains", label: "Domains", icon: FolderTree },
  { id: "projects", label: "Projects", icon: ListChecks },
  { id: "review", label: "Review Queue", icon: FileSearch },
  { id: "notes", label: "Notes", icon: BookOpen },
  { id: "import", label: "Import", icon: UploadCloud },
  { id: "settings", label: "Settings", icon: Settings },
];

function authorLine(document: DocumentSummary | DocumentDetail) {
  const authors = document.authors || [];
  if (!authors.length) return "Unknown author";
  return authors
    .slice(0, 3)
    .map((author) => [author.given, author.family].filter(Boolean).join(" "))
    .join(", ");
}

function StatusPill({ value, tone = "neutral" }: { value: string; tone?: "neutral" | "good" | "warn" | "blue" }) {
  return <span className={`pill ${tone}`}>{value.replaceAll("_", " ")}</span>;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function useStoredPaneSize(key: string, defaultValue: number, min: number, max: number) {
  const [value, setValue] = useState(() => {
    const stored = Number(localStorage.getItem(key));
    return Number.isFinite(stored) && stored > 0 ? clamp(stored, min, max) : defaultValue;
  });

  useEffect(() => {
    localStorage.setItem(key, String(value));
  }, [key, value]);

  return [value, setValue] as const;
}

function ResizeHandle({
  label,
  value,
  setValue,
  min,
  max,
  invert = false,
  className = "",
}: {
  label: string;
  value: number;
  setValue: (value: number) => void;
  min: number;
  max: number;
  invert?: boolean;
  className?: string;
}) {
  const startResize = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const startValue = value;
    document.body.classList.add("resizing-pane");

    const onPointerMove = (moveEvent: PointerEvent) => {
      const delta = moveEvent.clientX - startX;
      setValue(clamp(startValue + (invert ? -delta : delta), min, max));
    };
    const stopResize = () => {
      document.body.classList.remove("resizing-pane");
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
  };

  const nudge = (direction: -1 | 1) => {
    setValue(clamp(value + (invert ? -direction : direction) * 16, min, max));
  };

  return (
    <button
      aria-label={label}
      aria-orientation="vertical"
      aria-valuemax={max}
      aria-valuemin={min}
      aria-valuenow={Math.round(value)}
      className={`resize-handle ${className}`}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          nudge(-1);
        }
        if (event.key === "ArrowRight") {
          event.preventDefault();
          nudge(1);
        }
      }}
      onPointerDown={startResize}
      role="separator"
      type="button"
    >
      <span />
    </button>
  );
}

function Login() {
  const [email, setEmail] = useState("admin@medusa.local");
  const [password, setPassword] = useState("medusa");
  const queryClient = useQueryClient();
  const login = useMutation({
    mutationFn: () => api.login(email, password),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });

  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="brand-stack">
          <div className="brand-mark">M</div>
          <div>
            <h1>Medusa</h1>
            <p>Research Library</p>
          </div>
        </div>
        <form
          className="login-form"
          onSubmit={(event) => {
            event.preventDefault();
            login.mutate();
          }}
        >
          <label>
            Email
            <input value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          <button className="primary-button" type="submit" disabled={login.isPending}>
            <CheckCircle2 size={17} />
            Sign in
          </button>
          {login.error ? <p className="form-error">{login.error.message}</p> : null}
        </form>
      </section>
    </main>
  );
}

function Header({
  query,
  setQuery,
  theme,
  setTheme,
  onLogout,
}: {
  query: string;
  setQuery: (query: string) => void;
  theme: "day" | "night";
  setTheme: (theme: "day" | "night") => void;
  onLogout: () => void;
}) {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark compact">M</div>
        <div>
          <strong>Medusa</strong>
          <span>Research Library</span>
        </div>
      </div>
      <label className="global-search">
        <Search size={17} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search documents, notes, figures, citations..." />
      </label>
      <div className="topbar-actions">
        <button className="icon-button" title="Toggle theme" onClick={() => setTheme(theme === "day" ? "night" : "day")}>
          {theme === "day" ? <Moon size={18} /> : <Sun size={18} />}
        </button>
        <button className="icon-button" title="Sign out" onClick={onLogout}>
          <LogOut size={18} />
        </button>
      </div>
    </header>
  );
}

function Sidebar({ activeView, setActiveView, queuedJobs }: { activeView: View; setActiveView: (view: View) => void; queuedJobs: number }) {
  return (
    <aside className="sidebar">
      <nav>
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.id} className={activeView === item.id ? "active" : ""} onClick={() => setActiveView(item.id)}>
              <Icon size={18} />
              <span>{item.label}</span>
              {item.id === "import" && queuedJobs > 0 ? <small>{queuedJobs}</small> : null}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}

function DomainTree({ domains }: { domains: Domain[] }) {
  const roots = useMemo(() => domains.filter((domain) => !domain.parent_id), [domains]);
  const children = useMemo(
    () =>
      domains.reduce<Record<string, Domain[]>>((acc, domain) => {
        if (domain.parent_id) acc[domain.parent_id] = [...(acc[domain.parent_id] || []), domain];
        return acc;
      }, {}),
    [domains],
  );

  const render = (domain: Domain, depth = 0) => (
    <div key={domain.id} className="domain-row" style={{ paddingLeft: 10 + depth * 16 }}>
      <span className="domain-dot" style={{ background: domain.color || "var(--blue)" }} />
      <span>{domain.name}</span>
      <small>{domain.document_count}</small>
      {(children[domain.id] || []).map((child) => render(child, depth + 1))}
    </div>
  );

  return <div className="domain-tree">{roots.map((domain) => render(domain))}</div>;
}

function LibraryView({
  documents,
  document,
  selectedId,
  setSelectedId,
  domains,
  tags,
  loading,
}: {
  documents: DocumentSummary[];
  document?: DocumentDetail;
  selectedId?: string;
  setSelectedId: (id: string) => void;
  domains: Domain[];
  tags: Tag[];
  loading: boolean;
}) {
  const [filterWidth, setFilterWidth] = useStoredPaneSize("medusa-filter-pane-width", 248, 184, 360);
  const [detailWidth, setDetailWidth] = useStoredPaneSize("medusa-detail-pane-width", 384, 300, 560);
  const paneStyle = {
    "--filter-pane-width": `${filterWidth}px`,
    "--detail-pane-width": `${detailWidth}px`,
  } as CSSProperties;

  return (
    <section className="library-grid" style={paneStyle}>
      <aside className="filter-pane">
        <div className="pane-heading">
          <FolderTree size={17} />
          Domains
        </div>
        <DomainTree domains={domains} />
        <div className="pane-heading tags-heading">
          <Tags size={17} />
          Keywords
        </div>
        <div className="tag-cloud">
          {tags.slice(0, 24).map((tag) => (
            <span key={tag.id}>{tag.name}</span>
          ))}
        </div>
      </aside>
      <ResizeHandle
        className="filter-resizer"
        label="Resize filters pane"
        max={360}
        min={184}
        setValue={setFilterWidth}
        value={filterWidth}
      />
      <section className="document-list">
        <div className="list-toolbar">
          <strong>{loading ? "Searching..." : `${documents.length} documents`}</strong>
          <button className="secondary-button">
            <Plus size={16} />
            Bulk edit
          </button>
        </div>
        <div className="rows">
          {documents.map((item) => (
            <button key={item.id} className={`doc-row ${selectedId === item.id ? "selected" : ""}`} onClick={() => setSelectedId(item.id)}>
              <div>
                <strong>{item.title}</strong>
                <span>{authorLine(item)} {item.publication_year ? `• ${item.publication_year}` : ""}</span>
              </div>
              <div className="row-meta">
                <StatusPill value={item.processing_status} tone={item.processing_status === "ready" ? "good" : "blue"} />
                <StatusPill value={item.citation_status} tone={item.citation_status === "verified" ? "good" : "warn"} />
              </div>
            </button>
          ))}
        </div>
      </section>
      <ResizeHandle
        className="detail-resizer"
        invert
        label="Resize document detail pane"
        max={560}
        min={300}
        setValue={setDetailWidth}
        value={detailWidth}
      />
      <DocumentPanel document={document} />
    </section>
  );
}

function DocumentPanel({ document }: { document?: DocumentDetail }) {
  if (!document) {
    return (
      <aside className="detail-pane empty">
        <Archive size={32} />
        <strong>No document selected</strong>
      </aside>
    );
  }

  const copyCitation = () => {
    if (document.apa_citation) void navigator.clipboard?.writeText(document.apa_citation);
  };

  return (
    <aside className="detail-pane">
      <div className="detail-head">
        <div>
          <h2>{document.title}</h2>
          <p>{authorLine(document)}</p>
        </div>
        <StatusPill value={document.priority} tone="blue" />
      </div>
      <div className="pdf-preview">
        <FileSearch size={44} />
        <span>{document.page_count || "?"} pages</span>
      </div>
      <section className="detail-section">
        <h3>APA</h3>
        <p>{document.apa_citation || "Needs review"}</p>
        <button className="secondary-button" onClick={copyCitation} disabled={!document.apa_citation}>
          <Clipboard size={15} />
          Copy
        </button>
      </section>
      <section className="detail-section">
        <h3>Summary</h3>
        <p>{document.rich_summary || "Summary pending."}</p>
      </section>
      <section className="detail-section">
        <h3>Tags</h3>
        <div className="tag-cloud">
          {document.tags.map((tag) => (
            <span key={tag.id}>{tag.name}</span>
          ))}
        </div>
      </section>
      <section className="detail-section">
        <h3>Evidence</h3>
        <pre>{JSON.stringify(document.metadata_evidence, null, 2)}</pre>
      </section>
    </aside>
  );
}

function ImportView({ jobs }: { jobs: ImportJob[] }) {
  const [priority, setPriority] = useState("normal");
  const [readStatus, setReadStatus] = useState("unread");
  const [dragDepth, setDragDepth] = useState(0);
  const [dropMessage, setDropMessage] = useState("Ready");
  const queryClient = useQueryClient();
  const upload = useMutation({
    mutationFn: (incomingFiles: File[]) => api.uploadBatch(incomingFiles, { priority, read_status: readStatus }),
    onMutate: (incomingFiles) => {
      setDropMessage(`Importing ${incomingFiles.length} PDF${incomingFiles.length === 1 ? "" : "s"}`);
    },
    onSuccess: (_batch, incomingFiles) => {
      setDropMessage(`Queued ${incomingFiles.length} PDF${incomingFiles.length === 1 ? "" : "s"}`);
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (error) => {
      setDropMessage(error instanceof Error ? error.message : "Import failed");
    },
  });
  const isDraggingFiles = dragDepth > 0;

  const hasDraggedFiles = (event: DragEvent<HTMLElement>) => Array.from(event.dataTransfer.types).includes("Files");
  const importFiles = (incomingFiles: FileList | File[]) => {
    const allFiles = Array.from(incomingFiles);
    const pdfs = allFiles.filter((file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"));
    if (upload.isPending) {
      setDropMessage("Import already running");
      return;
    }
    if (!pdfs.length) {
      setDropMessage(allFiles.length ? "PDFs only" : "No files selected");
      return;
    }
    const rejectedCount = allFiles.length - pdfs.length;
    if (rejectedCount > 0) {
      setDropMessage(`Importing ${pdfs.length}; ignored ${rejectedCount}`);
    }
    upload.mutate(pdfs);
  };

  return (
    <section className="workbench">
      <div
        className={`dropzone${isDraggingFiles ? " active" : ""}${upload.isPending ? " uploading" : ""}`}
        onDragEnter={(event) => {
          if (!hasDraggedFiles(event)) return;
          event.preventDefault();
          setDragDepth((depth) => depth + 1);
        }}
        onDragOver={(event) => {
          if (!hasDraggedFiles(event)) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }}
        onDragLeave={(event) => {
          if (!hasDraggedFiles(event)) return;
          event.preventDefault();
          setDragDepth((depth) => Math.max(0, depth - 1));
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragDepth(0);
          importFiles(event.dataTransfer.files);
        }}
      >
        <div className="dropzone-content">
          <span className="dropzone-icon-shell">
            <UploadCloud size={42} />
          </span>
          <strong>{isDraggingFiles ? "Release to import" : upload.isPending ? "Importing" : "Drop PDFs"}</strong>
          <span className="dropzone-hint">{isDraggingFiles ? "PDFs will start immediately" : "or click anywhere"}</span>
          <span className="dropzone-status">{dropMessage}</span>
        </div>
        <input
          aria-label="Import PDFs"
          type="file"
          multiple
          accept="application/pdf"
          onChange={(event) => {
            importFiles(event.target.files || []);
            event.currentTarget.value = "";
          }}
        />
      </div>
      <div className="import-controls">
        <label>
          Priority
          <select value={priority} onChange={(event) => setPriority(event.target.value)}>
            <option value="urgent">Urgent</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
            <option value="low">Low</option>
          </select>
        </label>
        <label>
          Read status
          <select value={readStatus} onChange={(event) => setReadStatus(event.target.value)}>
            <option value="unread">Unread</option>
            <option value="skimmed">Skimmed</option>
            <option value="read">Read</option>
          </select>
        </label>
        <div className="import-live-status">
          <Cloud size={17} />
          <span>{upload.isPending ? "Submitting upload" : "Imports start on drop"}</span>
        </div>
      </div>
      <section className="job-list">
        <h2>Processing</h2>
        {jobs.slice(0, 20).map((job) => (
          <div key={job.id} className="job-row">
            <span>{job.current_step}</span>
            <StatusPill value={job.status} tone={job.status === "failed" ? "warn" : job.status === "complete" ? "good" : "blue"} />
          </div>
        ))}
      </section>
    </section>
  );
}

function ProjectsView({ projects }: { projects: Project[] }) {
  const [name, setName] = useState("");
  const [bibliography, setBibliography] = useState<Bibliography | null>(null);
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () => api.createProject(name),
    onSuccess: () => {
      setName("");
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  return (
    <section className="workbench split">
      <div>
        <div className="inline-form">
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="New project" />
          <button className="primary-button" disabled={!name} onClick={() => create.mutate()}>
            <Plus size={16} />
            Add
          </button>
        </div>
        <div className="project-list">
          {projects.map((project) => (
            <button key={project.id} onClick={async () => setBibliography(await api.bibliography(project.id))}>
              <strong>{project.name}</strong>
              <span>{project.item_count} resources</span>
            </button>
          ))}
        </div>
      </div>
      <pre className="bibliography">{bibliography?.apa || "Select a project bibliography."}</pre>
    </section>
  );
}

function ReviewView({ items }: { items: CitationCandidate[] }) {
  return (
    <section className="workbench">
      <h2>Citation Review</h2>
      <div className="review-list">
        {items.map((item) => (
          <article key={item.id}>
            <div>
              <strong>{String(item.metadata.title || "Untitled")}</strong>
              <span>{item.source}</span>
            </div>
            <p>{item.citation_text || "No candidate citation"}</p>
            <StatusPill value={item.status} tone="warn" />
          </article>
        ))}
      </div>
    </section>
  );
}

function SettingsView() {
  return (
    <section className="workbench settings-grid">
      <div>
        <Gauge size={22} />
        <h2>Runtime</h2>
        <p>Port 3737, FastAPI, PostgreSQL, pgvector, durable worker.</p>
      </div>
      <div>
        <Cloud size={22} />
        <h2>Storage</h2>
        <p>Set GCS_BUCKET and GOOGLE_APPLICATION_CREDENTIALS to use Google Cloud Storage and Vision OCR.</p>
      </div>
      <div>
        <Sparkles size={22} />
        <h2>AI</h2>
        <p>Set OPENAI_API_KEY to enable structured metadata, summaries, topics, and embeddings.</p>
      </div>
    </section>
  );
}

export default function App() {
  const [activeView, setActiveView] = useState<View>("library");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [theme, setTheme] = useState<"day" | "night">(() => (localStorage.getItem("medusa-theme") as "day" | "night") || "day");
  const [sidebarWidth, setSidebarWidth] = useStoredPaneSize("medusa-sidebar-width", 220, 168, 304);
  const queryClient = useQueryClient();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("medusa-theme", theme);
  }, [theme]);

  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, enabled: Boolean(me.data), refetchInterval: 8000 });
  const domains = useQuery({ queryKey: ["domains"], queryFn: api.domains, enabled: Boolean(me.data) });
  const tags = useQuery({ queryKey: ["tags"], queryFn: api.tags, enabled: Boolean(me.data) });
  const documents = useQuery({
    queryKey: ["documents", query],
    queryFn: () => api.documents(query),
    enabled: Boolean(me.data),
    refetchInterval: 10000,
  });
  const selectedDocument = useQuery({
    queryKey: ["document", selectedId],
    queryFn: () => api.document(selectedId!),
    enabled: Boolean(me.data && selectedId),
  });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, enabled: Boolean(me.data), refetchInterval: 4000 });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, enabled: Boolean(me.data) });
  const review = useQuery({ queryKey: ["review"], queryFn: api.reviewQueue, enabled: Boolean(me.data), refetchInterval: 10000 });
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => queryClient.clear(),
  });

  useEffect(() => {
    if (!selectedId && documents.data?.[0]) setSelectedId(documents.data[0].id);
  }, [documents.data, selectedId]);

  if (me.isLoading) return <div className="loading-screen">Medusa</div>;
  if (me.error || !me.data) return <Login />;

  const shellStyle = { "--sidebar-width": `${sidebarWidth}px` } as CSSProperties;

  return (
    <div className="app-shell" style={shellStyle}>
      <Header query={query} setQuery={setQuery} theme={theme} setTheme={setTheme} onLogout={() => logout.mutate()} />
      <Sidebar activeView={activeView} setActiveView={setActiveView} queuedJobs={dashboard.data?.queued_jobs || 0} />
      <ResizeHandle
        className="sidebar-resizer"
        label="Resize navigation pane"
        max={304}
        min={168}
        setValue={setSidebarWidth}
        value={sidebarWidth}
      />
      <main className="content">
        <section className="metrics">
          <div>
            <strong>{dashboard.data?.documents ?? 0}</strong>
            <span>Documents</span>
          </div>
          <div>
            <strong>{dashboard.data?.unread ?? 0}</strong>
            <span>Unread</span>
          </div>
          <div>
            <strong>{dashboard.data?.needs_review ?? 0}</strong>
            <span>Review</span>
          </div>
          <div>
            <strong>{dashboard.data?.queued_jobs ?? 0}</strong>
            <span>Jobs</span>
          </div>
        </section>
        {activeView === "library" || activeView === "domains" || activeView === "notes" ? (
          <LibraryView
            documents={documents.data || []}
            document={selectedDocument.data}
            selectedId={selectedId}
            setSelectedId={setSelectedId}
            domains={domains.data || []}
            tags={tags.data || []}
            loading={documents.isFetching}
          />
        ) : null}
        {activeView === "import" ? <ImportView jobs={jobs.data || []} /> : null}
        {activeView === "projects" ? <ProjectsView projects={projects.data || []} /> : null}
        {activeView === "review" ? <ReviewView items={review.data || []} /> : null}
        {activeView === "settings" ? <SettingsView /> : null}
      </main>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, DragEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Bookmark,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  CheckSquare,
  Clipboard,
  Cloud,
  Download,
  Edit3,
  ExternalLink,
  FileSearch,
  FileText,
  Filter,
  FolderTree,
  Gauge,
  Info,
  Image,
  Library,
  ListChecks,
  ListTodo,
  LogOut,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings,
  Sparkles,
  Sun,
  Tags,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { api } from "./lib/api";
import type {
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
  DocumentSummary,
  DocumentUpdatePayload,
  Domain,
  DuplicateImportStrategy,
  ImportDuplicateCheck,
  ImportJob,
  Note,
  NotePayload,
  Project,
  ProjectItem,
  SavedSearch,
  Tag,
} from "./types";

type View = "library" | "domains" | "projects" | "queue" | "notes" | "import" | "settings";

const FILTER_PANE_MIN = 260;
const FILTER_PANE_DEFAULT = 280;
const FILTER_PANE_MAX = 420;

const navItems: Array<{ id: View; label: string; icon: typeof Library }> = [
  { id: "library", label: "Library", icon: Library },
  { id: "domains", label: "Domains", icon: FolderTree },
  { id: "projects", label: "Projects", icon: ListChecks },
  { id: "queue", label: "Queue", icon: ListTodo },
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

function recommendationAuthorLine(item: DocumentRecommendation) {
  const authors = item.authors || [];
  if (!authors.length) return "Unknown author";
  return authors
    .slice(0, 3)
    .map((author) => [author.given, author.family].filter(Boolean).join(" "))
    .filter(Boolean)
    .join(", ");
}

function recommendationProviderLabel(value: string) {
  return value
    .split(",")
    .map((part) =>
      part
        .trim()
        .replaceAll("_", " ")
        .replace(/\b\w/g, (letter) => letter.toUpperCase()),
    )
    .join(", ");
}

function StatusPill({ value, tone = "neutral" }: { value: string; tone?: "neutral" | "good" | "warn" | "blue" }) {
  return <span className={`pill ${tone}`}>{value.replaceAll("_", " ")}</span>;
}

function uniqueValues(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function authorsToText(document: DocumentSummary | DocumentDetail) {
  return (document.authors || [])
    .map((author) => {
      const given = author.given || "";
      const family = author.family || "";
      return family && given ? `${family}, ${given}` : family || given || "";
    })
    .filter(Boolean)
    .join("\n");
}

function parseAuthorText(value: string) {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      if (line.includes(",")) {
        const [family, ...givenParts] = line.split(",");
        return { family: family.trim(), given: givenParts.join(",").trim(), affiliation: null };
      }
      const parts = line.split(/\s+/);
      if (parts.length === 1) return { family: parts[0], given: "", affiliation: null };
      return { family: parts.at(-1) || "", given: parts.slice(0, -1).join(" "), affiliation: null };
    });
}

function splitCommaList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function emptyFilters(): DocumentFilters {
  return { domain_id: "", tag_id: "", read_status: "", priority: "", citation_status: "", duplicate_status: "" };
}

function cleanFilters(filters: DocumentFilters): DocumentFilters {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => Boolean(value))) as DocumentFilters;
}

function attributeDisplayValue(value: Record<string, unknown>) {
  if ("value" in value) return String(value.value ?? "");
  return JSON.stringify(value);
}

function decodeHtmlEntities(value: string) {
  if (!value) return value;
  const textarea = window.document.createElement("textarea");
  textarea.innerHTML = value;
  return textarea.value;
}

function decodeHtmlEntitiesDeep(value: unknown): unknown {
  if (typeof value === "string") return decodeHtmlEntities(value);
  if (Array.isArray(value)) return value.map((item) => decodeHtmlEntitiesDeep(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, decodeHtmlEntitiesDeep(item)]));
  }
  return value;
}

function formatFileSize(bytes?: number | null) {
  if (!bytes || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const precision = value >= 10 || unitIndex === 0 ? 0 : 1;
  return `${value.toFixed(precision)} ${units[unitIndex]}`;
}

function formatDuration(seconds?: number | null) {
  if (seconds === undefined || seconds === null || Number.isNaN(seconds)) return "";
  const safeSeconds = Math.max(0, Math.floor(seconds));
  if (safeSeconds < 60) return `${safeSeconds}s`;
  const minutes = Math.floor(safeSeconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

function importJobProgress(job: ImportJob) {
  if (job.status === "complete") return 100;
  if (job.status === "failed") return 100;
  if (job.status === "queued") return 0;
  const step = job.current_step || "stored";
  const pageMatch = step.match(/^normalizing_page_(\d+)$/);
  if (pageMatch) {
    const pageNumber = Number(pageMatch[1]);
    const pageCount = Math.max(1, job.document_page_count || pageNumber);
    return Math.min(58, 12 + Math.round((Math.min(pageNumber, pageCount) / pageCount) * 42));
  }
  const progressByStep: Record<string, number> = {
    stored: 2,
    extracting: 8,
    normalizing_pages: 12,
    extracted: 58,
    extracting_figures: 62,
    figures: 68,
    enriching: 76,
    enriched: 84,
    indexing: 90,
    indexed: 95,
    cleaning_cache: 97,
  };
  return progressByStep[step] ?? (job.status === "running" ? 8 : 0);
}

function importJobStage(job: ImportJob) {
  const pageMatch = job.current_step.match(/^normalizing_page_(\d+)$/);
  if (pageMatch) {
    const pageCount = job.document_page_count ? `/${job.document_page_count}` : "";
    return `normalizing page ${pageMatch[1]}${pageCount}`;
  }
  return job.current_step.replaceAll("_", " ");
}

function importJobLabel(job: ImportJob) {
  const name = job.original_filename || job.document_title || job.current_step || "Import";
  const size = formatFileSize(job.file_size_bytes);
  return `${name}${size ? ` (${size})` : ""}${job.status === "complete" ? " (done)" : ""}`;
}

function importJobStepLabel(job: ImportJob) {
  if (job.status === "complete") return "complete";
  if (job.status === "failed") return job.last_error || "failed";
  return importJobStage(job);
}

function canRescueImportJob(job: ImportJob) {
  if (job.status === "failed" || job.status === "restored_paused") return true;
  if (job.status !== "running" || !job.locked_at) return false;
  return Date.now() - new Date(job.locked_at).getTime() > 15 * 60 * 1000;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function normalizeHexColor(value?: string | null, fallback = "#2563eb") {
  return /^#[0-9a-fA-F]{6}$/.test(value || "") ? String(value).toLowerCase() : fallback;
}

function mixHexColors(foreground: string, background: string, foregroundWeight: number) {
  const parse = (value: string) => [1, 3, 5].map((start) => Number.parseInt(value.slice(start, start + 2), 16));
  const fg = parse(foreground);
  const bg = parse(background);
  const channel = (index: number) => Math.round(fg[index] * foregroundWeight + bg[index] * (1 - foregroundWeight));
  return `#${[0, 1, 2].map((index) => channel(index).toString(16).padStart(2, "0")).join("")}`;
}

function accentSoftColor(accent: string, theme: "day" | "night") {
  return mixHexColors(accent, theme === "night" ? "#172033" : "#ffffff", theme === "night" ? 0.28 : 0.12);
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

function useStoredBoolean(key: string, defaultValue: boolean) {
  const [value, setValue] = useState(() => {
    const stored = localStorage.getItem(key);
    if (stored === "true") return true;
    if (stored === "false") return false;
    return defaultValue;
  });

  useEffect(() => {
    localStorage.setItem(key, String(value));
  }, [key, value]);

  return [value, setValue] as const;
}

function useClipboardNotice(resetMs = 1600) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const timeoutRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    },
    [],
  );

  const copyToClipboard = async (key: string, text: string) => {
    if (!text || !navigator.clipboard) return;
    await navigator.clipboard.writeText(text);
    setCopiedKey(key);
    if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    timeoutRef.current = window.setTimeout(() => {
      setCopiedKey((current) => (current === key ? null : current));
    }, resetMs);
  };

  return { copiedKey, copyToClipboard };
}

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text))) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${match.index}`;
    if (token.startsWith("**")) nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith("*")) nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    else nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function markdownExcerpt(markdown: string, maxChars = 360): string {
  const lines = decodeHtmlEntities(markdown)
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const usefulLines = lines.filter((line) => !/^#{1,6}\s+/.test(line)).slice(0, 4);
  const joined = usefulLines.join("\n");
  if (joined.length <= maxChars) return joined;
  const sentenceEnd = joined.slice(0, maxChars).search(/[.!?]\s+[A-Z0-9*`]/);
  if (sentenceEnd > 120) return joined.slice(0, sentenceEnd + 1).trim();
  const trimmed = joined.slice(0, maxChars).trimEnd();
  return `${trimmed.replace(/[,\s;:]+$/, "")}...`;
}

function MarkdownBlock({
  content,
  empty,
  compact = false,
}: {
  content?: string | null;
  empty: string;
  compact?: boolean;
}) {
  const source = decodeHtmlEntities(content || "").trim();
  if (!source) return <p className="markdown-empty">{empty}</p>;

  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let orderedItems: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const text = paragraph.join(" ");
    blocks.push(<p key={`p-${blocks.length}`}>{renderInlineMarkdown(text, `p-${blocks.length}`)}</p>);
    paragraph = [];
  };
  const flushList = () => {
    if (listItems.length) {
      blocks.push(
        <ul key={`ul-${blocks.length}`}>
          {listItems.map((item, index) => (
            <li key={`${item}-${index}`}>{renderInlineMarkdown(item, `ul-${blocks.length}-${index}`)}</li>
          ))}
        </ul>,
      );
      listItems = [];
    }
    if (orderedItems.length) {
      blocks.push(
        <ol key={`ol-${blocks.length}`}>
          {orderedItems.map((item, index) => (
            <li key={`${item}-${index}`}>{renderInlineMarkdown(item, `ol-${blocks.length}-${index}`)}</li>
          ))}
        </ol>,
      );
      orderedItems = [];
    }
  };

  source.split(/\n/).forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      return;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push(<strong key={`h-${blocks.length}`}>{renderInlineMarkdown(heading[2], `h-${blocks.length}`)}</strong>);
      return;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      orderedItems = [];
      listItems.push(bullet[1]);
      return;
    }
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      listItems = [];
      orderedItems.push(ordered[1]);
      return;
    }
    flushList();
    paragraph.push(line);
  });
  flushParagraph();
  flushList();

  return <div className={`markdown-content ${compact ? "compact" : ""}`}>{blocks}</div>;
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
          <div className="brand-mark">
            <img className="brand-emblem" src="/medusa-emblem.svg" alt="" aria-hidden="true" />
          </div>
          <div className="brand-wordmark">
            <strong className="brand-name">medusa</strong>
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
      <div className="topbar-brand-area">
        <div className="brand">
          <div className="brand-mark compact">
            <img className="brand-emblem" src="/medusa-emblem.svg" alt="" aria-hidden="true" />
          </div>
          <div className="brand-wordmark">
            <strong className="brand-name">medusa</strong>
          </div>
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

function Sidebar({
  activeView,
  collapsed,
  activeImportJobs,
  dashboard,
  onOpenQueue,
  onToggleSidebar,
  setActiveView,
}: {
  activeView: View;
  collapsed: boolean;
  activeImportJobs: number;
  dashboard?: Dashboard;
  onOpenQueue: () => void;
  onToggleSidebar: () => void;
  setActiveView: (view: View) => void;
}) {
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      {!collapsed ? (
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={activeView === item.id ? "active" : ""} onClick={() => setActiveView(item.id)}>
                <Icon size={18} />
                <span>{item.label}</span>
                {item.id === "import" && activeImportJobs > 0 ? <small>{activeImportJobs}</small> : null}
              </button>
            );
          })}
        </nav>
      ) : null}
      <div className="sidebar-bottom">
        {!collapsed ? <SidebarImportProgress dashboard={dashboard} onOpenQueue={onOpenQueue} /> : null}
        <button
          className="icon-button sidebar-toggle"
          title={collapsed ? "Show navigation" : "Hide navigation"}
          onClick={onToggleSidebar}
          type="button"
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>
    </aside>
  );
}

function SidebarImportProgress({ dashboard, onOpenQueue }: { dashboard?: Dashboard; onOpenQueue: () => void }) {
  if (!dashboard || dashboard.active_import_jobs <= 0) return null;
  const total = dashboard.import_progress_total || dashboard.active_import_jobs;
  const finished = Math.min(total, dashboard.import_progress_completed + dashboard.import_progress_failed);
  const percent = total > 0 ? Math.round((finished / total) * 100) : 0;
  const visiblePercent = dashboard.import_running_jobs > 0 && percent === 0 ? 6 : percent;
  const fillWidth = `${Math.max(0, Math.min(100, visiblePercent))}%`;
  const activeStep = dashboard.import_active_step?.replaceAll("_", " ");
  const activeElapsed = formatDuration(dashboard.import_active_elapsed_seconds);

  return (
    <button className="sidebar-import-progress" type="button" aria-label="Open import queue" onClick={onOpenQueue}>
      <div className="sidebar-progress-head">
        <span>Imports</span>
        <strong>{percent}%</strong>
      </div>
      <div
        className={`sidebar-progress-track${dashboard.import_running_jobs > 0 ? " active" : ""}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span style={{ width: fillWidth }} />
      </div>
      {activeStep ? (
        <div className="sidebar-progress-step">
          <span>{activeStep}</span>
          {activeElapsed ? <strong>{activeElapsed}</strong> : null}
        </div>
      ) : null}
      <div className="sidebar-progress-meta">
        <span>{dashboard.import_running_jobs} importing</span>
        <span>{dashboard.import_queued_jobs} queued</span>
      </div>
    </button>
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
  projects,
  citationJobs,
  query,
  setQuery,
  filters,
  setFilters,
  savedSearches,
  loading,
}: {
  documents: DocumentSummary[];
  document?: DocumentDetail;
  selectedId?: string;
  setSelectedId: (id: string) => void;
  domains: Domain[];
  tags: Tag[];
  projects: Project[];
  citationJobs: ConcordanceJob[];
  query: string;
  setQuery: (query: string) => void;
  filters: DocumentFilters;
  setFilters: (filters: DocumentFilters) => void;
  savedSearches: SavedSearch[];
  loading: boolean;
}) {
  const [filterWidth, setFilterWidth] = useStoredPaneSize("medusa-filter-pane-width", FILTER_PANE_DEFAULT, FILTER_PANE_MIN, FILTER_PANE_MAX);
  const [detailWidth, setDetailWidth] = useStoredPaneSize("medusa-detail-pane-width", 384, 300, 560);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [readerOpen, setReaderOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [bulkReadStatus, setBulkReadStatus] = useState("");
  const [bulkPriority, setBulkPriority] = useState("");
  const [bulkTagId, setBulkTagId] = useState("");
  const [bulkCustomTag, setBulkCustomTag] = useState("");
  const [bulkDomainId, setBulkDomainId] = useState("");
  const queryClient = useQueryClient();
  const saveSearch = useMutation({
    mutationFn: () => api.createSavedSearch({ name: saveName, query, filters: cleanFilters(filters) }),
    onSuccess: () => {
      setSaveName("");
      void queryClient.invalidateQueries({ queryKey: ["saved-searches"] });
    },
  });
  const deleteSearch = useMutation({
    mutationFn: (id: string) => api.deleteSavedSearch(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["saved-searches"] }),
  });
  const bulkUpdate = useMutation({
    mutationFn: () => {
      const updates: Record<string, unknown> = {};
      if (bulkReadStatus) updates.read_status = bulkReadStatus;
      if (bulkPriority) updates.priority = bulkPriority;
      if (bulkTagId && bulkTagId !== "__custom__") updates.tag_ids = [bulkTagId];
      if (bulkCustomTag.trim()) updates.tag_names = [bulkCustomTag.trim()];
      if (bulkDomainId) updates.domain_ids = [bulkDomainId];
      return api.bulkUpdateDocuments(selectedIds, updates);
    },
    onSuccess: () => {
      setSelectedIds([]);
      setBulkReadStatus("");
      setBulkPriority("");
      setBulkTagId("");
      setBulkCustomTag("");
      setBulkDomainId("");
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document"] });
      void queryClient.invalidateQueries({ queryKey: ["domains"] });
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
    },
  });
  const batchConcordance = useMutation({
    mutationFn: () =>
      api.createConcordanceRun({
        label: `Selected document Concordance (${selectedIds.length})`,
        scope_type: "documents",
        scope_data: { document_ids: selectedIds },
      }),
    onSuccess: () => {
      setSelectedIds([]);
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document"] });
    },
  });
  const paneStyle = {
    "--filter-pane-width": `${filterWidth}px`,
    "--detail-pane-width": `${detailWidth}px`,
  } as CSSProperties;
  const allVisibleSelected = documents.length > 0 && documents.every((item) => selectedIds.includes(item.id));
  const sortedTags = useMemo(() => [...tags].sort((left, right) => left.name.localeCompare(right.name)), [tags]);
  const hasBulkUpdate = Boolean(
    bulkReadStatus || bulkPriority || (bulkTagId && bulkTagId !== "__custom__") || bulkCustomTag.trim() || bulkDomainId,
  );

  const setFilterValue = (key: keyof DocumentFilters, value: string) => {
    setFilters({ ...filters, [key]: value });
  };

  const applySavedSearch = (savedSearch: SavedSearch) => {
    setQuery(savedSearch.query || "");
    setFilters({ ...emptyFilters(), ...savedSearch.filters });
  };

  const activateDocument = (id: string) => {
    setSelectedId(id);
  };

  const toggleSelected = (id: string) => {
    activateDocument(id);
    setSelectedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  };

  if (readerOpen && document) {
    return (
      <section className="library-grid reader-mode" style={paneStyle}>
        <DocumentPanel
          citationJobs={citationJobs}
          document={document}
          domains={domains}
          onCloseReader={() => setReaderOpen(false)}
          projects={projects}
          query={query}
          readerExpanded
          tags={tags}
        />
      </section>
    );
  }

  return (
    <section className="library-grid" style={paneStyle}>
      <aside className="filter-pane">
        <div className="pane-heading">
          <Filter size={17} />
          Filters
        </div>
        <div className="filter-controls">
          <label>
            Domain
            <select value={filters.domain_id || ""} onChange={(event) => setFilterValue("domain_id", event.target.value)}>
              <option value="">Any domain</option>
              {domains.map((domain) => (
                <option key={domain.id} value={domain.id}>
                  {domain.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Tag
            <select value={filters.tag_id || ""} onChange={(event) => setFilterValue("tag_id", event.target.value)}>
              <option value="">Any tag</option>
              {tags.map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Read
            <select value={filters.read_status || ""} onChange={(event) => setFilterValue("read_status", event.target.value)}>
              <option value="">Any read status</option>
              <option value="unread">Unread</option>
              <option value="skimmed">Skimmed</option>
              <option value="read">Read</option>
            </select>
          </label>
          <label>
            Priority
            <select value={filters.priority || ""} onChange={(event) => setFilterValue("priority", event.target.value)}>
              <option value="">Any priority</option>
              <option value="urgent">Urgent</option>
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
          </label>
          <label>
            Citation
            <select value={filters.citation_status || ""} onChange={(event) => setFilterValue("citation_status", event.target.value)}>
              <option value="">Any citation status</option>
              <option value="needs_review">Needs review</option>
              <option value="verified">Verified</option>
              <option value="rejected">Rejected</option>
            </select>
          </label>
          <label>
            Duplicates
            <select value={filters.duplicate_status || ""} onChange={(event) => setFilterValue("duplicate_status", event.target.value)}>
              <option value="">Any duplicate status</option>
              <option value="duplicates">Has duplicates</option>
              <option value="unique">No exact duplicates</option>
            </select>
          </label>
          <button className="secondary-button" onClick={() => setFilters(emptyFilters())}>
            <X size={15} />
            Clear
          </button>
        </div>
        <div className="pane-heading tags-heading">
          <Bookmark size={17} />
          Saved
        </div>
        <form
          className="saved-search-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (saveName.trim()) saveSearch.mutate();
          }}
        >
          <input value={saveName} onChange={(event) => setSaveName(event.target.value)} placeholder="Name current view" />
          <button className="secondary-button" type="submit" disabled={!saveName.trim() || saveSearch.isPending}>
            <Save size={14} />
          </button>
        </form>
        <div className="saved-search-list">
          {savedSearches.map((savedSearch) => (
            <div key={savedSearch.id}>
              <button type="button" onClick={() => applySavedSearch(savedSearch)}>
                {savedSearch.name}
              </button>
              <button type="button" title="Delete saved search" onClick={() => deleteSearch.mutate(savedSearch.id)}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
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
        max={FILTER_PANE_MAX}
        min={FILTER_PANE_MIN}
        setValue={setFilterWidth}
        value={filterWidth}
      />
      <section className="document-list">
        <div className="list-toolbar">
          <label className="select-all-row">
            <input
              type="checkbox"
              checked={allVisibleSelected}
              onChange={() => {
                if (allVisibleSelected) {
                  setSelectedIds([]);
                  return;
                }
                setSelectedIds(documents.map((item) => item.id));
                if (documents[0]) activateDocument(documents[0].id);
              }}
            />
            <strong>{loading ? "Searching..." : `${documents.length} documents`}</strong>
          </label>
          {selectedIds.length ? (
            <div className="bulk-bar">
              <span>{selectedIds.length} selected</span>
              <select value={bulkReadStatus} onChange={(event) => setBulkReadStatus(event.target.value)}>
                <option value="">Read status</option>
                <option value="unread">Unread</option>
                <option value="skimmed">Skimmed</option>
                <option value="read">Read</option>
              </select>
              <select value={bulkPriority} onChange={(event) => setBulkPriority(event.target.value)}>
                <option value="">Priority</option>
                <option value="urgent">Urgent</option>
                <option value="high">High</option>
                <option value="normal">Normal</option>
                <option value="low">Low</option>
              </select>
              <select
                value={bulkTagId}
                onChange={(event) => {
                  setBulkTagId(event.target.value);
                  if (event.target.value && event.target.value !== "__custom__") setBulkCustomTag("");
                }}
              >
                <option value="">Add tag</option>
                {sortedTags.map((tag) => (
                  <option key={tag.id} value={tag.id}>
                    {tag.name}
                  </option>
                ))}
                <option value="__custom__">Custom tag...</option>
              </select>
              {bulkTagId === "__custom__" || bulkCustomTag ? (
                <input
                  className="bulk-custom-tag"
                  placeholder="Custom tag"
                  value={bulkCustomTag}
                  onChange={(event) => {
                    setBulkCustomTag(event.target.value);
                    setBulkTagId("__custom__");
                  }}
                />
              ) : null}
              <select value={bulkDomainId} onChange={(event) => setBulkDomainId(event.target.value)}>
                <option value="">Add domain</option>
                {domains.map((domain) => (
                  <option key={domain.id} value={domain.id}>
                    {domain.name}
                  </option>
                ))}
              </select>
              <button className="primary-button" disabled={!hasBulkUpdate || bulkUpdate.isPending} onClick={() => bulkUpdate.mutate()}>
                <CheckSquare size={15} />
                Apply
              </button>
              <button className="secondary-button" disabled={batchConcordance.isPending} onClick={() => batchConcordance.mutate()}>
                <RefreshCw size={15} />
                Concord
              </button>
            </div>
          ) : null}
        </div>
        <div className="rows">
          {documents.map((item) => (
            <div
              key={item.id}
              className={`doc-row ${selectedId === item.id ? "selected" : ""}`}
              onClick={() => activateDocument(item.id)}
              onPointerDown={() => activateDocument(item.id)}
            >
              <input
                aria-label={`Select ${item.title}`}
                checked={selectedIds.includes(item.id)}
                onClick={(event) => event.stopPropagation()}
                onPointerDown={(event) => event.stopPropagation()}
                onChange={() => toggleSelected(item.id)}
                type="checkbox"
              />
              <button className="doc-row-main" onClick={() => activateDocument(item.id)} type="button">
                <strong>{item.title}</strong>
                <span>
                  {authorLine(item)} {item.publication_year ? `• ${item.publication_year}` : ""}
                </span>
              </button>
              <div className="row-meta">
                {item.duplicate_count > 0 ? <StatusPill value={`Duplicate ${item.duplicate_count + 1}`} tone="warn" /> : null}
                <StatusPill value={item.processing_status} tone={item.processing_status === "ready" ? "good" : "blue"} />
                <StatusPill value={item.citation_status} tone={item.citation_status === "verified" ? "good" : "warn"} />
              </div>
              <div className="doc-row-summary">
                <MarkdownBlock compact content={markdownExcerpt(item.rich_summary || "", 320)} empty="Summary pending." />
              </div>
            </div>
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
      <DocumentPanel
        citationJobs={citationJobs}
        document={document}
        domains={domains}
        onOpenReader={() => setReaderOpen(true)}
        projects={projects}
        query={query}
        tags={tags}
      />
    </section>
  );
}

type AttributeDraft = {
  key: string;
  value: string;
};

type DocumentDraft = {
  title: string;
  subtitle: string;
  authors: string;
  publication_year: string;
  journal: string;
  publisher: string;
  doi: string;
  source_url: string;
  abstract: string;
  rich_summary: string;
  priority: string;
  read_status: string;
  citation_status: string;
  tag_names: string;
  domain_ids: string[];
  attributes: AttributeDraft[];
};

type AnnotationDraft = {
  page_number: string;
  kind: string;
  body: string;
  color: string;
};

type ReaderMode = "pdf" | "text";

function draftFromDocument(document: DocumentDetail): DocumentDraft {
  return {
    title: document.title || "",
    subtitle: document.subtitle || "",
    authors: authorsToText(document),
    publication_year: document.publication_year ? String(document.publication_year) : "",
    journal: document.journal || "",
    publisher: document.publisher || "",
    doi: document.doi || "",
    source_url: document.source_url || "",
    abstract: document.abstract || "",
    rich_summary: document.rich_summary || "",
    priority: document.priority || "normal",
    read_status: document.read_status || "unread",
    citation_status: document.citation_status || "needs_review",
    tag_names: document.tags.map((tag) => tag.name).join(", "),
    domain_ids: document.domains.map((domain) => domain.id),
    attributes: document.attributes.map((attribute) => ({
      key: attribute.definition.name,
      value: attributeDisplayValue(attribute.value),
    })),
  };
}

function DocumentPanel({
  citationJobs,
  document,
  domains,
  onCloseReader,
  onOpenReader,
  projects,
  query,
  readerExpanded = false,
  tags,
}: {
  citationJobs: ConcordanceJob[];
  document?: DocumentDetail;
  domains: Domain[];
  onCloseReader?: () => void;
  onOpenReader?: () => void;
  projects: Project[];
  query: string;
  readerExpanded?: boolean;
  tags: Tag[];
}) {
  if (!document) {
    return (
      <aside className="detail-pane empty">
        <Archive size={32} />
        <strong>No document selected</strong>
      </aside>
    );
  }

  return (
    <DocumentPanelContent
      citationJobs={citationJobs}
      document={document}
      domains={domains}
      onCloseReader={onCloseReader}
      onOpenReader={onOpenReader}
      projects={projects}
      query={query}
      readerExpanded={readerExpanded}
      tags={tags}
    />
  );
}

function RecommendationsPanel({ document }: { document: DocumentDetail }) {
  const [hideExisting, setHideExisting] = useStoredBoolean("medusa-recommendations-hide-existing", false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const { copiedKey, copyToClipboard } = useClipboardNotice();
  const queryClient = useQueryClient();
  const recommendations = useQuery({
    queryKey: ["document-recommendations", document.id, hideExisting],
    queryFn: () => api.documentRecommendations(document.id, hideExisting),
    enabled: document.processing_status === "ready" && Boolean(document.doi),
  });
  const refresh = useMutation({
    mutationFn: () => api.refreshDocumentRecommendations(document.id),
    onSuccess: (result) => {
      setNotice(`Found ${result.recommendation_count} related papers`);
      void queryClient.invalidateQueries({ queryKey: ["document-recommendations", document.id] });
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "Could not refresh recommendations"),
  });
  const download = useMutation({
    mutationFn: (body: { recommendation_ids?: string[]; mode?: "selected" | "new"; skip_existing?: boolean }) =>
      api.downloadRecommendations(document.id, body),
    onSuccess: (result) => {
      setNotice(
        `Queued ${result.queued_count}; skipped ${result.skipped_existing_count}; unavailable ${result.unavailable_count}; failed ${result.failed_count}`,
      );
      setSelectedIds([]);
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["document-recommendations", document.id] });
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : "Could not queue recommendation downloads"),
  });

  useEffect(() => {
    setSelectedIds([]);
    setNotice("");
  }, [document.id, hideExisting]);

  const rows = recommendations.data || [];
  const newRows = rows.filter((item) => !item.existing_document_id && !item.imported_document_id);
  const selectableRows = rows.filter((item) => !item.existing_document_id && !item.imported_document_id);
  const allSelectableSelected =
    selectableRows.length > 0 && selectableRows.every((item) => selectedIds.includes(item.id));
  const selectedCount = selectedIds.length;
  const selectedDownloadable = rows.filter((item) => selectedIds.includes(item.id) && item.has_pdf).length;
  const newDownloadable = newRows.filter((item) => item.has_pdf).length;
  const canRefresh = document.processing_status === "ready" && Boolean(document.doi);

  const toggleSelected = (id: string) => {
    setSelectedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  };

  const toggleAllSelectable = () => {
    setSelectedIds(allSelectableSelected ? [] : selectableRows.map((item) => item.id));
  };

  return (
    <section className="detail-section recommendations-panel">
      <div className="recommendations-head">
        <div>
          <h3>Recommendations</h3>
          <span>
            {recommendations.isFetching
              ? "Loading related papers"
              : `${rows.length} shown / ${newRows.length} new / ${newDownloadable} with PDFs`}
          </span>
        </div>
        <div className="recommendation-actions">
          <label className="compact-toggle">
            <input type="checkbox" checked={hideExisting} onChange={(event) => setHideExisting(event.target.checked)} />
            <span>Hide existing</span>
          </label>
          <button className="secondary-button compact" disabled={!canRefresh || refresh.isPending} onClick={() => refresh.mutate()} type="button">
            <RefreshCw className={refresh.isPending ? "spin" : ""} size={14} />
            Refresh
          </button>
        </div>
      </div>
      <div className="recommendations-download-row">
        <label className="select-all-row">
          <input type="checkbox" checked={allSelectableSelected} onChange={toggleAllSelectable} disabled={!selectableRows.length} />
          <strong>{selectedCount ? `${selectedCount} selected` : "Select new papers"}</strong>
        </label>
        <button
          className="secondary-button compact"
          disabled={!selectedCount || !selectedDownloadable || download.isPending}
          onClick={() => download.mutate({ recommendation_ids: selectedIds, mode: "selected", skip_existing: true })}
          type="button"
        >
          <Download size={14} />
          Selected
        </button>
        <button
          className="primary-button compact"
          disabled={!newRows.length || !newDownloadable || download.isPending}
          onClick={() => download.mutate({ mode: "new", skip_existing: true })}
          type="button"
        >
          <Download size={14} />
          All new
        </button>
      </div>
      {notice ? <p className="recommendation-notice">{notice}</p> : null}
      {!canRefresh ? (
        <div className="empty-inline">
          <Sparkles size={17} />
          <span>Recommendations need a completed document with a DOI.</span>
        </div>
      ) : rows.length ? (
        <div className="recommendation-list">
          {rows.map((item) => {
            const inLibrary = Boolean(item.existing_document_id || item.imported_document_id);
            return (
              <article key={item.id} className={`recommendation-row ${inLibrary ? "in-library" : ""}`}>
                <input
                  aria-label={`Select ${item.title}`}
                  type="checkbox"
                  checked={selectedIds.includes(item.id)}
                  disabled={inLibrary}
                  onChange={() => toggleSelected(item.id)}
                />
                <div className="recommendation-copy">
                  <div className="recommendation-title-line">
                    <strong>{item.title}</strong>
                    {inLibrary ? <StatusPill value="In library" tone="good" /> : item.has_pdf ? <StatusPill value="PDF" tone="blue" /> : null}
                  </div>
                  <span>
                    {recommendationAuthorLine(item)}
                    {item.publication_year ? ` / ${item.publication_year}` : ""}
                    {item.journal ? ` / ${item.journal}` : ""}
                  </span>
                  {item.doi ? <code>{item.doi}</code> : null}
                  <p>{item.description || "No abstract available from recommendation sources."}</p>
                  <small>
                    {recommendationProviderLabel(item.source_provider)}
                    {item.source_relation ? ` / ${item.source_relation.replaceAll("_", " ")}` : ""}
                    {item.existing_document_title ? ` / ${item.existing_document_title}` : ""}
                  </small>
                </div>
                <div className="recommendation-row-actions">
                  <button
                    className="icon-button"
                    disabled={!item.doi}
                    onClick={() => item.doi && void copyToClipboard(`doi-${item.id}`, item.doi)}
                    title="Copy DOI"
                    type="button"
                  >
                    {copiedKey === `doi-${item.id}` ? <CheckCircle2 size={15} /> : <Clipboard size={15} />}
                  </button>
                  <button
                    className="icon-button"
                    onClick={() => void copyToClipboard(`title-${item.id}`, item.title)}
                    title="Copy title"
                    type="button"
                  >
                    {copiedKey === `title-${item.id}` ? <CheckCircle2 size={15} /> : <FileText size={15} />}
                  </button>
                  {item.source_url ? (
                    <a className="icon-button" href={item.source_url} target="_blank" rel="noreferrer" title="Open source">
                      <ExternalLink size={15} />
                    </a>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-inline">
          <Sparkles size={17} />
          <span>Refresh to find related papers.</span>
        </div>
      )}
    </section>
  );
}

function DocumentPanelContent({
  citationJobs,
  document,
  domains,
  onCloseReader,
  onOpenReader,
  projects,
  query,
  readerExpanded = false,
  tags,
}: {
  citationJobs: ConcordanceJob[];
  document: DocumentDetail;
  domains: Domain[];
  onCloseReader?: () => void;
  onOpenReader?: () => void;
  projects: Project[];
  query: string;
  readerExpanded?: boolean;
  tags: Tag[];
}) {

  const [editing, setEditing] = useState(false);
  const [recommendationsOpen, setRecommendationsOpen] = useState(false);
  const [readerMode, setReaderMode] = useState<ReaderMode>(() => (readerExpanded ? "text" : "pdf"));
  const [readerPageIndex, setReaderPageIndex] = useState(0);
  const [draft, setDraft] = useState<DocumentDraft>(() => draftFromDocument(document));
  const [annotationDraft, setAnnotationDraft] = useState<AnnotationDraft>({
    page_number: "",
    kind: "highlight",
    body: "",
    color: "#f6c343",
  });
  const [saveError, setSaveError] = useState<string | null>(null);
  const { copiedKey, copyToClipboard } = useClipboardNotice();
  const queryClient = useQueryClient();
  const updateDocument = useMutation({
    mutationFn: (body: DocumentUpdatePayload) => api.updateDocument(document.id, body),
    onSuccess: () => {
      setEditing(false);
      setSaveError(null);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
      void queryClient.invalidateQueries({ queryKey: ["domains"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setSaveError(error instanceof Error ? error.message : "Could not save correction"),
  });
  const runConcordance = useMutation({
    mutationFn: () =>
      api.createConcordanceRun({
        label: `Document Concordance: ${document.title}`,
        scope_type: "documents",
        scope_data: { document_ids: [document.id] },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-jobs"] });
    },
  });
  const refreshCitation = useMutation({
    mutationFn: () => api.refreshDocumentCitation(document.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["review"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
    },
  });
  const createAnnotation = useMutation({
    mutationFn: (body: AnnotationPayload) => api.createAnnotation(document.id, body),
    onSuccess: () => {
      setAnnotationDraft({ page_number: "", kind: "highlight", body: "", color: "#f6c343" });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
  const deleteAnnotation = useMutation({
    mutationFn: (annotationId: string) => api.deleteAnnotation(annotationId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  useEffect(() => {
    setDraft(draftFromDocument(document));
    setAnnotationDraft({ page_number: "", kind: "highlight", body: "", color: "#f6c343" });
    setReaderPageIndex(0);
    setEditing(false);
    setRecommendationsOpen(false);
    setSaveError(null);
  }, [document.id]);

  const copyCitation = () => {
    if (document.apa_citation) void copyToClipboard("citation", decodeHtmlEntities(document.apa_citation));
  };
  const pages = useMemo(
    () => [...(document.pages || [])].sort((left, right) => left.page_number - right.page_number),
    [document.pages],
  );
  const pageReadableText = (page: (typeof pages)[number]) => page.normalized_text || page.text || "";
  const fullText = pages.map(pageReadableText).filter(Boolean).join("\n\n");
  const currentPageIndex = pages.length ? Math.min(readerPageIndex, pages.length - 1) : 0;
  const currentPage = pages[currentPageIndex];
  const currentPageText = currentPage ? pageReadableText(currentPage).trim() : "";
  const citationRefreshActive = citationJobs.some(
    (job) => job.document_id === document.id && job.capability_key === "citation_refresh" && ["queued", "running"].includes(job.status),
  );
  const citationBusy = refreshCitation.isPending || citationRefreshActive;
  const copyFullText = () => {
    if (fullText) void copyToClipboard("full-text", fullText);
  };
  const startPageNote = (pageNumber: number) => {
    setReaderMode("text");
    setAnnotationDraft({ page_number: String(pageNumber), kind: "note", body: "", color: "#60a5fa" });
  };

  const setDraftValue = <K extends keyof DocumentDraft>(key: K, value: DocumentDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const toggleDomain = (domainId: string) => {
    setDraft((current) => ({
      ...current,
      domain_ids: current.domain_ids.includes(domainId)
        ? current.domain_ids.filter((id) => id !== domainId)
        : [...current.domain_ids, domainId],
    }));
  };

  const updateAttribute = (index: number, field: keyof AttributeDraft, value: string) => {
    setDraft((current) => ({
      ...current,
      attributes: current.attributes.map((attribute, attributeIndex) =>
        attributeIndex === index ? { ...attribute, [field]: value } : attribute,
      ),
    }));
  };

  const removeAttribute = (index: number) => {
    setDraft((current) => ({
      ...current,
      attributes: current.attributes.filter((_, attributeIndex) => attributeIndex !== index),
    }));
  };

  const saveCorrection = () => {
    const nextAttributes: Record<string, unknown> = {};
    const draftAttributeNames = new Set(draft.attributes.map((attribute) => attribute.key.trim()).filter(Boolean));
    document.attributes.forEach((attribute) => {
      if (!draftAttributeNames.has(attribute.definition.name)) nextAttributes[attribute.definition.name] = "";
    });
    draft.attributes.forEach((attribute) => {
      const key = attribute.key.trim();
      if (key) nextAttributes[key] = attribute.value;
    });
    const year = Number(draft.publication_year);
    updateDocument.mutate({
      title: draft.title.trim() || document.title,
      subtitle: draft.subtitle.trim() || null,
      authors: parseAuthorText(draft.authors),
      publication_year: Number.isFinite(year) && draft.publication_year.trim() ? year : null,
      journal: draft.journal.trim() || null,
      publisher: draft.publisher.trim() || null,
      doi: draft.doi.trim() || null,
      source_url: draft.source_url.trim() || null,
      abstract: draft.abstract.trim() || null,
      rich_summary: draft.rich_summary.trim() || null,
      priority: draft.priority,
      read_status: draft.read_status,
      citation_status: draft.citation_status,
      tag_names: splitCommaList(draft.tag_names),
      domain_ids: draft.domain_ids,
      attribute_values: nextAttributes,
    });
  };
  const saveAnnotation = () => {
    const pageNumber = Number(annotationDraft.page_number);
    createAnnotation.mutate({
      page_number: Number.isFinite(pageNumber) && annotationDraft.page_number.trim() ? pageNumber : null,
      kind: annotationDraft.kind,
      body: annotationDraft.body.trim() || null,
      geometry: {},
      color: annotationDraft.color || null,
    });
  };
  const annotations = document.annotations || [];

  return (
    <aside className={`detail-pane ${readerExpanded ? "reader-detail" : ""}`}>
      <div className="detail-head">
        <div>
          <h2>{document.title}</h2>
          <p>{authorLine(document)}</p>
        </div>
        <div className="detail-status">
          {document.duplicate_count > 0 ? <StatusPill value={`Duplicate ${document.duplicate_count + 1}`} tone="warn" /> : null}
          <StatusPill value={document.priority} tone="blue" />
        </div>
      </div>
      <div className="detail-actions">
        <button className="secondary-button" onClick={() => setEditing((value) => !value)}>
          {editing ? <X size={15} /> : <Edit3 size={15} />}
          {editing ? "Cancel" : "Edit"}
        </button>
        <button className="secondary-button" onClick={() => runConcordance.mutate()} disabled={runConcordance.isPending}>
          <RefreshCw size={15} />
          Concord
        </button>
        {onOpenReader && !readerExpanded ? (
          <button className="secondary-button" onClick={onOpenReader} type="button">
            <BookOpen size={15} />
            Reader
          </button>
        ) : null}
        <button
          className="secondary-button"
          disabled={document.processing_status !== "ready" || !document.doi}
          onClick={() => setRecommendationsOpen((value) => !value)}
          title={!document.doi ? "Recommendations need a DOI" : "View related papers"}
          type="button"
        >
          <Sparkles size={15} />
          Related
        </button>
        {onCloseReader && readerExpanded ? (
          <button className="secondary-button" onClick={onCloseReader} type="button">
            <X size={15} />
            Close reader
          </button>
        ) : null}
        <a className="secondary-button" href={`/api/documents/${document.id}/original`} target="_blank" rel="noreferrer">
          <FileSearch size={15} />
          Open original
        </a>
      </div>
      <div className="reader-tabs" role="tablist" aria-label="Document reader">
        <button className={readerMode === "pdf" ? "selected" : ""} type="button" onClick={() => setReaderMode("pdf")}>
          <FileSearch size={15} />
          PDF
        </button>
        <button className={readerMode === "text" ? "selected" : ""} type="button" onClick={() => setReaderMode("text")}>
          <FileText size={15} />
          Text
        </button>
      </div>
      {readerMode === "pdf" ? (
        <div className="pdf-preview">
          <iframe title={`PDF preview for ${document.title}`} src={`/api/documents/${document.id}/original#toolbar=0&navpanes=0`} />
          <div className="pdf-preview-meta">
            <FileSearch size={16} />
            <span>{document.page_count || "?"} pages</span>
          </div>
        </div>
      ) : (
        <section className="text-reader">
          <div className="text-reader-head">
            <div>
              <strong>Parsed text</strong>
              <span>{pages.length ? `Page ${currentPageIndex + 1} of ${pages.length}` : `${document.page_count || "?"} pages`}</span>
            </div>
            <div className="reader-actions">
              <button
                className="icon-button reader-arrow"
                type="button"
                title="Previous page"
                disabled={!pages.length || currentPageIndex === 0}
                onClick={() => setReaderPageIndex((index) => Math.max(0, index - 1))}
              >
                <ChevronLeft size={18} />
              </button>
              <span className="page-counter">{pages.length ? `${currentPage?.page_number ?? currentPageIndex + 1} / ${pages.length}` : "0 / 0"}</span>
              <button
                className="icon-button reader-arrow"
                type="button"
                title="Next page"
                disabled={!pages.length || currentPageIndex >= pages.length - 1}
                onClick={() => setReaderPageIndex((index) => Math.min(pages.length - 1, index + 1))}
              >
                <ChevronRight size={18} />
              </button>
              {currentPage ? (
                <button className="secondary-button compact" type="button" onClick={() => startPageNote(currentPage.page_number)}>
                  <Bookmark size={14} />
                  Note
                </button>
              ) : null}
              <button className="secondary-button compact" onClick={copyFullText} disabled={!fullText}>
                {copiedKey === "full-text" ? <CheckCircle2 size={14} /> : <Clipboard size={14} />}
                {copiedKey === "full-text" ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
          {currentPage ? (
            <article className={`reader-page ${currentPage.low_text ? "low-text" : ""}`}>
              <header>
                <div>
                  <strong>Page {currentPage.page_number}</strong>
                  <span>
                    {currentPage.normalized_text ? "normalized" : currentPage.text_source}
                    {currentPage.low_text ? " / low text" : ""}
                  </span>
                </div>
              </header>
              <pre>{currentPageText || "No extracted text."}</pre>
            </article>
          ) : (
            <div className="empty-inline">
              <FileText size={17} />
              <span>No parsed pages yet.</span>
            </div>
          )}
        </section>
      )}
      {editing ? (
        <form
          className="document-editor"
          onSubmit={(event) => {
            event.preventDefault();
            saveCorrection();
          }}
        >
          <label>
            Title
            <input value={draft.title} onChange={(event) => setDraftValue("title", event.target.value)} />
          </label>
          <label>
            Subtitle
            <input value={draft.subtitle} onChange={(event) => setDraftValue("subtitle", event.target.value)} />
          </label>
          <label>
            Authors
            <textarea value={draft.authors} onChange={(event) => setDraftValue("authors", event.target.value)} />
          </label>
          <div className="editor-grid">
            <label>
              Year
              <input value={draft.publication_year} inputMode="numeric" onChange={(event) => setDraftValue("publication_year", event.target.value)} />
            </label>
            <label>
              Journal
              <input value={draft.journal} onChange={(event) => setDraftValue("journal", event.target.value)} />
            </label>
          </div>
          <div className="editor-grid">
            <label>
              Publisher
              <input value={draft.publisher} onChange={(event) => setDraftValue("publisher", event.target.value)} />
            </label>
            <label>
              DOI
              <input value={draft.doi} onChange={(event) => setDraftValue("doi", event.target.value)} />
            </label>
          </div>
          <label>
            Source URL
            <input value={draft.source_url} onChange={(event) => setDraftValue("source_url", event.target.value)} />
          </label>
          <div className="editor-grid">
            <label>
              Priority
              <select value={draft.priority} onChange={(event) => setDraftValue("priority", event.target.value)}>
                <option value="urgent">Urgent</option>
                <option value="high">High</option>
                <option value="normal">Normal</option>
                <option value="low">Low</option>
              </select>
            </label>
            <label>
              Read
              <select value={draft.read_status} onChange={(event) => setDraftValue("read_status", event.target.value)}>
                <option value="unread">Unread</option>
                <option value="skimmed">Skimmed</option>
                <option value="read">Read</option>
              </select>
            </label>
          </div>
          <label>
            Citation status
            <select value={draft.citation_status} onChange={(event) => setDraftValue("citation_status", event.target.value)}>
              <option value="needs_review">Needs review</option>
              <option value="verified">Verified</option>
              <option value="rejected">Rejected</option>
            </select>
          </label>
          <label>
            Tags
            <input list={`known-tags-${document.id}`} value={draft.tag_names} onChange={(event) => setDraftValue("tag_names", event.target.value)} />
            <datalist id={`known-tags-${document.id}`}>
              {tags.map((tag) => (
                <option key={tag.id} value={tag.name} />
              ))}
            </datalist>
          </label>
          <div className="editor-block">
            <strong>Domains</strong>
            <div className="compact-checklist">
              {domains.map((domain) => (
                <label key={domain.id}>
                  <input type="checkbox" checked={draft.domain_ids.includes(domain.id)} onChange={() => toggleDomain(domain.id)} />
                  <span>{domain.name}</span>
                </label>
              ))}
            </div>
          </div>
          <label>
            Abstract
            <textarea value={draft.abstract} onChange={(event) => setDraftValue("abstract", event.target.value)} />
          </label>
          <label>
            Summary
            <textarea value={draft.rich_summary} onChange={(event) => setDraftValue("rich_summary", event.target.value)} />
          </label>
          <div className="editor-block">
            <div className="editor-block-head">
              <strong>Attributes</strong>
              <button
                className="secondary-button compact"
                type="button"
                onClick={() => setDraftValue("attributes", [...draft.attributes, { key: "", value: "" }])}
              >
                <Plus size={14} />
                Add
              </button>
            </div>
            <div className="attribute-editor-list">
              {draft.attributes.map((attribute, index) => (
                <div key={`${attribute.key}-${index}`} className="attribute-editor-row">
                  <input placeholder="Name" value={attribute.key} onChange={(event) => updateAttribute(index, "key", event.target.value)} />
                  <input placeholder="Value" value={attribute.value} onChange={(event) => updateAttribute(index, "value", event.target.value)} />
                  <button className="icon-button" type="button" title="Remove attribute" onClick={() => removeAttribute(index)}>
                    <Trash2 size={15} />
                  </button>
                </div>
              ))}
            </div>
          </div>
          <button className="primary-button" type="submit" disabled={updateDocument.isPending}>
            <Save size={15} />
            Save correction
          </button>
          {saveError ? <p className="form-error">{saveError}</p> : null}
        </form>
      ) : null}
      <section className="detail-section">
        <h3>APA</h3>
        <MarkdownBlock content={document.apa_citation} empty="Needs review." />
        <div className="citation-actions">
          <button className="secondary-button" onClick={copyCitation} disabled={!document.apa_citation}>
            {copiedKey === "citation" ? <CheckCircle2 size={15} /> : <Clipboard size={15} />}
            {copiedKey === "citation" ? "Copied" : "Copy"}
          </button>
          <button className="secondary-button" onClick={() => refreshCitation.mutate()} disabled={citationBusy}>
            <RefreshCw className={citationBusy ? "spin" : ""} size={15} />
            {citationBusy ? "Checking" : "Check"}
          </button>
        </div>
      </section>
      {recommendationsOpen ? <RecommendationsPanel document={document} /> : null}
      <section className="detail-section">
        <h3>Summary</h3>
        <MarkdownBlock content={document.rich_summary} empty="Summary pending." />
      </section>
      <section className="detail-section">
        <h3>Annotations</h3>
        <form
          className="annotation-composer"
          onSubmit={(event) => {
            event.preventDefault();
            saveAnnotation();
          }}
        >
          <select
            value={annotationDraft.kind}
            onChange={(event) => setAnnotationDraft((current) => ({ ...current, kind: event.target.value }))}
          >
            <option value="highlight">Highlight</option>
            <option value="note">Note</option>
            <option value="reminder">Reminder</option>
          </select>
          <input
            inputMode="numeric"
            placeholder="Page"
            value={annotationDraft.page_number}
            onChange={(event) => setAnnotationDraft((current) => ({ ...current, page_number: event.target.value }))}
          />
          <input
            type="color"
            title="Annotation color"
            value={annotationDraft.color}
            onChange={(event) => setAnnotationDraft((current) => ({ ...current, color: event.target.value }))}
          />
          <textarea
            placeholder="Annotation note"
            value={annotationDraft.body}
            onChange={(event) => setAnnotationDraft((current) => ({ ...current, body: event.target.value }))}
          />
          <button className="primary-button" type="submit" disabled={createAnnotation.isPending || !annotationDraft.body.trim()}>
            <Plus size={15} />
            Add
          </button>
        </form>
        {annotations.length ? (
          <div className="annotation-list">
            {annotations.map((annotation) => (
              <article key={annotation.id}>
                <span className="annotation-swatch" style={{ backgroundColor: annotation.color || "#f6c343" }} />
                <div>
                  <strong>
                    {annotation.kind}
                    {annotation.page_number ? ` / page ${annotation.page_number}` : ""}
                  </strong>
                  <p>{annotation.body || "No note body"}</p>
                </div>
                <button
                  className="icon-button"
                  title="Delete annotation"
                  onClick={() => deleteAnnotation.mutate(annotation.id)}
                  disabled={deleteAnnotation.isPending}
                >
                  <Trash2 size={15} />
                </button>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-inline">
            <Bookmark size={17} />
            <span>No annotations yet.</span>
          </div>
        )}
      </section>
      <section className="detail-section">
        <h3>Figures</h3>
        {document.figures.length ? (
          <div className="figure-grid">
            {document.figures.map((figure) => (
              <a key={figure.id} href={`/api/figures/${figure.id}/asset`} target="_blank" rel="noreferrer">
                <img alt={figure.figure_label || "Extracted figure"} src={`/api/figures/${figure.id}/asset`} />
                <span>{figure.figure_label || `Page ${figure.page_number || "?"}`}</span>
                <small>{figure.gist || figure.caption || "Extracted figure"}</small>
              </a>
            ))}
          </div>
        ) : (
          <div className="empty-inline">
            <Image size={17} />
            <span>No extracted figures yet.</span>
          </div>
        )}
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
        <h3>Domains</h3>
        <div className="tag-cloud">
          {document.domains.map((domain) => (
            <span key={domain.id}>{domain.name}</span>
          ))}
        </div>
      </section>
      <section className="detail-section">
        <h3>Attributes</h3>
        {document.attributes.length ? (
          <div className="attribute-list">
            {document.attributes.map((attribute) => (
              <div key={attribute.id}>
                <strong>{attribute.definition.name}</strong>
                <span>{attributeDisplayValue(attribute.value)}</span>
              </div>
            ))}
          </div>
        ) : (
          <p>No custom attributes.</p>
        )}
      </section>
      <section className="detail-section">
        <h3>History</h3>
        {document.versions.slice(0, 4).map((version) => (
          <div key={version.id} className="history-row">
            <strong>v{version.version_number}</strong>
            <span>{version.change_note || "Snapshot"}</span>
          </div>
        ))}
      </section>
      <section className="detail-section">
        <h3>Evidence</h3>
        <pre>{JSON.stringify(decodeHtmlEntitiesDeep(document.metadata_evidence), null, 2)}</pre>
      </section>
    </aside>
  );
}

type ImportPickerItem = {
  id: string;
  name: string;
  meta?: string;
};

function ImportDefaultPicker({
  title,
  hint,
  items,
  selectedIds,
  onChange,
  createLabel,
  onCreate,
}: {
  title: string;
  hint: string;
  items: ImportPickerItem[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  createLabel: string;
  onCreate?: (name: string) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [createName, setCreateName] = useState("");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);
  const selected = items.filter((item) => selectedIds.includes(item.id));
  const normalizedQuery = query.trim().toLowerCase();
  const options = items
    .filter((item) => !selectedIds.includes(item.id))
    .filter((item) => {
      if (!normalizedQuery) return true;
      return [item.name, item.meta].filter(Boolean).join(" ").toLowerCase().includes(normalizedQuery);
    })
    .slice(0, 12);
  const canCreate = Boolean(onCreate && createName.trim());

  const addItem = (id: string) => onChange(uniqueValues([...selectedIds, id]));
  const removeItem = (id: string) => onChange(selectedIds.filter((selectedId) => selectedId !== id));
  const handleCreate = async () => {
    if (!onCreate || !createName.trim()) return;
    setCreating(true);
    setCreateError("");
    try {
      await onCreate(createName.trim());
      setCreateName("");
      setQuery("");
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : "Could not create item");
    } finally {
      setCreating(false);
    }
  };

  return (
    <section className="import-picker">
      <div className="import-picker-head">
        <div>
          <h3>{title}</h3>
          <p>{hint}</p>
        </div>
        {selectedIds.length ? (
          <button className="text-button" type="button" onClick={() => onChange([])}>
            Clear
          </button>
        ) : null}
      </div>
      <div className="selected-chips" aria-label={`${title} selected defaults`}>
        {selected.length ? (
          selected.map((item) => (
            <button key={item.id} type="button" onClick={() => removeItem(item.id)} title={`Remove ${item.name}`}>
              <span>{item.name}</span>
              <X size={13} />
            </button>
          ))
        ) : (
          <span>No default</span>
        )}
      </div>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Find ${title.toLowerCase()}`} />
      <div className="picker-options">
        {options.map((item) => (
          <button key={item.id} type="button" onClick={() => addItem(item.id)}>
            <span>{item.name}</span>
            {item.meta ? <small>{item.meta}</small> : null}
          </button>
        ))}
        {!options.length ? <span className="picker-empty">No matches</span> : null}
      </div>
      {onCreate ? (
        <div className="inline-create">
          <input value={createName} onChange={(event) => setCreateName(event.target.value)} placeholder={createLabel} />
          <button className="secondary-button" disabled={!canCreate || creating} onClick={handleCreate} type="button">
            <Plus size={14} />
            Add
          </button>
        </div>
      ) : null}
      {createError ? <p className="field-error">{createError}</p> : null}
    </section>
  );
}

function domainPickerItems(domains: Domain[]): ImportPickerItem[] {
  const byId = new Map(domains.map((domain) => [domain.id, domain]));
  const labelFor = (domain: Domain): string => {
    const parents: string[] = [];
    let current: Domain | undefined = domain;
    while (current) {
      parents.unshift(current.name);
      current = current.parent_id ? byId.get(current.parent_id) : undefined;
    }
    return parents.join(" / ");
  };
  return domains
    .map((domain) => ({ id: domain.id, name: labelFor(domain), meta: `${domain.document_count} documents` }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

function ImportView({ jobs, domains, tags, projects }: { jobs: ImportJob[]; domains: Domain[]; tags: Tag[]; projects: Project[] }) {
  const [batchLabel, setBatchLabel] = useState("");
  const [priority, setPriority] = useState("normal");
  const [readStatus, setReadStatus] = useState("unread");
  const [selectedDomainIds, setSelectedDomainIds] = useState<string[]>([]);
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([]);
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
  const [dragDepth, setDragDepth] = useState(0);
  const [dropMessage, setDropMessage] = useState("Ready");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [duplicateCheck, setDuplicateCheck] = useState<ImportDuplicateCheck | null>(null);
  const queryClient = useQueryClient();
  const sortedTags = useMemo(() => [...tags].sort((left, right) => left.name.localeCompare(right.name)), [tags]);
  const sortedProjects = useMemo(() => [...projects].sort((left, right) => left.name.localeCompare(right.name)), [projects]);
  const domainItems = useMemo(() => domainPickerItems(domains), [domains]);
  const tagItems = useMemo<ImportPickerItem[]>(
    () => sortedTags.map((tag) => ({ id: tag.id, name: tag.name, meta: tag.kind })),
    [sortedTags],
  );
  const projectItems = useMemo<ImportPickerItem[]>(
    () => sortedProjects.map((project) => ({ id: project.id, name: project.name, meta: `${project.item_count} resources` })),
    [sortedProjects],
  );
  const selectedDefaultCount = selectedDomainIds.length + selectedTagIds.length + selectedProjectIds.length;
  const importDefaults = () => ({
    label: batchLabel.trim(),
    priority,
    read_status: readStatus,
    domain_ids: selectedDomainIds,
    tag_ids: selectedTagIds,
    project_ids: selectedProjectIds,
  });
  const createAndSelectDomain = async (name: string) => {
    const existing = domains.find((domain) => domain.name.toLowerCase() === name.toLowerCase() && !domain.parent_id);
    const domain = existing || (await api.createDomain(name));
    setSelectedDomainIds((current) => uniqueValues([...current, domain.id]));
    void queryClient.invalidateQueries({ queryKey: ["domains"] });
  };
  const createAndSelectTag = async (name: string) => {
    const existing = tags.find((tag) => tag.name.toLowerCase() === name.toLowerCase());
    const tag = existing || (await api.createTag(name));
    setSelectedTagIds((current) => uniqueValues([...current, tag.id]));
    void queryClient.invalidateQueries({ queryKey: ["tags"] });
  };
  const createAndSelectProject = async (name: string) => {
    const existing = projects.find((project) => project.name.toLowerCase() === name.toLowerCase());
    const project = existing || (await api.createProject(name));
    setSelectedProjectIds((current) => uniqueValues([...current, project.id]));
    void queryClient.invalidateQueries({ queryKey: ["projects"] });
  };
  const upload = useMutation({
    mutationFn: ({ incomingFiles, strategy }: { incomingFiles: File[]; strategy: DuplicateImportStrategy }) =>
      api.uploadBatch(incomingFiles, { ...importDefaults(), duplicate_strategy: strategy }),
    onMutate: ({ incomingFiles }) => {
      setDuplicateCheck(null);
      setPendingFiles([]);
      setDropMessage(`Importing ${incomingFiles.length} PDF${incomingFiles.length === 1 ? "" : "s"}`);
    },
    onSuccess: (_batch, { incomingFiles }) => {
      setDropMessage(`Queued ${incomingFiles.length} PDF${incomingFiles.length === 1 ? "" : "s"}`);
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => {
      setDropMessage(error instanceof Error ? error.message : "Import failed");
    },
  });
  const duplicatePreflight = useMutation({
    mutationFn: (incomingFiles: File[]) => api.checkImportDuplicates(incomingFiles),
    onMutate: (incomingFiles) => {
      setDuplicateCheck(null);
      setPendingFiles(incomingFiles);
      setDropMessage(`Checking ${incomingFiles.length} PDF${incomingFiles.length === 1 ? "" : "s"}`);
    },
    onSuccess: (result, incomingFiles) => {
      if (result.duplicate_file_count > 0) {
        setDuplicateCheck(result);
        setPendingFiles(incomingFiles);
        setDropMessage(`${result.duplicate_file_count} duplicate ${result.duplicate_file_count === 1 ? "file" : "files"} found`);
        return;
      }
      upload.mutate({ incomingFiles, strategy: "skip" });
    },
    onError: (error) => {
      setDuplicateCheck(null);
      setPendingFiles([]);
      setDropMessage(error instanceof Error ? error.message : "Duplicate check failed");
    },
  });
  const rescueJob = useMutation({
    mutationFn: (jobId: string) => api.rescueImportJob(jobId),
    onSuccess: () => {
      setDropMessage("Import job requeued");
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => {
      setDropMessage(error instanceof Error ? error.message : "Could not rescue import job");
    },
  });
  const isDraggingFiles = dragDepth > 0;
  const importBusy = upload.isPending || duplicatePreflight.isPending;
  const duplicateFiles = duplicateCheck?.files.filter((file) => file.duplicate_in_upload || file.existing_documents.length > 0) || [];

  const hasDraggedFiles = (event: DragEvent<HTMLElement>) => Array.from(event.dataTransfer.types).includes("Files");
  const importFiles = (incomingFiles: FileList | File[]) => {
    const allFiles = Array.from(incomingFiles);
    const pdfs = allFiles.filter((file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"));
    if (importBusy) {
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
    duplicatePreflight.mutate(pdfs);
  };
  const applyDuplicateStrategy = (strategy: DuplicateImportStrategy) => {
    if (!pendingFiles.length) return;
    upload.mutate({ incomingFiles: pendingFiles, strategy });
  };

  return (
    <section className="workbench">
      <div
        className={`dropzone${isDraggingFiles ? " active" : ""}${importBusy ? " uploading" : ""}`}
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
          <strong>{isDraggingFiles ? "Release to check" : importBusy ? "Working" : "Drop PDFs"}</strong>
          <span className="dropzone-hint">{isDraggingFiles ? "PDFs will be checked for duplicates" : "or click anywhere"}</span>
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
      {duplicateCheck ? (
        <section className="duplicate-panel">
          <div>
            <h2>Duplicate files</h2>
            <p>{duplicateFiles.length} exact checksum {duplicateFiles.length === 1 ? "match" : "matches"} need a decision.</p>
          </div>
          <div className="duplicate-list">
            {duplicateFiles.slice(0, 8).map((file, index) => (
              <div key={`${file.checksum_sha256}-${file.filename}-${index}`} className="duplicate-row">
                <span>
                  <strong>{file.filename}</strong>
                  <small>
                    {formatFileSize(file.file_size_bytes)}
                    {file.duplicate_in_upload ? " / duplicate in this drop" : ""}
                    {file.existing_documents.length ? ` / matches ${file.existing_documents[0].title}` : ""}
                  </small>
                </span>
                <StatusPill value={file.existing_documents.length ? "In library" : "In batch"} tone="warn" />
              </div>
            ))}
          </div>
          <div className="duplicate-actions">
            <button className="secondary-button" disabled={upload.isPending} onClick={() => applyDuplicateStrategy("skip")} type="button">
              <X size={15} />
              Skip duplicates
            </button>
            <button className="secondary-button" disabled={upload.isPending} onClick={() => applyDuplicateStrategy("overwrite")} type="button">
              <RefreshCw size={15} />
              Overwrite
            </button>
            <button className="primary-button" disabled={upload.isPending} onClick={() => applyDuplicateStrategy("import_anyway")} type="button">
              <Plus size={15} />
              Import anyway
            </button>
          </div>
        </section>
      ) : null}
      <section className="import-defaults">
        <div className="import-defaults-head">
          <div>
            <h2>Apply to this batch</h2>
            <p>
              Defaults are optional. Selected domains, tags, projects, priority, and read state will be applied to every queued PDF.
            </p>
          </div>
          <StatusPill value={selectedDefaultCount ? `${selectedDefaultCount} defaults` : "No organization defaults"} tone={selectedDefaultCount ? "blue" : "neutral"} />
        </div>
        <div className="import-default-controls">
          <label>
            Batch label
            <input value={batchLabel} onChange={(event) => setBatchLabel(event.target.value)} placeholder="Optional import label" />
          </label>
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
        </div>
        <div className="import-picker-grid">
          <ImportDefaultPicker
            createLabel="New top-level domain"
            hint="Select knowledge domains or add a new top-level domain."
            items={domainItems}
            onChange={setSelectedDomainIds}
            onCreate={createAndSelectDomain}
            selectedIds={selectedDomainIds}
            title="Domains"
          />
          <ImportDefaultPicker
            createLabel="New tag"
            hint="Apply known keywords or create a tag before dropping files."
            items={tagItems}
            onChange={setSelectedTagIds}
            onCreate={createAndSelectTag}
            selectedIds={selectedTagIds}
            title="Tags"
          />
          <ImportDefaultPicker
            createLabel="New project"
            hint="Attach imports to run sheets as candidate resources."
            items={projectItems}
            onChange={setSelectedProjectIds}
            onCreate={createAndSelectProject}
            selectedIds={selectedProjectIds}
            title="Projects"
          />
        </div>
      </section>
      <section className="job-list">
        <h2>Processing</h2>
        {jobs.slice(0, 20).map((job) => (
          <div key={job.id} className="job-row">
            <span className="job-copy">
              <span>{importJobLabel(job)}</span>
              <small>{importJobStepLabel(job)}</small>
            </span>
            <span className="job-actions">
              <StatusPill value={job.status} tone={job.status === "failed" ? "warn" : job.status === "complete" ? "good" : "blue"} />
              {canRescueImportJob(job) ? (
                <button
                  className="icon-button compact"
                  disabled={rescueJob.isPending}
                  onClick={() => rescueJob.mutate(job.id)}
                  title="Requeue this import job"
                  type="button"
                >
                  <RefreshCw size={15} />
                </button>
              ) : null}
            </span>
          </div>
        ))}
      </section>
    </section>
  );
}

function ProjectItemRow({ item, projectId }: { item: ProjectItem; projectId: string }) {
  const [note, setNote] = useState(item.note || "");
  const queryClient = useQueryClient();
  useEffect(() => {
    setNote(item.note || "");
  }, [item.note]);
  const update = useMutation({
    mutationFn: (body: Partial<ProjectItem>) => api.updateProjectItem(projectId, item.id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteProjectItem(projectId, item.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });
  const title = item.document?.title || "Untitled resource";

  return (
    <article className="project-resource-row">
      <div className="resource-title">
        <strong>{title}</strong>
        {item.document?.apa_citation ? (
          <MarkdownBlock compact content={item.document.apa_citation} empty="No citation yet." />
        ) : (
          <span>{item.document?.original_filename || "No citation yet"}</span>
        )}
      </div>
      <select value={item.status} onChange={(event) => update.mutate({ status: event.target.value })}>
        <option value="candidate">Candidate</option>
        <option value="reading">Reading</option>
        <option value="used">Used</option>
        <option value="rejected">Rejected</option>
      </select>
      <select value={item.priority} onChange={(event) => update.mutate({ priority: event.target.value })}>
        <option value="urgent">Urgent</option>
        <option value="high">High</option>
        <option value="normal">Normal</option>
        <option value="low">Low</option>
      </select>
      <label className="used-toggle">
        <input
          type="checkbox"
          checked={item.used_in_output}
          onChange={(event) => update.mutate({ used_in_output: event.target.checked, status: event.target.checked ? "used" : item.status })}
        />
        <span>Used</span>
      </label>
      <input
        value={note}
        onChange={(event) => setNote(event.target.value)}
        onBlur={() => {
          if (note !== (item.note || "")) update.mutate({ note });
        }}
        placeholder="Run-sheet note"
      />
      <button className="icon-button" title="Remove from project" onClick={() => remove.mutate()} disabled={remove.isPending}>
        <Trash2 size={15} />
      </button>
    </article>
  );
}

function ProjectsView({ projects, documents }: { projects: Project[]; documents: DocumentSummary[] }) {
  const [name, setName] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [addDocumentId, setAddDocumentId] = useState("");
  const [bibliography, setBibliography] = useState<Bibliography | null>(null);
  const [bibliographyStyle, setBibliographyStyle] = useState<"apa" | "bibtex" | "ris" | "csl_json">("apa");
  const { copiedKey, copyToClipboard } = useClipboardNotice();
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!selectedProjectId && projects[0]) setSelectedProjectId(projects[0].id);
  }, [projects, selectedProjectId]);
  const selectedProject = useQuery({
    queryKey: ["project", selectedProjectId],
    queryFn: () => api.project(selectedProjectId),
    enabled: Boolean(selectedProjectId),
  });
  const create = useMutation({
    mutationFn: () => api.createProject(name),
    onSuccess: (project) => {
      setName("");
      setSelectedProjectId(project.id);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  const addItem = useMutation({
    mutationFn: () => api.addProjectItems(selectedProjectId, [addDocumentId]),
    onSuccess: () => {
      setAddDocumentId("");
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({ queryKey: ["project", selectedProjectId] });
    },
  });
  const generateBibliography = async (usedOnly: boolean) => {
    if (!selectedProjectId) return;
    setBibliography(await api.bibliography(selectedProjectId, usedOnly));
    setBibliographyStyle("apa");
  };
  const current = selectedProject.data;
  const currentDocumentIds = new Set((current?.items || []).map((item) => item.document_id));
  const availableDocuments = documents.filter((document) => !currentDocumentIds.has(document.id));
  const bibliographyText =
    bibliographyStyle === "csl_json"
      ? JSON.stringify(bibliography?.csl_json || [], null, 2)
      : bibliography
        ? bibliography[bibliographyStyle]
        : "";

  return (
    <section className="workbench project-workbench">
      <aside className="project-sidebar">
        <div className="inline-form">
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="New project" />
          <button className="primary-button" disabled={!name} onClick={() => create.mutate()}>
            <Plus size={16} />
            Add
          </button>
        </div>
        <div className="project-list">
          {projects.map((project) => (
            <button
              key={project.id}
              className={project.id === selectedProjectId ? "selected" : ""}
              onClick={() => {
                setSelectedProjectId(project.id);
                setBibliography(null);
              }}
            >
              <strong>{project.name}</strong>
              <span>{project.item_count} resources</span>
            </button>
          ))}
        </div>
      </aside>
      <section className="project-detail">
        <div className="panel-title-row">
          <div>
            <h2>{current?.name || "Select a project"}</h2>
            <span>{current ? `${current.item_count} resources / ${current.status}` : "Run sheets track resource use for a paper or assignment."}</span>
          </div>
          <div className="project-actions">
            <button className="secondary-button" disabled={!current} onClick={() => void generateBibliography(false)}>
              <Clipboard size={16} />
              All sources
            </button>
            <button className="primary-button" disabled={!current} onClick={() => void generateBibliography(true)}>
              <CheckSquare size={16} />
              Used only
            </button>
          </div>
        </div>
        {current ? (
          <>
            <div className="project-add-row">
              <select value={addDocumentId} onChange={(event) => setAddDocumentId(event.target.value)}>
                <option value="">Add a library document</option>
                {availableDocuments.map((document) => (
                  <option key={document.id} value={document.id}>
                    {document.title}
                  </option>
                ))}
              </select>
              <button className="secondary-button" disabled={!addDocumentId || addItem.isPending} onClick={() => addItem.mutate()}>
                <Plus size={16} />
                Add resource
              </button>
            </div>
            <div className="project-resource-list">
              {(current.items || []).map((item) => (
                <ProjectItemRow key={item.id} item={item} projectId={current.id} />
              ))}
              {!current.items.length ? <div className="empty-inline">No resources in this run sheet yet.</div> : null}
            </div>
          </>
        ) : (
          <div className="empty-inline">Create or select a project to build its run sheet.</div>
        )}
      </section>
      <section className="bibliography-panel">
        <div className="panel-title-row">
          <div>
            <h2>Bibliography</h2>
            <span>{bibliography ? "Generated from current run sheet" : "Generate all sources or used-only sources"}</span>
          </div>
          <button
            className="secondary-button"
            disabled={!bibliographyText}
            onClick={() => {
              void copyToClipboard("bibliography", decodeHtmlEntities(bibliographyText));
            }}
          >
            {copiedKey === "bibliography" ? <CheckCircle2 size={16} /> : <Clipboard size={16} />}
            {copiedKey === "bibliography" ? "Copied" : "Copy"}
          </button>
        </div>
        <div className="bibliography-tabs">
          {(["apa", "bibtex", "ris", "csl_json"] as const).map((style) => (
            <button
              key={style}
              className={style === bibliographyStyle ? "selected" : ""}
              onClick={() => setBibliographyStyle(style)}
              disabled={!bibliography}
            >
              {style.replace("_", " ").toUpperCase()}
            </button>
          ))}
        </div>
        <pre className="bibliography">{bibliographyText || "No bibliography generated yet."}</pre>
      </section>
    </section>
  );
}

function QueueView({ items, jobs }: { items: CitationCandidate[]; jobs: ImportJob[] }) {
  const queryClient = useQueryClient();
  const updateCandidate = useMutation({
    mutationFn: ({ id, status, apply }: { id: string; status: string; apply?: boolean }) =>
      api.updateCitationCandidate(id, { status, apply_to_document: Boolean(apply) }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["review"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document"] });
    },
  });
  const rescueJob = useMutation({
    mutationFn: (jobId: string) => api.rescueImportJob(jobId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
  const queueJobs = jobs.filter((job) => ["queued", "running", "failed", "restored_paused"].includes(job.status));

  return (
    <section className="workbench queue-workbench">
      <section className="queue-panel">
        <div className="panel-title-row">
          <div>
            <h2>Import Queue</h2>
            <span>{queueJobs.length ? `${queueJobs.length} active or waiting` : "No import jobs waiting"}</span>
          </div>
          <ListTodo size={20} />
        </div>
        <div className="queue-job-list">
          {queueJobs.map((job) => {
            const progress = importJobProgress(job);
            return (
              <div key={job.id} className="queue-job-row">
                <span className="job-copy">
                  <span>{importJobLabel(job)}</span>
                  <small>{importJobStepLabel(job)}</small>
                </span>
                <span className="queue-job-status">
                  <StatusPill value={job.status} tone={job.status === "failed" ? "warn" : job.status === "complete" ? "good" : "blue"} />
                  {canRescueImportJob(job) ? (
                    <button
                      className="icon-button compact"
                      disabled={rescueJob.isPending}
                      onClick={() => rescueJob.mutate(job.id)}
                      title="Requeue this import job"
                      type="button"
                    >
                      <RefreshCw size={15} />
                    </button>
                  ) : null}
                </span>
                <span
                  aria-label={`${importJobStage(job)}: ${progress}%`}
                  aria-valuemax={100}
                  aria-valuemin={0}
                  aria-valuenow={progress}
                  className="queue-job-progress"
                  role="progressbar"
                  title={`${importJobStage(job)}: ${progress}%`}
                >
                  <span style={{ width: `${progress}%` }} />
                </span>
              </div>
            );
          })}
          {!queueJobs.length ? <p className="empty-note">The import queue is clear.</p> : null}
        </div>
      </section>
      <section className="queue-panel">
        <div className="panel-title-row">
          <div>
            <h2>Citation Review</h2>
            <span>{items.length ? `${items.length} candidates need review` : "No citation candidates waiting"}</span>
          </div>
          <FileSearch size={20} />
        </div>
        <div className="review-list">
          {items.map((item) => (
            <article key={item.id}>
              <div>
                <strong>{String(item.metadata.title || "Untitled")}</strong>
                <span>{item.source}</span>
              </div>
              <MarkdownBlock content={item.citation_text} empty="No candidate citation." />
              <div className="review-actions">
                <StatusPill value={item.status} tone="warn" />
                <button
                  className="primary-button"
                  disabled={updateCandidate.isPending}
                  onClick={() => updateCandidate.mutate({ id: item.id, status: "accepted", apply: true })}
                >
                  <CheckCircle2 size={16} />
                  Accept
                </button>
                <button
                  className="secondary-button"
                  disabled={updateCandidate.isPending}
                  onClick={() => updateCandidate.mutate({ id: item.id, status: "rejected" })}
                >
                  <X size={16} />
                  Reject
                </button>
              </div>
            </article>
          ))}
          {!items.length ? <p className="empty-note">Citation review is clear.</p> : null}
        </div>
      </section>
    </section>
  );
}

function NotesView({
  notes,
  documents,
  domains,
  projects,
}: {
  notes: Note[];
  documents: DocumentSummary[];
  domains: Domain[];
  projects: Project[];
}) {
  const [draft, setDraft] = useState<NotePayload>({ title: "", body: "", kind: "note" });
  const queryClient = useQueryClient();
  const createNote = useMutation({
    mutationFn: () =>
      api.createNote({
        ...draft,
        title: draft.title.trim(),
        body: draft.body.trim(),
        document_id: draft.document_id || null,
        domain_id: draft.domain_id || null,
        project_id: draft.project_id || null,
        reminder_at: draft.reminder_at || null,
      }),
    onSuccess: () => {
      setDraft({ title: "", body: "", kind: "note" });
      void queryClient.invalidateQueries({ queryKey: ["notes"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document"] });
    },
  });
  const deleteNote = useMutation({
    mutationFn: (id: string) => api.deleteNote(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["notes"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document"] });
    },
  });
  const setDraftValue = <K extends keyof NotePayload>(key: K, value: NotePayload[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };
  const linkedLabel = (note: Note) => {
    if (note.document_id) return documents.find((document) => document.id === note.document_id)?.title || "Document";
    if (note.domain_id) return domains.find((domain) => domain.id === note.domain_id)?.name || "Domain";
    if (note.project_id) return projects.find((project) => project.id === note.project_id)?.name || "Project";
    return "Library";
  };

  return (
    <section className="workbench notes-workbench">
      <form
        className="note-composer"
        onSubmit={(event) => {
          event.preventDefault();
          if (draft.title?.trim() && draft.body?.trim()) createNote.mutate();
        }}
      >
        <div className="inline-form">
          <input value={draft.title} onChange={(event) => setDraftValue("title", event.target.value)} placeholder="Note title" />
          <button className="primary-button" disabled={!draft.title?.trim() || !draft.body?.trim() || createNote.isPending} type="submit">
            <Plus size={16} />
            Add
          </button>
        </div>
        <textarea value={draft.body} onChange={(event) => setDraftValue("body", event.target.value)} placeholder="Note body" />
        <div className="note-link-grid">
          <label>
            Kind
            <select value={draft.kind || "note"} onChange={(event) => setDraftValue("kind", event.target.value)}>
              <option value="note">Note</option>
              <option value="reminder">Reminder</option>
              <option value="question">Question</option>
              <option value="idea">Idea</option>
            </select>
          </label>
          <label>
            Document
            <select value={draft.document_id || ""} onChange={(event) => setDraftValue("document_id", event.target.value || null)}>
              <option value="">No document</option>
              {documents.map((document) => (
                <option key={document.id} value={document.id}>
                  {document.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            Domain
            <select value={draft.domain_id || ""} onChange={(event) => setDraftValue("domain_id", event.target.value || null)}>
              <option value="">No domain</option>
              {domains.map((domain) => (
                <option key={domain.id} value={domain.id}>
                  {domain.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Project
            <select value={draft.project_id || ""} onChange={(event) => setDraftValue("project_id", event.target.value || null)}>
              <option value="">No project</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Reminder
            <input
              type="datetime-local"
              value={draft.reminder_at || ""}
              onChange={(event) => setDraftValue("reminder_at", event.target.value || null)}
            />
          </label>
        </div>
      </form>
      <div className="notes-list">
        {notes.map((note) => (
          <article key={note.id}>
            <div className="note-head">
              <div>
                <strong>{note.title}</strong>
                <span>
                  {note.kind} / {linkedLabel(note)}
                </span>
              </div>
              <button className="icon-button" title="Delete note" onClick={() => deleteNote.mutate(note.id)}>
                <Trash2 size={15} />
              </button>
            </div>
            <p>{note.body}</p>
            {note.reminder_at ? <StatusPill value={new Date(note.reminder_at).toLocaleString()} tone="warn" /> : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function sameStringMap(left: Record<string, string>, right: Record<string, string>) {
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  for (const key of keys) {
    if ((left[key] || "") !== (right[key] || "")) return false;
  }
  return true;
}

function InfoPopup({ text }: { text: string }) {
  return (
    <span className="info-popover" tabIndex={0}>
      <Info size={14} aria-hidden="true" />
      <span role="tooltip">{text}</span>
    </span>
  );
}

function ModelSelect({
  value,
  options,
  defaultModel,
  onChange,
}: {
  value: string;
  options: string[];
  defaultModel: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const uniqueOptions = Array.from(new Set([value, defaultModel, ...options].filter(Boolean)));

  return (
    <div
      className="model-select"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
      <button className="model-select-trigger" type="button" onClick={() => setOpen((current) => !current)}>
        <span>{value}</span>
        <ChevronRight size={14} aria-hidden="true" />
      </button>
      {open ? (
        <div className="model-options" role="listbox">
          {uniqueOptions.map((option) => (
            <button
              aria-selected={option === value}
              className={option === value ? "selected" : ""}
              key={option}
              onClick={() => {
                onChange(option);
                setOpen(false);
              }}
              role="option"
              type="button"
            >
              <span>{option}</span>
              {option === defaultModel ? <span className="model-default-marker">(Default)</span> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SettingsView({
  capabilities,
  runs,
  jobs,
  preferences,
  domains,
  projects,
  savedSearches,
  selectedDocument,
  query,
}: {
  capabilities: ConcordanceCapability[];
  runs: ConcordanceRun[];
  jobs: ConcordanceJob[];
  preferences?: AppPreferences;
  domains: Domain[];
  projects: Project[];
  savedSearches: SavedSearch[];
  selectedDocument?: DocumentDetail;
  query: string;
}) {
  const [force, setForce] = useState(false);
  const [scopeType, setScopeType] = useState<"library" | "documents" | "search" | "saved_search" | "domain" | "project">("library");
  const [domainId, setDomainId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [savedSearchId, setSavedSearchId] = useState("");
  const [importWorkerConcurrency, setImportWorkerConcurrency] = useState(preferences?.import_worker_concurrency || 4);
  const [accentColorDay, setAccentColorDay] = useState(preferences?.accent_color_day || "#2563eb");
  const [accentColorNight, setAccentColorNight] = useState(preferences?.accent_color_night || "#6ea8ff");
  const [documentCacheSizeMb, setDocumentCacheSizeMb] = useState(preferences?.document_cache_size_mb || 1000);
  const [analysisModels, setAnalysisModels] = useState<Record<string, string>>(preferences?.analysis_models || {});
  const [selectedCapabilityKeys, setSelectedCapabilityKeys] = useState<string[]>([]);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (preferences) {
      setImportWorkerConcurrency(preferences.import_worker_concurrency);
      setAccentColorDay(preferences.accent_color_day);
      setAccentColorNight(preferences.accent_color_night);
      setDocumentCacheSizeMb(preferences.document_cache_size_mb);
      setAnalysisModels(preferences.analysis_models);
    }
  }, [preferences]);

  useEffect(() => {
    setSelectedCapabilityKeys((current) => (current.length ? current : capabilities.map((capability) => capability.key)));
  }, [capabilities]);

  const scopeData = () => {
    if (scopeType === "documents") return { document_ids: selectedDocument ? [selectedDocument.id] : [] };
    if (scopeType === "search") return { query };
    if (scopeType === "saved_search") return { saved_search_id: savedSearchId };
    if (scopeType === "domain") return { domain_id: domainId };
    if (scopeType === "project") return { project_id: projectId };
    return {};
  };
  const scopeReady =
    scopeType === "library" ||
    (scopeType === "documents" && Boolean(selectedDocument)) ||
    (scopeType === "search" && Boolean(query.trim())) ||
    (scopeType === "saved_search" && Boolean(savedSearchId)) ||
    (scopeType === "domain" && Boolean(domainId)) ||
    (scopeType === "project" && Boolean(projectId));
  const createRun = useMutation({
    mutationFn: () =>
      api.createConcordanceRun({
        label: `${scopeType.replace("_", " ")} Concordance`,
        scope_type: scopeType,
        scope_data: scopeData(),
        capability_keys: selectedCapabilityKeys,
        force,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-jobs"] });
    },
  });
  const savePreferences = useMutation({
    mutationFn: () =>
      api.updatePreferences({
        import_worker_concurrency: importWorkerConcurrency,
        accent_color_day: accentColorDay,
        accent_color_night: accentColorNight,
        document_cache_size_mb: documentCacheSizeMb,
        analysis_models: analysisModels,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["preferences"] });
    },
  });
  const latestRun = runs[0];
  const activeJobs = jobs.filter((job) => job.status === "queued" || job.status === "running").length;
  const progressTotal = latestRun?.total_jobs || 0;
  const progressDone = latestRun ? latestRun.completed_jobs + latestRun.failed_jobs : 0;
  const warningThreshold = preferences?.import_worker_cost_warning_threshold || 4;
  const preferenceDirty = Boolean(
    preferences &&
      (preferences.import_worker_concurrency !== importWorkerConcurrency ||
        preferences.accent_color_day !== accentColorDay ||
        preferences.accent_color_night !== accentColorNight ||
        preferences.document_cache_size_mb !== documentCacheSizeMb ||
        !sameStringMap(preferences.analysis_models, analysisModels)),
  );
  const importCostWarning = importWorkerConcurrency > warningThreshold;

  return (
    <section className="workbench settings-grid">
      <div className="settings-tile">
        <Gauge size={22} />
        <h2>Runtime</h2>
        <p>Port 3737, FastAPI, PostgreSQL, pgvector, durable worker.</p>
      </div>
      <div className="settings-tile">
        <Cloud size={22} />
        <h2>Storage</h2>
        <p>Set GCS_BUCKET and GOOGLE_APPLICATION_CREDENTIALS to use Google Cloud Storage and Vision OCR.</p>
      </div>
      <div className="settings-tile">
        <Sparkles size={22} />
        <h2>AI</h2>
        <p>Set OPENAI_API_KEY to enable structured metadata, summaries, topics, and embeddings.</p>
      </div>
      <div className="preferences-panel">
        <div className="panel-title-row">
          <div>
            <h2>Preferences</h2>
            <span>Import worker throughput</span>
          </div>
          <Settings size={20} />
        </div>
        <div className="preference-control">
          <label htmlFor="import-worker-concurrency">
            <span>Import workers</span>
            <strong>{importWorkerConcurrency}</strong>
          </label>
          <input
            id="import-worker-concurrency"
            min={1}
            onChange={(event) => setImportWorkerConcurrency(Math.max(1, Number(event.target.value) || 1))}
            type="number"
            value={importWorkerConcurrency}
          />
          <p>Default is 4. Higher values can fan out many OpenAI calls at once.</p>
          {importCostWarning ? (
            <p className="preference-warning">Higher concurrency can incur a large OpenAI cost over a short amount of time.</p>
          ) : null}
        </div>
        <div className="preference-control">
          <label htmlFor="document-cache-size">
            <span>Document Cache Size</span>
            <strong>{documentCacheSizeMb.toLocaleString()} MB</strong>
          </label>
          <input
            id="document-cache-size"
            min={0}
            onChange={(event) => setDocumentCacheSizeMb(Math.max(0, Number(event.target.value) || 0))}
            type="number"
            value={documentCacheSizeMb}
          />
          <p>Default is 1,000 MB. Uploads still write originals to configured storage before cache rules apply.</p>
        </div>
        <div className="accent-settings">
          <label>
            <span>Day accent</span>
            <span className="accent-swatch" style={{ background: accentColorDay }} />
            <input type="color" value={accentColorDay} onChange={(event) => setAccentColorDay(event.target.value)} />
          </label>
          <label>
            <span>Night accent</span>
            <span className="accent-swatch" style={{ background: accentColorNight }} />
            <input type="color" value={accentColorNight} onChange={(event) => setAccentColorNight(event.target.value)} />
          </label>
        </div>
        <button
          className="primary-button"
          disabled={!preferences || !preferenceDirty || savePreferences.isPending}
          onClick={() => savePreferences.mutate()}
          type="button"
        >
          <Save size={16} />
          Save
        </button>
      </div>
      <div className="model-settings-panel">
        <div className="panel-title-row">
          <div>
            <h2>Models</h2>
            <span>{preferences?.analysis_model_tasks.length || 7} document-analysis tasks</span>
          </div>
          <Sparkles size={20} />
        </div>
        <div className="models-note">
          <Info size={15} />
          <span>Changing a model affects new work. Run Concordance for older documents that need matching analysis.</span>
        </div>
        <div className="model-task-grid">
          {(preferences?.analysis_model_tasks || []).map((task) => (
            <div className="model-task-row" key={task.key}>
              <div className="model-task-label">
                <span>{task.label}</span>
                <InfoPopup text={task.description} />
              </div>
              <ModelSelect
                defaultModel={task.default_model}
                onChange={(model) => setAnalysisModels((current) => ({ ...current, [task.key]: model }))}
                options={preferences?.model_options[task.model_kind] || []}
                value={analysisModels[task.key] || task.selected_model || task.default_model}
              />
            </div>
          ))}
        </div>
        <button
          className="primary-button"
          disabled={!preferences || !preferenceDirty || savePreferences.isPending}
          onClick={() => savePreferences.mutate()}
          type="button"
        >
          <Save size={16} />
          Save models
        </button>
      </div>
      <div className="export-panel">
        <div className="panel-title-row">
          <div>
            <h2>Backup Export</h2>
            <span>Metadata plus durable asset manifest</span>
          </div>
          <Archive size={20} />
        </div>
        <p>
          Exports include documents, organization, notes, corrections, processing history, and storage URIs. Secrets, sessions, and
          password hashes stay out.
        </p>
        <div className="export-actions">
          <a className="primary-button" href="/api/exports/metadata" download>
            <Download size={16} />
            Full metadata
          </a>
          <a className="secondary-button" href="/api/exports/storage-manifest" download>
            <Download size={16} />
            Asset manifest
          </a>
        </div>
      </div>
      <div className="concordance-panel">
        <div className="panel-title-row">
          <div>
            <h2>Concordance Runs</h2>
            <span>{activeJobs} active jobs</span>
          </div>
          <button className="primary-button" disabled={createRun.isPending || !scopeReady || !selectedCapabilityKeys.length} onClick={() => createRun.mutate()}>
            <RefreshCw size={16} />
            Start run
          </button>
        </div>
        <div className="scope-grid">
          <label>
            Scope
            <select value={scopeType} onChange={(event) => setScopeType(event.target.value as typeof scopeType)}>
              <option value="library">Library</option>
              <option value="documents">Current document</option>
              <option value="search">Current search</option>
              <option value="saved_search">Saved search</option>
              <option value="domain">Domain</option>
              <option value="project">Project</option>
            </select>
          </label>
          {scopeType === "domain" ? (
            <label>
              Domain
              <select value={domainId} onChange={(event) => setDomainId(event.target.value)}>
                <option value="">Select domain</option>
                {domains.map((domain) => (
                  <option key={domain.id} value={domain.id}>
                    {domain.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {scopeType === "project" ? (
            <label>
              Project
              <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                <option value="">Select project</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {scopeType === "saved_search" ? (
            <label>
              Saved search
              <select value={savedSearchId} onChange={(event) => setSavedSearchId(event.target.value)}>
                <option value="">Select saved search</option>
                {savedSearches.map((savedSearch) => (
                  <option key={savedSearch.id} value={savedSearch.id}>
                    {savedSearch.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {scopeType === "documents" ? (
            <div className="scope-summary">
              <span>{selectedDocument?.title || "No document selected"}</span>
            </div>
          ) : null}
          {scopeType === "search" ? (
            <div className="scope-summary">
              <span>{query.trim() || "No active search"}</span>
            </div>
          ) : null}
        </div>
        <label className="checkbox-row">
          <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
          <span>Force current versions</span>
        </label>
        <div className="capability-picker">
          {capabilities.map((capability) => (
            <label key={capability.key}>
              <input
                type="checkbox"
                checked={selectedCapabilityKeys.includes(capability.key)}
                onChange={() =>
                  setSelectedCapabilityKeys((current) =>
                    current.includes(capability.key)
                      ? current.filter((key) => key !== capability.key)
                      : [...current, capability.key],
                  )
                }
              />
              <span>{capability.label}</span>
            </label>
          ))}
        </div>
        <div className="capability-grid">
          {capabilities.map((capability) => (
            <article key={capability.key}>
              <div>
                <strong>{capability.label}</strong>
                <StatusPill value={`v${capability.version}`} tone="blue" />
              </div>
              <p>{capability.description}</p>
            </article>
          ))}
        </div>
        <div className="run-history">
          <div className="run-row header">
            <span>Recent run</span>
            <span>Status</span>
            <span>Progress</span>
          </div>
          {latestRun ? (
            <div className="run-row">
              <span>{latestRun.label || latestRun.scope_type}</span>
              <StatusPill value={latestRun.status} tone={latestRun.failed_jobs ? "warn" : latestRun.status === "complete" ? "good" : "blue"} />
              <span>
                {progressDone}/{progressTotal}
              </span>
            </div>
          ) : (
            <div className="run-row empty">
              <span>No runs yet</span>
              <span />
              <span />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export default function App() {
  const [activeView, setActiveView] = useState<View>("library");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<DocumentFilters>(() => emptyFilters());
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [theme, setTheme] = useState<"day" | "night">(() => (localStorage.getItem("medusa-theme") as "day" | "night") || "day");
  const [sidebarWidth, setSidebarWidth] = useStoredPaneSize("medusa-sidebar-width", 220, 168, 304);
  const [sidebarCollapsed, setSidebarCollapsed] = useStoredBoolean("medusa-sidebar-collapsed", false);
  const queryClient = useQueryClient();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("medusa-theme", theme);
  }, [theme]);

  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, enabled: Boolean(me.data), refetchInterval: 4000 });
  const preferences = useQuery({ queryKey: ["preferences"], queryFn: api.preferences, enabled: Boolean(me.data) });
  const domains = useQuery({ queryKey: ["domains"], queryFn: api.domains, enabled: Boolean(me.data) });
  const tags = useQuery({ queryKey: ["tags"], queryFn: api.tags, enabled: Boolean(me.data) });
  const savedSearches = useQuery({ queryKey: ["saved-searches"], queryFn: api.savedSearches, enabled: Boolean(me.data) });
  const documents = useQuery({
    queryKey: ["documents", query, filters],
    queryFn: () => api.documents(query, filters),
    enabled: Boolean(me.data),
    refetchInterval: 10000,
  });
  const selectedDocument = useQuery({
    queryKey: ["document", selectedId],
    queryFn: () => api.document(selectedId!),
    enabled: Boolean(me.data && selectedId),
    refetchInterval: 4000,
  });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, enabled: Boolean(me.data), refetchInterval: 4000 });
  const concordanceCapabilities = useQuery({
    queryKey: ["concordance-capabilities"],
    queryFn: api.concordanceCapabilities,
    enabled: Boolean(me.data),
  });
  const concordanceRuns = useQuery({
    queryKey: ["concordance-runs"],
    queryFn: api.concordanceRuns,
    enabled: Boolean(me.data),
    refetchInterval: 4000,
  });
  const concordanceJobs = useQuery({
    queryKey: ["concordance-jobs"],
    queryFn: api.concordanceJobs,
    enabled: Boolean(me.data),
    refetchInterval: 4000,
  });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, enabled: Boolean(me.data) });
  const notes = useQuery({ queryKey: ["notes"], queryFn: () => api.notes(), enabled: Boolean(me.data), refetchInterval: 10000 });
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

  const activeAccent = normalizeHexColor(
    theme === "night" ? preferences.data?.accent_color_night : preferences.data?.accent_color_day,
    theme === "night" ? "#6ea8ff" : "#2563eb",
  );
  const shellStyle = {
    "--sidebar-width": sidebarCollapsed ? "52px" : `${sidebarWidth}px`,
    "--sidebar-resizer-width": sidebarCollapsed ? "0px" : "8px",
    "--accent": activeAccent,
    "--accent-soft": accentSoftColor(activeAccent, theme),
  } as CSSProperties;

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`} style={shellStyle}>
      <Header
        query={query}
        setQuery={setQuery}
        theme={theme}
        setTheme={setTheme}
        onLogout={() => logout.mutate()}
      />
      <Sidebar
        activeView={activeView}
        collapsed={sidebarCollapsed}
        activeImportJobs={dashboard.data?.active_import_jobs || 0}
        dashboard={dashboard.data}
        onOpenQueue={() => setActiveView("queue")}
        onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
        setActiveView={setActiveView}
      />
      {!sidebarCollapsed ? (
        <ResizeHandle
          className="sidebar-resizer"
          label="Resize navigation pane"
          max={304}
          min={168}
          setValue={setSidebarWidth}
          value={sidebarWidth}
        />
      ) : null}
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
        {activeView === "library" || activeView === "domains" ? (
          <LibraryView
            documents={documents.data || []}
            document={selectedDocument.data}
            selectedId={selectedId}
            setSelectedId={setSelectedId}
            domains={domains.data || []}
            tags={tags.data || []}
            projects={projects.data || []}
            citationJobs={concordanceJobs.data || []}
            query={query}
            setQuery={setQuery}
            filters={filters}
            setFilters={setFilters}
            savedSearches={savedSearches.data || []}
            loading={documents.isFetching}
          />
        ) : null}
        {activeView === "import" ? (
          <ImportView domains={domains.data || []} jobs={jobs.data || []} projects={projects.data || []} tags={tags.data || []} />
        ) : null}
        {activeView === "projects" ? <ProjectsView documents={documents.data || []} projects={projects.data || []} /> : null}
        {activeView === "queue" ? <QueueView items={review.data || []} jobs={jobs.data || []} /> : null}
        {activeView === "notes" ? (
          <NotesView
            documents={documents.data || []}
            domains={domains.data || []}
            notes={notes.data || []}
            projects={projects.data || []}
          />
        ) : null}
        {activeView === "settings" ? (
          <SettingsView
            capabilities={concordanceCapabilities.data || []}
            domains={domains.data || []}
            jobs={concordanceJobs.data || []}
            preferences={preferences.data}
            projects={projects.data || []}
            query={query}
            runs={concordanceRuns.data || []}
            savedSearches={savedSearches.data || []}
            selectedDocument={selectedDocument.data}
          />
        ) : null}
      </main>
    </div>
  );
}

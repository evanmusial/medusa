import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, DragEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node as FlowNode,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Archive,
  Bookmark,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  CheckSquare,
  CircleDollarSign,
  Clipboard,
  Cloud,
  Download,
  Edit3,
  Eraser,
  ExternalLink,
  FileSearch,
  FileText,
  Filter,
  FolderTree,
  Gauge,
  Info,
  Image,
  Inbox,
  Library,
  ListChecks,
  LogOut,
  Moon,
  PieChart,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Settings,
  Sparkles,
  Sun,
  Tags,
  Trash2,
  Upload,
  UploadCloud,
  X,
} from "lucide-react";
import { api } from "./lib/api";
import type {
  AccessorySummary,
  AppPreferences,
  Bibliography,
  CitationCandidate,
  ConcordanceCapability,
  ConcordanceJob,
  ConcordanceRun,
  Dashboard,
  DocumentComposition,
  DocumentCompositionEntry,
  DocumentDetail,
  DocumentFilters,
  DocumentRecommendation,
  DocumentSummary,
  DocumentUpdatePayload,
  Domain,
  DuplicateImportStrategy,
  ImportDuplicateCheck,
  ImportJob,
  ModelOptionGroup,
  Note,
  NotePayload,
  OpenAIUsage,
  OpenAIUsageGroup,
  OpenAIUsagePeriod,
  Project,
  ProjectItem,
  SavedSearch,
  Tag,
} from "./types";

type View = "library" | "domains" | "projects" | "queue" | "notes" | "import" | "budget" | "settings";
type NavCounts = Partial<Record<View, number>>;
type AsyncFeedbackTone = "success" | "error";
type AsyncActionFeedback = { tone: AsyncFeedbackTone; message?: string; token: number };
type BackgroundJobStatus = "starting" | "queued" | "running" | "complete" | "failed";
type BackgroundJob = {
  id: string;
  label: string;
  detail?: string;
  status: BackgroundJobStatus;
  runId?: string;
  documentId?: string;
  capabilityKey?: string;
  completedJobs?: number;
  failedJobs?: number;
  totalJobs?: number;
  error?: string;
  createdAt: number;
  completedAt?: number;
};
type ConcordanceRunRequest = {
  backgroundDetail?: string;
  backgroundLabel?: string;
  capability_keys?: string[];
  capabilityKey?: string;
  documentId?: string;
  force?: boolean;
  label?: string;
  scope_data?: Record<string, unknown>;
  scope_type?: string;
};
type StartConcordanceRun = (request: ConcordanceRunRequest) => Promise<ConcordanceRun>;

const ACCESSORY_SUMMARIES_MODEL_KEY = "accessory_summaries";
const FILTER_PANE_MIN = 260;
const FILTER_PANE_DEFAULT = 280;
const FILTER_PANE_MAX = 420;
const MEDUSA_BUILD_VERSION = import.meta.env.VITE_MEDUSA_BUILD_VERSION || "local";
const MEDUSA_APP_NAME = "medusa";
const MEDUSA_EXPANSION = "Mapped Evidence for Discovery, Understanding, Synthesis, and Analysis";
const QUEUE_IMPORT_JOB_STATUSES = new Set(["queued", "running", "failed", "restored_paused"]);
const ASYNC_ACTION_SUCCESS_FEEDBACK_MS = 900;
const ASYNC_ACTION_ERROR_FEEDBACK_MS = 5000;
const BACKGROUND_JOB_RETENTION_MS = 18000;
const USAGE_PERIOD_OPTIONS: Array<{ value: OpenAIUsagePeriod; label: string }> = [
  { value: "last_day", label: "Last day" },
  { value: "last_month", label: "Last month" },
  { value: "last_3_months", label: "Last 3 months" },
  { value: "all_time", label: "All time" },
];
type BudgetMetricMode = "tokens_cost" | "tokens" | "cost";
type BudgetGroupMode = "model" | "task" | "document" | "day" | "hour";

const navItems: Array<{ id: View; label: string; icon: typeof Library; shortcut?: string; align?: "end" }> = [
  { id: "library", label: "Library", icon: Library },
  { id: "domains", label: "Domains", icon: FolderTree },
  { id: "projects", label: "Projects", icon: ListChecks },
  { id: "queue", label: "Queue", icon: Inbox },
  { id: "notes", label: "Notes", icon: BookOpen },
  { id: "import", label: "Import", icon: Upload },
  { id: "budget", label: "Budget", icon: CircleDollarSign, shortcut: "B" },
  { id: "settings", label: "Settings", icon: Settings, align: "end" },
];

function authorLine(document: DocumentSummary | DocumentDetail) {
  const authors = document.authors || [];
  if (!authors.length) return "Unknown author";
  return authors
    .slice(0, 3)
    .map((author) => [author.given, author.family].filter(Boolean).join(" "))
    .join(", ");
}

function pageCountMarker(document: DocumentSummary | DocumentDetail) {
  return document.page_count > 0 ? `${document.page_count}pp` : "?pp";
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

function citationText(document: DocumentDetail, kind: CitationKind) {
  return kind === "reference" ? document.apa_citation || "" : document.apa_in_text_citation || "";
}

function citationModel(document: DocumentDetail, kind: CitationKind) {
  return kind === "reference" ? document.apa_citation_model : document.apa_in_text_citation_model;
}

function citationSource(document: DocumentDetail, kind: CitationKind) {
  return kind === "reference" ? document.apa_citation_source : document.apa_in_text_citation_source;
}

function citationProvenanceLabel(document: DocumentDetail, kind: CitationKind) {
  if (citationSource(document, kind) === "user") return "user provided";
  const model = citationModel(document, kind);
  if (model) return model;
  return citationText(document, kind) ? "gpt-5.5" : "not generated";
}

function formatNavCount(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return "";
  if (Math.abs(value) < 1000) return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value);
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1, notation: "compact" }).format(value);
}

function isQueueImportJob(job: ImportJob) {
  return QUEUE_IMPORT_JOB_STATUSES.has(job.status);
}

function actionFailureMessage(action: string, error: unknown) {
  const detail = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  return detail ? `${action}: ${detail}` : action;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function countOccurrences(text: string, needle: string) {
  if (!needle) return 0;
  let count = 0;
  let index = 0;
  while (index <= text.length) {
    const next = text.indexOf(needle, index);
    if (next < 0) break;
    count += 1;
    index = next + needle.length;
  }
  return count;
}

const restorableDocumentKeys = new Set([
  "title",
  "subtitle",
  "authors",
  "universities",
  "publication_year",
  "publisher",
  "journal",
  "doi",
  "source_url",
  "abstract",
  "rich_summary",
  "apa_citation",
  "apa_in_text_citation",
  "citation_status",
  "metadata_confidence",
  "metadata_evidence",
  "read_status",
  "priority",
  "tags",
  "domains",
  "attributes",
]);

function versionSnapshot(version: DocumentDetail["versions"][number]) {
  return isRecord(version.metadata_snapshot) ? version.metadata_snapshot : {};
}

function changedFieldsForVersion(version: DocumentDetail["versions"][number]) {
  const changedFields = versionSnapshot(version).changed_fields;
  return Array.isArray(changedFields) ? changedFields.filter((field): field is string => typeof field === "string") : [];
}

function versionDocumentTarget(version: DocumentDetail["versions"][number]) {
  const snapshot = versionSnapshot(version);
  if (isRecord(snapshot.after)) return snapshot.after;
  return [...restorableDocumentKeys].some((key) => key in snapshot) ? snapshot : null;
}

function versionPageTargets(version: DocumentDetail["versions"][number]) {
  const snapshot = versionSnapshot(version);
  const pages: Record<string, unknown>[] = [];
  if (isRecord(snapshot.page_after)) pages.push(snapshot.page_after);
  if (Array.isArray(snapshot.pages)) {
    snapshot.pages.forEach((entry) => {
      if (!isRecord(entry)) return;
      if (isRecord(entry.after)) pages.push(entry.after);
    });
  }
  return pages;
}

function versionIsRestorable(version: DocumentDetail["versions"][number]) {
  return Boolean(versionDocumentTarget(version) || versionPageTargets(version).length);
}

function versionPreviewLines(version: DocumentDetail["versions"][number]) {
  const target = versionDocumentTarget(version);
  const pages = versionPageTargets(version);
  const lines: string[] = [];
  if (target) {
    if (typeof target.title === "string" && target.title.trim()) lines.push(target.title.trim());
    const year = target.publication_year;
    if (typeof year === "number" || typeof year === "string") lines.push(`Year ${year}`);
    if (Array.isArray(target.tags) && target.tags.length) lines.push(`${target.tags.length} tags`);
    if (isRecord(target.attributes) && Object.keys(target.attributes).length) lines.push(`${Object.keys(target.attributes).length} attributes`);
  }
  if (pages.length === 1 && typeof pages[0].page_number === "number") lines.push(`Page ${pages[0].page_number}`);
  else if (pages.length > 1) lines.push(`${pages.length} pages`);
  const scrubCount = versionSnapshot(version).scrub_count;
  if (typeof scrubCount === "number") lines.push(`${scrubCount} scrubbed`);
  return lines;
}

function useAsyncActionFeedback(options: { successMs?: number; errorMs?: number } = {}) {
  const [feedback, setFeedback] = useState<AsyncActionFeedback | null>(null);
  const startTimerRef = useRef<number | null>(null);
  const clearTimerRef = useRef<number | null>(null);
  const successMs = options.successMs ?? ASYNC_ACTION_SUCCESS_FEEDBACK_MS;
  const errorMs = options.errorMs ?? ASYNC_ACTION_ERROR_FEEDBACK_MS;

  const clearTimers = useCallback(() => {
    if (startTimerRef.current !== null) window.clearTimeout(startTimerRef.current);
    if (clearTimerRef.current !== null) window.clearTimeout(clearTimerRef.current);
    startTimerRef.current = null;
    clearTimerRef.current = null;
  }, []);

  const show = useCallback(
    (tone: AsyncFeedbackTone, message?: string) => {
      clearTimers();
      setFeedback(null);
      startTimerRef.current = window.setTimeout(() => {
        const durationMs = tone === "success" ? successMs : errorMs;
        setFeedback({ tone, message, token: Date.now() });
        clearTimerRef.current = window.setTimeout(() => {
          setFeedback(null);
          clearTimerRef.current = null;
        }, durationMs);
      }, 0);
    },
    [clearTimers, errorMs, successMs],
  );

  useEffect(() => clearTimers, [clearTimers]);

  return {
    feedback,
    showError: useCallback((message: string) => show("error", message), [show]),
    showSuccess: useCallback(() => show("success"), [show]),
  };
}

function useAsyncActionFeedbackMap() {
  const [feedbackByKey, setFeedbackByKey] = useState<Record<string, AsyncActionFeedback>>({});
  const startTimersRef = useRef<Record<string, number>>({});
  const clearTimersRef = useRef<Record<string, number>>({});

  const clearKeyTimers = useCallback((key: string) => {
    if (startTimersRef.current[key] !== undefined) window.clearTimeout(startTimersRef.current[key]);
    if (clearTimersRef.current[key] !== undefined) window.clearTimeout(clearTimersRef.current[key]);
    delete startTimersRef.current[key];
    delete clearTimersRef.current[key];
  }, []);

  const show = useCallback(
    (key: string, tone: AsyncFeedbackTone, message?: string) => {
      clearKeyTimers(key);
      setFeedbackByKey((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      startTimersRef.current[key] = window.setTimeout(() => {
        setFeedbackByKey((current) => ({ ...current, [key]: { tone, message, token: Date.now() } }));
        clearTimersRef.current[key] = window.setTimeout(() => {
          setFeedbackByKey((current) => {
            const next = { ...current };
            delete next[key];
            return next;
          });
          delete clearTimersRef.current[key];
        }, tone === "success" ? ASYNC_ACTION_SUCCESS_FEEDBACK_MS : ASYNC_ACTION_ERROR_FEEDBACK_MS);
      }, 0);
    },
    [clearKeyTimers],
  );

  useEffect(
    () => () => {
      Object.values(startTimersRef.current).forEach((timer) => window.clearTimeout(timer));
      Object.values(clearTimersRef.current).forEach((timer) => window.clearTimeout(timer));
    },
    [],
  );

  return {
    feedbackFor: useCallback((key: string) => feedbackByKey[key] || null, [feedbackByKey]),
    showError: useCallback((key: string, message: string) => show(key, "error", message), [show]),
    showSuccess: useCallback((key: string) => show(key, "success"), [show]),
  };
}

function asyncFeedbackClass(className: string, feedback?: AsyncActionFeedback | null, busy = false) {
  return [className, busy ? "async-feedback-progress" : "", feedback ? `async-feedback-${feedback.tone}` : ""]
    .filter(Boolean)
    .join(" ");
}

function AsyncActionSlot({
  busy = false,
  children,
  feedback,
  label = "Async work in progress",
}: {
  busy?: boolean;
  children: ReactNode;
  feedback?: AsyncActionFeedback | null;
  label?: string;
}) {
  return (
    <span className={`async-action-slot ${busy ? "in-flight" : ""}`}>
      {children}
      {busy ? (
        <span className="async-action-progress" role="progressbar" aria-label={label}>
          <span />
        </span>
      ) : null}
      {feedback?.tone === "error" && feedback.message ? (
        <span key={feedback.token} className="async-action-message" role="alert">
          {feedback.message}
        </span>
      ) : null}
    </span>
  );
}

function scopeLabel(value?: string) {
  return (value || "library").replaceAll("_", " ");
}

function backgroundJobId() {
  return `job-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function isTerminalBackgroundStatus(status: BackgroundJobStatus) {
  return status === "complete" || status === "failed";
}

function isActiveConcordanceStatus(status: string) {
  return status === "queued" || status === "running";
}

function isActiveAccessorySummaryStatus(status: string) {
  return status === "queued" || status === "running";
}

function accessorySummaryTone(summary: AccessorySummary): "neutral" | "good" | "warn" | "blue" {
  if (summary.status === "complete") return "good";
  if (summary.status === "failed") return "warn";
  if (isActiveAccessorySummaryStatus(summary.status)) return "blue";
  return "neutral";
}

function statusFromRun(run: ConcordanceRun, runJobs: ConcordanceJob[]): BackgroundJobStatus {
  if (run.status === "complete_with_errors" || run.failed_jobs > 0 || runJobs.some((job) => job.status === "failed")) return "failed";
  if (run.status === "complete") return "complete";
  if (runJobs.some((job) => job.status === "running")) return "running";
  return "queued";
}

function runFailureMessage(run: ConcordanceRun, runJobs: ConcordanceJob[]) {
  const failedJob = runJobs.find((job) => job.status === "failed" && job.last_error);
  if (failedJob?.last_error) return failedJob.last_error;
  if (run.failed_jobs > 0) return `${run.failed_jobs} Concordance ${run.failed_jobs === 1 ? "job" : "jobs"} failed.`;
  return undefined;
}

function backgroundJobFromRun(run: ConcordanceRun, runJobs: ConcordanceJob[], existing?: BackgroundJob): BackgroundJob {
  const status = statusFromRun(run, runJobs);
  const terminal = isTerminalBackgroundStatus(status);
  const now = Date.now();
  return {
    id: existing?.id || run.id,
    label: existing?.label || run.label || `${scopeLabel(run.scope_type)} Concordance`,
    detail: existing?.detail || `${run.completed_jobs + run.failed_jobs} of ${run.total_jobs} jobs finished`,
    status,
    runId: run.id,
    documentId: existing?.documentId,
    capabilityKey: existing?.capabilityKey,
    completedJobs: run.completed_jobs,
    failedJobs: run.failed_jobs,
    totalJobs: run.total_jobs,
    error: status === "failed" ? runFailureMessage(run, runJobs) : undefined,
    createdAt: existing?.createdAt || new Date(run.created_at).getTime() || now,
    completedAt: terminal ? existing?.completedAt || now : undefined,
  };
}

function backgroundProgress(job: BackgroundJob) {
  if (job.status === "complete" || job.status === "failed") return 100;
  if (job.status === "starting") return 10;
  const total = job.totalJobs || 0;
  if (!total) return job.status === "running" ? 35 : 18;
  return Math.max(8, Math.min(96, Math.round((((job.completedJobs || 0) + (job.failedJobs || 0)) / total) * 100)));
}

function backgroundStatusLabel(job: BackgroundJob) {
  if (job.status === "starting") return "Starting";
  if (job.status === "queued") return "Queued";
  if (job.status === "running") return "Processing";
  if (job.status === "failed") return "Needs attention";
  return "Complete";
}

function HeaderWorkProgress({
  dashboard,
  jobs,
  onOpenQueue,
}: {
  dashboard?: Dashboard;
  jobs: BackgroundJob[];
  onOpenQueue: () => void;
}) {
  const importActive = Boolean(dashboard && dashboard.active_import_jobs > 0);
  const activeJobs = jobs.filter((job) => !isTerminalBackgroundStatus(job.status));
  if (!importActive && !activeJobs.length) return <div className="header-work-slot empty" aria-hidden="true" />;

  let label = "Background work";
  let detail = "Processing";
  let progress = 10;
  let activeClass = "running";

  if (importActive && dashboard) {
    const total = dashboard.import_progress_total || dashboard.active_import_jobs;
    const finished = Math.min(total, dashboard.import_progress_completed + dashboard.import_progress_failed);
    const percent = total > 0 ? Math.round((finished / total) * 100) : 0;
    progress = Math.max(0, Math.min(100, dashboard.import_running_jobs > 0 && percent === 0 ? 6 : percent));
    label = "Imports";
    activeClass = dashboard.import_running_jobs > 0 ? "running" : "queued";
    const activeStep = dashboard.import_active_step?.replaceAll("_", " ");
    const activeElapsed = formatDuration(dashboard.import_active_elapsed_seconds);
    const activeCost = dashboard.import_active_cost_usd > 0 ? ` - ${formatUsd(dashboard.import_active_cost_usd)}` : "";
    detail = activeStep
      ? `${activeStep}${activeElapsed ? ` - ${activeElapsed}` : ""}${activeCost}`
      : `${dashboard.import_running_jobs} importing / ${dashboard.import_queued_jobs} queued`;
  } else {
    const job = activeJobs[0];
    progress = backgroundProgress(job);
    label = activeJobs.length > 1 ? `${activeJobs.length} background jobs` : job.label;
    detail = job.detail || backgroundStatusLabel(job);
    activeClass = job.status;
  }

  return (
    <div className="header-work-slot">
      <button className={`header-work-progress ${activeClass}`} type="button" aria-label="Open import queue" onClick={onOpenQueue}>
        <span className="header-work-main">
          <span className="header-work-icon">
            <RefreshCw className={activeClass === "running" ? "spin" : ""} size={15} />
          </span>
          <span className="header-work-copy">
            <strong>{label}</strong>
            <small>{detail}</small>
          </span>
        </span>
        <span
          aria-label={`${label}: ${progress}%`}
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={progress}
          className="header-work-track"
          role="progressbar"
        >
          <span style={{ width: `${progress}%` }} />
        </span>
      </button>
    </div>
  );
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

function formatMetric(value?: number | null) {
  if (value === undefined || value === null || !Number.isFinite(value)) return "0";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0, notation: Math.abs(value) >= 100000 ? "compact" : "standard" }).format(value);
}

function formatUsd(value?: number | null) {
  if (value === undefined || value === null || !Number.isFinite(value)) return "Unpriced";
  const minimumFractionDigits = value > 0 && value < 0.01 ? 4 : 2;
  return new Intl.NumberFormat(undefined, {
    currency: "USD",
    maximumFractionDigits: 4,
    minimumFractionDigits,
    style: "currency",
  }).format(value);
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

function formatDurationMs(ms?: number | null) {
  if (!ms) return "";
  return formatDuration(ms / 1000);
}

const COMPOSITION_COLORS = ["#2563eb", "#14b8a6", "#f59e0b", "#8b5cf6", "#ef4444", "#64748b", "#22c55e"];

function compositionLabel(entry: DocumentCompositionEntry) {
  return entry.model || entry.method || entry.label || entry.stage_label || entry.provider || "Unknown";
}

function compositionPieGradient(entries: DocumentCompositionEntry[]) {
  const total = entries.reduce((sum, entry) => sum + Math.max(0, entry.amount_usd || 0), 0);
  if (!total) return "conic-gradient(var(--line) 0 100%)";
  let cursor = 0;
  const stops = entries.map((entry, index) => {
    const start = cursor;
    cursor += (Math.max(0, entry.amount_usd || 0) / total) * 100;
    const color = COMPOSITION_COLORS[index % COMPOSITION_COLORS.length];
    return `${color} ${start}% ${cursor}%`;
  });
  return `conic-gradient(${stops.join(", ")})`;
}

type PipelineNodeData = Record<string, unknown> & {
  amountUsd: number;
  callCount: number;
  durationMs: number;
  meta: string;
  status: string;
  subtitle: string;
  title: string;
  tone: string;
};

type CompositionPipelineNode = FlowNode<PipelineNodeData, "compositionPipeline">;

const compositionPipelineNodeTypes = {
  compositionPipeline: CompositionPipelineNodeView,
};

function pipelineTone(entry: DocumentCompositionEntry) {
  if (entry.status === "failed" || entry.status === "error") return "error";
  if (entry.status === "warning") return "warning";
  if (entry.record_kind === "llm") return "llm";
  if (entry.record_kind === "embedding") return "embedding";
  if (entry.record_kind === "edit") return "edit";
  return "local";
}

function pipelineMeta(entry: DocumentCompositionEntry) {
  return [
    entry.provider,
    entry.amount_usd > 0 ? formatUsd(entry.amount_usd) : "",
    formatDurationMs(entry.duration_ms),
    entry.total_tokens ? `${formatMetric(entry.total_tokens)} tokens` : "",
    entry.call_count > 1 ? `${entry.call_count} calls` : "",
  ]
    .filter(Boolean)
    .join(" / ");
}

function pipelineNodesAndEdges(pipeline: DocumentCompositionEntry[]) {
  const nodeWidth = 236;
  const nodeHeight = 126;
  const horizontalGap = 70;
  const verticalGap = 90;
  const columns = Math.max(1, Math.min(3, pipeline.length));
  const nodes: CompositionPipelineNode[] = pipeline.map((entry, index) => ({
    id: `pipeline-${index}`,
    type: "compositionPipeline",
    position: {
      x: (index % columns) * (nodeWidth + horizontalGap),
      y: Math.floor(index / columns) * (nodeHeight + verticalGap),
    },
    data: {
      amountUsd: entry.amount_usd || 0,
      callCount: entry.call_count || 0,
      durationMs: entry.duration_ms || 0,
      meta: pipelineMeta(entry),
      status: entry.status || "complete",
      subtitle: compositionLabel(entry),
      title: entry.stage_label || entry.label || "Pipeline step",
      tone: pipelineTone(entry),
    },
  }));
  const edges: Edge[] = pipeline.slice(1).map((_, index) => ({
    id: `pipeline-edge-${index}`,
    source: `pipeline-${index}`,
    target: `pipeline-${index + 1}`,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
    style: { strokeWidth: 2 },
  }));
  return { nodes, edges };
}

function CompositionPipelineNodeView({ data }: NodeProps<CompositionPipelineNode>) {
  const hasSpend = data.amountUsd > 0;
  const hasDuration = data.durationMs > 0;
  return (
    <div className={`composition-pipeline-node ${data.tone}`}>
      <span>{data.title}</span>
      <strong>{data.subtitle}</strong>
      {data.meta ? <small>{data.meta}</small> : null}
      <div>
        <em>{data.status}</em>
        {hasSpend ? <em>{formatUsd(data.amountUsd)}</em> : null}
        {hasDuration ? <em>{formatDurationMs(data.durationMs)}</em> : null}
      </div>
    </div>
  );
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

function candidateMetadataText(candidate: CitationCandidate, key: string) {
  const value = candidate.metadata?.[key];
  if (typeof value === "string") return decodeHtmlEntities(value).trim();
  if (typeof value === "number") return String(value);
  return "";
}

function citationCandidateTitle(candidate: CitationCandidate) {
  return candidate.document_title || candidateMetadataText(candidate, "title") || "Untitled document";
}

function citationCandidateSourceLabel(candidate: CitationCandidate) {
  const source = candidate.source.replaceAll("_", " ").replaceAll("-", " ").trim();
  return source ? source : "candidate";
}

function citationCandidateReviewDate(candidate: CitationCandidate) {
  const date = new Date(candidate.created_at);
  if (Number.isNaN(date.valueOf())) return "";
  return date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
}

function importJobStatusLabel(job: ImportJob) {
  if (job.status === "complete") return "complete";
  if (job.status === "failed") return "failed";
  if (job.status === "queued") return "queued";
  if (job.status === "restored_paused") return "restored paused";
  return importJobStage(job);
}

function ImportJobStatusDetail({ job }: { job: ImportJob }) {
  const status = importJobStatusLabel(job);
  const model = modelDisplayName(job.current_model);
  const cost = formatUsd(job.estimated_cost_usd ?? 0);
  return (
    <small className="job-status-detail" title={job.status === "failed" ? job.last_error || undefined : undefined}>
      <strong>{status}</strong>
      {model ? ` (${model})` : ""}
      {` (${cost})`}
    </small>
  );
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
  const paragraphLines: string[] = [];
  const lines = decodeHtmlEntities(markdown)
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.trim());
  for (const line of lines) {
    if (!line) {
      if (paragraphLines.length) break;
      continue;
    }
    if (/^#{1,6}\s+/.test(line)) {
      if (paragraphLines.length) break;
      continue;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (bullet || ordered) {
      if (paragraphLines.length) break;
      paragraphLines.push((bullet?.[1] || ordered?.[1] || "").trim());
      break;
    }
    paragraphLines.push(line);
  }
  const paragraph = paragraphLines.join(" ");
  if (paragraph.length <= maxChars) return paragraph;
  const excerpt = paragraph.slice(0, maxChars);
  const sentenceEnd = [...excerpt.matchAll(/[.!?](?=\s+[A-Z0-9*`]|$)/g)].at(-1)?.index;
  if (sentenceEnd && sentenceEnd > 120) return paragraph.slice(0, sentenceEnd + 1).trim();
  const trimmed = excerpt.trimEnd();
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

function BrandLockup({ compact = false, stacked = false }: { compact?: boolean; stacked?: boolean }) {
  return (
    <ViewportTooltip
      ariaLabel={`${MEDUSA_APP_NAME}: ${MEDUSA_EXPANSION}`}
      className={`${stacked ? "brand-stack" : "brand"} brand-tooltip`}
      text={MEDUSA_EXPANSION}
    >
      <span className={`brand-mark${compact ? " compact" : ""}`}>
        <img className="brand-emblem" src="/medusa-emblem.svg" alt="" aria-hidden="true" />
      </span>
      <span className="brand-wordmark">
        <strong className="brand-name">{MEDUSA_APP_NAME}</strong>
      </span>
    </ViewportTooltip>
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
        <BrandLockup stacked />
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
  backgroundJobs,
  dashboard,
  onOpenQueue,
  query,
  setQuery,
  theme,
  setTheme,
  onLogout,
}: {
  backgroundJobs: BackgroundJob[];
  dashboard?: Dashboard;
  onOpenQueue: () => void;
  query: string;
  setQuery: (query: string) => void;
  theme: "day" | "night";
  setTheme: (theme: "day" | "night") => void;
  onLogout: () => void;
}) {
  return (
    <header className="topbar">
      <div className="topbar-brand-area">
        <BrandLockup compact />
      </div>
      <label className="global-search">
        <Search size={17} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search documents, notes, figures, citations..." />
      </label>
      <div className="topbar-actions">
        <HeaderWorkProgress dashboard={dashboard} jobs={backgroundJobs} onOpenQueue={onOpenQueue} />
        <span className="build-version" title={`Medusa build ${MEDUSA_BUILD_VERSION}`}>
          v{MEDUSA_BUILD_VERSION}
        </span>
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

function WorkspaceNav({
  activeView,
  counts,
  setActiveView,
}: {
  activeView: View;
  counts: NavCounts;
  setActiveView: (view: View) => void;
}) {
  return (
    <nav className="workspace-nav" aria-label="Main sections">
      {navItems.map((item) => {
        const Icon = item.icon;
        const rawCount = counts[item.id];
        const count = rawCount !== undefined && (item.id === "library" || rawCount > 0) ? formatNavCount(rawCount) : "";
        return (
          <button
            key={item.id}
            aria-current={activeView === item.id ? "page" : undefined}
            aria-keyshortcuts={item.shortcut}
            className={`workspace-nav-item${activeView === item.id ? " active" : ""}${item.align === "end" ? " settings" : ""}`}
            onClick={() => setActiveView(item.id)}
            title={item.shortcut ? `${item.label} (${item.shortcut})` : item.label}
            type="button"
          >
            <Icon size={17} />
            <span>{item.label}</span>
            {count ? <small className="workspace-nav-count">{count}</small> : null}
          </button>
        );
      })}
    </nav>
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

function BulkMultiSelect({
  emptyLabel,
  extraCount = 0,
  footer,
  label,
  onChange,
  options,
  selectedIds,
}: {
  emptyLabel: string;
  extraCount?: number;
  footer?: ReactNode;
  label: string;
  onChange: (ids: string[]) => void;
  options: Array<{ id: string; name: string }>;
  selectedIds: string[];
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const selectedCount = selectedIds.length + extraCount;

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", closeOnOutsideClick);
    return () => window.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  const toggleId = (id: string) => {
    onChange(selectedIds.includes(id) ? selectedIds.filter((selectedId) => selectedId !== id) : uniqueValues([...selectedIds, id]));
  };

  return (
    <div className="bulk-multi-select" ref={wrapperRef}>
      <button className="bulk-multi-trigger" type="button" onClick={() => setOpen((value) => !value)}>
        <span>{selectedCount ? `${label} ${selectedCount}` : label}</span>
        <ChevronRight size={14} />
      </button>
      {open ? (
        <div className="bulk-multi-menu">
          {options.length ? (
            options.map((option) => (
              <label key={option.id}>
                <input type="checkbox" checked={selectedIds.includes(option.id)} onChange={() => toggleId(option.id)} />
                <span>{option.name}</span>
              </label>
            ))
          ) : (
            <div className="bulk-multi-empty">{emptyLabel}</div>
          )}
          {footer ? <div className="bulk-multi-footer">{footer}</div> : null}
        </div>
      ) : null}
    </div>
  );
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
  startConcordanceRun,
  loading,
  alternatingRows,
  preferences,
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
  startConcordanceRun: StartConcordanceRun;
  loading: boolean;
  alternatingRows: boolean;
  preferences?: AppPreferences;
}) {
  const [filterWidth, setFilterWidth] = useStoredPaneSize("medusa-filter-pane-width", FILTER_PANE_DEFAULT, FILTER_PANE_MIN, FILTER_PANE_MAX);
  const [detailWidth, setDetailWidth] = useStoredPaneSize("medusa-detail-pane-width", 384, 300, 560);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [readerOpen, setReaderOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [bulkReadStatus, setBulkReadStatus] = useState("");
  const [bulkPriority, setBulkPriority] = useState("");
  const [bulkTagIds, setBulkTagIds] = useState<string[]>([]);
  const [bulkCustomTag, setBulkCustomTag] = useState("");
  const [bulkDomainId, setBulkDomainId] = useState("");
  const [bulkProjectIds, setBulkProjectIds] = useState<string[]>([]);
  const [batchConcordanceRunId, setBatchConcordanceRunId] = useState<string | null>(null);
  const [confirmBatchConcordance, setConfirmBatchConcordance] = useState(false);
  const queryClient = useQueryClient();
  const batchConcordanceFeedback = useAsyncActionFeedback();
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
      if (bulkTagIds.length) updates.tag_ids = bulkTagIds;
      if (bulkCustomTag.trim()) updates.tag_names = [bulkCustomTag.trim()];
      if (bulkDomainId) updates.domain_ids = [bulkDomainId];
      if (bulkProjectIds.length) updates.project_ids = bulkProjectIds;
      return api.bulkUpdateDocuments(selectedIds, updates);
    },
    onSuccess: () => {
      setSelectedIds([]);
      setBulkReadStatus("");
      setBulkPriority("");
      setBulkTagIds([]);
      setBulkCustomTag("");
      setBulkDomainId("");
      setBulkProjectIds([]);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document"] });
      void queryClient.invalidateQueries({ queryKey: ["domains"] });
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  const batchConcordance = useMutation({
    mutationFn: () =>
      startConcordanceRun({
        backgroundDetail: `${selectedIds.length} selected ${selectedIds.length === 1 ? "document" : "documents"}`,
        backgroundLabel: "Selected document Concordance",
        label: `Selected document Concordance (${selectedIds.length})`,
        scope_type: "documents",
        scope_data: { document_ids: selectedIds },
      }),
    onSuccess: (run) => {
      if (run.total_jobs > 0) setBatchConcordanceRunId(run.id);
      else batchConcordanceFeedback.showSuccess();
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document"] });
    },
    onError: (error) => {
      setBatchConcordanceRunId(null);
      batchConcordanceFeedback.showError(actionFailureMessage("Could not start selected-document Concordance", error));
    },
  });
  const trackedBatchConcordanceJobs = useMemo(
    () => (batchConcordanceRunId ? citationJobs.filter((job) => job.run_id === batchConcordanceRunId) : []),
    [batchConcordanceRunId, citationJobs],
  );
  const batchConcordanceBusy =
    batchConcordance.isPending ||
    Boolean(batchConcordanceRunId && (!trackedBatchConcordanceJobs.length || trackedBatchConcordanceJobs.some((job) => isActiveConcordanceStatus(job.status))));
  useEffect(() => {
    if (!confirmBatchConcordance) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConfirmBatchConcordance(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [confirmBatchConcordance]);
  useEffect(() => {
    if (!batchConcordanceRunId || trackedBatchConcordanceJobs.length === 0) return;
    if (trackedBatchConcordanceJobs.some((job) => isActiveConcordanceStatus(job.status))) return;
    const failedJob = trackedBatchConcordanceJobs.find((job) => job.status === "failed");
    if (failedJob) {
      batchConcordanceFeedback.showError(
        actionFailureMessage("Selected-document Concordance failed", failedJob.last_error || "Concordance job failed without a detailed error"),
      );
    } else {
      batchConcordanceFeedback.showSuccess();
    }
    setBatchConcordanceRunId(null);
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
    void queryClient.invalidateQueries({ queryKey: ["document"] });
  }, [batchConcordanceFeedback.showError, batchConcordanceFeedback.showSuccess, batchConcordanceRunId, queryClient, trackedBatchConcordanceJobs]);
  const paneStyle = {
    "--filter-pane-width": `${filterWidth}px`,
    "--detail-pane-width": `${detailWidth}px`,
  } as CSSProperties;
  const allVisibleSelected = documents.length > 0 && documents.every((item) => selectedIds.includes(item.id));
  const sortedTags = useMemo(() => [...tags].sort((left, right) => left.name.localeCompare(right.name)), [tags]);
  const sortedProjects = useMemo(() => [...projects].sort((left, right) => left.name.localeCompare(right.name)), [projects]);
  const hasBulkUpdate = Boolean(
    bulkReadStatus || bulkPriority || bulkTagIds.length || bulkCustomTag.trim() || bulkDomainId || bulkProjectIds.length,
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
          startConcordanceRun={startConcordanceRun}
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
                <option value="" disabled hidden>
                  Read status
                </option>
                <option value="unread">Unread</option>
                <option value="skimmed">Skimmed</option>
                <option value="read">Read</option>
              </select>
              <select value={bulkPriority} onChange={(event) => setBulkPriority(event.target.value)}>
                <option value="" disabled hidden>
                  Priority
                </option>
                <option value="urgent">Urgent</option>
                <option value="high">High</option>
                <option value="normal">Normal</option>
                <option value="low">Low</option>
              </select>
              <BulkMultiSelect
                emptyLabel="No tags"
                extraCount={bulkCustomTag.trim() ? 1 : 0}
                footer={
                  <input
                    className="bulk-custom-tag"
                    placeholder="New tag"
                    value={bulkCustomTag}
                    onChange={(event) => setBulkCustomTag(event.target.value)}
                  />
                }
                label="Tags"
                onChange={setBulkTagIds}
                options={sortedTags}
                selectedIds={bulkTagIds}
              />
              <select value={bulkDomainId} onChange={(event) => setBulkDomainId(event.target.value)}>
                <option value="" disabled hidden>
                  Domain
                </option>
                {domains.map((domain) => (
                  <option key={domain.id} value={domain.id}>
                    {domain.name}
                  </option>
                ))}
              </select>
              <BulkMultiSelect
                emptyLabel="No projects"
                label="Project"
                onChange={setBulkProjectIds}
                options={sortedProjects}
                selectedIds={bulkProjectIds}
              />
              <button className="primary-button" disabled={!hasBulkUpdate || bulkUpdate.isPending} onClick={() => bulkUpdate.mutate()}>
                <CheckSquare size={15} />
                Apply
              </button>
              <AsyncActionSlot busy={batchConcordanceBusy} feedback={batchConcordanceFeedback.feedback} label="Selected-document Concordance in progress">
                <button
                  className={asyncFeedbackClass("secondary-button", batchConcordanceFeedback.feedback, batchConcordanceBusy)}
                  disabled={batchConcordanceBusy}
                  onClick={() => setConfirmBatchConcordance(true)}
                >
                  <RefreshCw className={batchConcordanceBusy ? "spin" : ""} size={15} />
                  {batchConcordanceBusy ? "Concording" : "Concord"}
                </button>
              </AsyncActionSlot>
            </div>
          ) : null}
        </div>
        {confirmBatchConcordance ? (
          <div
            className="confirm-backdrop"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) setConfirmBatchConcordance(false);
            }}
          >
            <section aria-labelledby="confirm-concordance-title" aria-modal="true" className="confirm-dialog" role="dialog">
              <div className="confirm-dialog-heading">
                <div>
                  <h2 id="confirm-concordance-title">Confirm Concordance</h2>
                  <span>
                    {selectedIds.length} selected {selectedIds.length === 1 ? "document" : "documents"}
                  </span>
                </div>
                <RefreshCw size={20} />
              </div>
              <p>
                You're about to start a Concordance Run for the selected documents. Depending on your current model settings, this can queue AI
                processing and incur cost.
              </p>
              <div className="confirm-dialog-actions">
                <button className="secondary-button" onClick={() => setConfirmBatchConcordance(false)} type="button">
                  Cancel
                </button>
                <button
                  className="primary-button"
                  disabled={batchConcordanceBusy}
                  onClick={() => {
                    setConfirmBatchConcordance(false);
                    batchConcordance.mutate();
                  }}
                  type="button"
                >
                  Confirm
                </button>
              </div>
            </section>
          </div>
        ) : null}
        <div className={`rows ${alternatingRows ? "alternating-rows" : ""}`}>
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
                <span className="doc-row-title">{item.title}</span>
                <span className="doc-row-byline">
                  <span className="doc-row-pages">{pageCountMarker(item)}</span>
                  <span className="doc-row-year">{item.publication_year || "n.d."}</span>
                  <span className="doc-row-authors">{authorLine(item)}</span>
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
        preferences={preferences}
        projects={projects}
        query={query}
        startConcordanceRun={startConcordanceRun}
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

type ReaderMode = "pdf" | "text" | "compare";
type CitationKind = "reference" | "in-text";

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
  preferences,
  projects,
  query,
  readerExpanded = false,
  startConcordanceRun,
  tags,
}: {
  citationJobs: ConcordanceJob[];
  document?: DocumentDetail;
  domains: Domain[];
  onCloseReader?: () => void;
  onOpenReader?: () => void;
  preferences?: AppPreferences;
  projects: Project[];
  query: string;
  readerExpanded?: boolean;
  startConcordanceRun: StartConcordanceRun;
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
      preferences={preferences}
      projects={projects}
      query={query}
      readerExpanded={readerExpanded}
      startConcordanceRun={startConcordanceRun}
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
  const refreshFeedback = useAsyncActionFeedback();
  const selectedDownloadFeedback = useAsyncActionFeedback();
  const newDownloadFeedback = useAsyncActionFeedback();
  const recommendations = useQuery({
    queryKey: ["document-recommendations", document.id, hideExisting],
    queryFn: () => api.documentRecommendations(document.id, hideExisting),
    enabled: document.processing_status === "ready" && Boolean(document.doi),
  });
  const refresh = useMutation({
    mutationFn: () => api.refreshDocumentRecommendations(document.id),
    onSuccess: (result) => {
      refreshFeedback.showSuccess();
      setNotice(`Found ${result.recommendation_count} related papers`);
      void queryClient.invalidateQueries({ queryKey: ["document-recommendations", document.id] });
    },
    onError: (error) => {
      const message = actionFailureMessage("Could not refresh recommendations", error);
      refreshFeedback.showError(message);
      setNotice(message);
    },
  });
  const download = useMutation({
    mutationFn: (body: { recommendation_ids?: string[]; mode?: "selected" | "new"; skip_existing?: boolean }) =>
      api.downloadRecommendations(document.id, body),
    onSuccess: (result, body) => {
      const feedback = body.mode === "new" ? newDownloadFeedback : selectedDownloadFeedback;
      feedback.showSuccess();
      setNotice(
        `Queued ${result.queued_count}; skipped ${result.skipped_existing_count}; unavailable ${result.unavailable_count}; failed ${result.failed_count}`,
      );
      setSelectedIds([]);
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["document-recommendations", document.id] });
    },
    onError: (error, body) => {
      const feedback = body?.mode === "new" ? newDownloadFeedback : selectedDownloadFeedback;
      const message = actionFailureMessage("Could not queue recommendation downloads", error);
      feedback.showError(message);
      setNotice(message);
    },
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
          <AsyncActionSlot feedback={refreshFeedback.feedback}>
            <button
              className={asyncFeedbackClass("secondary-button compact", refreshFeedback.feedback)}
              disabled={!canRefresh || refresh.isPending}
              onClick={() => refresh.mutate()}
              type="button"
            >
              <RefreshCw className={refresh.isPending ? "spin" : ""} size={14} />
              Refresh
            </button>
          </AsyncActionSlot>
        </div>
      </div>
      <div className="recommendations-download-row">
        <label className="select-all-row">
          <input type="checkbox" checked={allSelectableSelected} onChange={toggleAllSelectable} disabled={!selectableRows.length} />
          <strong>{selectedCount ? `${selectedCount} selected` : "Select new papers"}</strong>
        </label>
        <AsyncActionSlot feedback={selectedDownloadFeedback.feedback}>
          <button
            className={asyncFeedbackClass("secondary-button compact", selectedDownloadFeedback.feedback)}
            disabled={!selectedCount || !selectedDownloadable || download.isPending}
            onClick={() => download.mutate({ recommendation_ids: selectedIds, mode: "selected", skip_existing: true })}
            type="button"
          >
            <Download size={14} />
            Selected
          </button>
        </AsyncActionSlot>
        <AsyncActionSlot feedback={newDownloadFeedback.feedback}>
          <button
            className={asyncFeedbackClass("primary-button compact", newDownloadFeedback.feedback)}
            disabled={!newRows.length || !newDownloadable || download.isPending}
            onClick={() => download.mutate({ mode: "new", skip_existing: true })}
            type="button"
          >
            <Download size={14} />
            All new
          </button>
        </AsyncActionSlot>
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

function CompositionDialog({
  composition,
  document,
  loading,
  onClose,
}: {
  composition?: DocumentComposition;
  document: DocumentDetail;
  loading: boolean;
  onClose: () => void;
}) {
  const available = Boolean(composition?.available);
  const costEntries = composition?.cost_entries || [];
  const providerEntries = composition?.provider_breakdown || [];
  const localEntries = composition?.local_duration_entries || [];
  const pipeline = composition?.pipeline || [];
  const issues = composition?.errata || [];
  const pipelineGraph = useMemo(() => pipelineNodesAndEdges(pipeline), [pipeline]);
  const duration = formatDuration(composition?.total_duration_seconds);
  return (
    <div
      className="modal-backdrop composition-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="composition-dialog" role="dialog" aria-modal="true" aria-labelledby="composition-title">
        <div className="composition-head">
          <div>
            <span>Composition</span>
            <h2 id="composition-title">{document.title}</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} title="Close composition">
            <X size={18} />
          </button>
        </div>
        {loading ? (
          <div className="composition-empty">
            <RefreshCw className="spin" size={22} />
            <span>Loading composition</span>
          </div>
        ) : !available ? (
          <div className="composition-empty">
            <Info size={22} />
            <strong>Cost composition not available</strong>
            <span>This document was imported before composition tracking was available.</span>
          </div>
        ) : (
          <>
            <div className="composition-grid">
              <section className="composition-chart-panel">
                <div className="composition-section-title">
                  <div>
                    <h3>Cost Composition</h3>
                    <span>{duration ? `${duration} processing` : "Processing time unavailable"}</span>
                  </div>
                  <strong>{formatUsd(composition?.total_estimated_cost_usd)}</strong>
                </div>
                <div className="composition-pie-wrap">
                  <div className="composition-pie" style={{ background: compositionPieGradient(costEntries) }}>
                    <span>{formatUsd(composition?.total_estimated_cost_usd)}</span>
                  </div>
                  <div className="composition-legend">
                    {costEntries.length ? (
                      costEntries.map((entry, index) => (
                        <div key={`${entry.provider}-${entry.model}-${entry.stage_key}`} className="composition-legend-row">
                          <i style={{ background: COMPOSITION_COLORS[index % COMPOSITION_COLORS.length] }} />
                          <span>{compositionLabel(entry)}</span>
                          <strong>{formatUsd(entry.amount_usd)}</strong>
                        </div>
                      ))
                    ) : (
                      <span>No dollar-cost model calls recorded.</span>
                    )}
                  </div>
                </div>
              </section>
              <section className="composition-provider-panel">
                <div className="composition-section-title">
                  <h3>Provider Spend</h3>
                </div>
                {providerEntries.length ? (
                  <div className="composition-provider-list">
                    {providerEntries.map((entry) => (
                      <div key={entry.provider || "unknown"} className="composition-provider-row">
                        <span>{entry.provider}</span>
                        <strong>{formatUsd(entry.amount_usd)}</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p>No provider spend recorded.</p>
                )}
              </section>
            </div>
            <section className="composition-section">
              <div className="composition-section-title">
                <h3>Local Time</h3>
              </div>
              <div className="composition-local-grid">
                {localEntries.length ? (
                  localEntries.map((entry) => (
                    <div key={`${entry.stage_key}-${entry.method}`} className="composition-local-row">
                      <span>{entry.stage_label}</span>
                      <strong>{formatDurationMs(entry.duration_ms) || "0s"}</strong>
                      <small>{entry.method || "local"}</small>
                    </div>
                  ))
                ) : (
                  <span>No local timing records.</span>
                )}
              </div>
            </section>
            <section className="composition-section">
              <div className="composition-section-title">
                <h3>Pipeline</h3>
                <span>{pipeline.length ? `${pipeline.length} recorded steps` : "No recorded steps"}</span>
              </div>
              {pipeline.length ? (
                <div className="composition-flow-chart">
                  <ReactFlow
                    colorMode="system"
                    edges={pipelineGraph.edges}
                    elementsSelectable={false}
                    defaultViewport={{ x: 24, y: 34, zoom: 1 }}
                    maxZoom={1.3}
                    minZoom={0.55}
                    nodeTypes={compositionPipelineNodeTypes}
                    nodes={pipelineGraph.nodes}
                    nodesConnectable={false}
                    nodesDraggable={false}
                    onlyRenderVisibleElements
                    panOnDrag
                    preventScrolling={false}
                    proOptions={{ hideAttribution: true }}
                    zoomOnDoubleClick={false}
                    zoomOnScroll={false}
                  >
                    <Background gap={20} size={1} />
                    <Controls position="bottom-right" showInteractive={false} />
                  </ReactFlow>
                </div>
              ) : (
                <div className="composition-empty compact">
                  <Info size={18} />
                  <span>No pipeline steps recorded.</span>
                </div>
              )}
            </section>
            {issues.length ? (
              <section className="composition-section">
                <div className="composition-section-title">
                  <h3>Processing Issues</h3>
                </div>
                <div className="composition-issue-list">
                  {issues.map((entry, index) => (
                    <div key={`${entry.stage_key}-${index}`} className="composition-issue-row">
                      <strong>{entry.stage_label || entry.label}</strong>
                      <span>{entry.message || entry.status}</span>
                      <small>{[entry.status, entry.provider, entry.model || entry.method].filter(Boolean).join(" / ")}</small>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}

function DocumentPanelContent({
  citationJobs,
  document,
  domains,
  onCloseReader,
  onOpenReader,
  preferences,
  projects,
  query,
  readerExpanded = false,
  startConcordanceRun,
  tags,
}: {
  citationJobs: ConcordanceJob[];
  document: DocumentDetail;
  domains: Domain[];
  onCloseReader?: () => void;
  onOpenReader?: () => void;
  preferences?: AppPreferences;
  projects: Project[];
  query: string;
  readerExpanded?: boolean;
  startConcordanceRun: StartConcordanceRun;
  tags: Tag[];
}) {

  const [editing, setEditing] = useState(false);
  const [recommendationsOpen, setRecommendationsOpen] = useState(false);
  const [compositionOpen, setCompositionOpen] = useState(false);
  const [readerMode, setReaderMode] = useState<ReaderMode>(() => (readerExpanded ? "compare" : "pdf"));
  const [readerPageIndex, setReaderPageIndex] = useState(0);
  const comparePdfRef = useRef<HTMLIFrameElement | null>(null);
  const compareTextRef = useRef<HTMLElement | null>(null);
  const syncScrollSourceRef = useRef<"pdf" | "text" | null>(null);
  const [editingPageId, setEditingPageId] = useState<string | null>(null);
  const [pageTextDraft, setPageTextDraft] = useState("");
  const [pageTextError, setPageTextError] = useState<string | null>(null);
  const [pageTextSelection, setPageTextSelection] = useState("");
  const [pdfScrollListenerTick, setPdfScrollListenerTick] = useState(0);
  const [draft, setDraft] = useState<DocumentDraft>(() => draftFromDocument(document));
  const accessorySummaryTask = preferences?.analysis_model_tasks.find((task) => task.key === ACCESSORY_SUMMARIES_MODEL_KEY);
  const accessorySummaryDefaultModel =
    preferences?.analysis_models[ACCESSORY_SUMMARIES_MODEL_KEY] || accessorySummaryTask?.selected_model || accessorySummaryTask?.default_model || "gpt-5.4";
  const [accessoryComposerOpen, setAccessoryComposerOpen] = useState(false);
  const [accessoryPrompt, setAccessoryPrompt] = useState("");
  const [accessoryModel, setAccessoryModel] = useState(accessorySummaryDefaultModel);
  const [trackedAccessorySummaryId, setTrackedAccessorySummaryId] = useState<string | null>(null);
  const [accessoryTitleDrafts, setAccessoryTitleDrafts] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [documentConcordanceRunId, setDocumentConcordanceRunId] = useState<string | null>(null);
  const [citationRunId, setCitationRunId] = useState<string | null>(null);
  const [citationRefreshTarget, setCitationRefreshTarget] = useState<CitationKind | null>(null);
  const [editingCitation, setEditingCitation] = useState<CitationKind | null>(null);
  const [citationDrafts, setCitationDrafts] = useState<Record<CitationKind, string>>({
    reference: document.apa_citation || "",
    "in-text": document.apa_in_text_citation || "",
  });
  const [citationEditError, setCitationEditError] = useState<string | null>(null);
  const [selectedHistoryVersionId, setSelectedHistoryVersionId] = useState<string | null>(null);
  const [historyRestoreError, setHistoryRestoreError] = useState<string | null>(null);
  const { copiedKey, copyToClipboard } = useClipboardNotice();
  const queryClient = useQueryClient();
  const runConcordanceFeedback = useAsyncActionFeedback();
  const referenceCitationFeedback = useAsyncActionFeedback();
  const inTextCitationFeedback = useAsyncActionFeedback();
  const accessorySummaryFeedback = useAsyncActionFeedback();
  const composition = useQuery({
    queryKey: ["document-composition", document.id],
    queryFn: () => api.documentComposition(document.id),
    enabled: compositionOpen,
  });
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
  const updatePageText = useMutation({
    mutationFn: ({ pageId, normalizedText }: { pageId: string; normalizedText: string }) =>
      api.updateDocumentPageText(document.id, pageId, { normalized_text: normalizedText }),
    onSuccess: () => {
      setEditingPageId(null);
      setPageTextError(null);
      setPageTextSelection("");
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setPageTextError(actionFailureMessage("Could not save extracted text", error)),
  });
  const scrubText = useMutation({
    mutationFn: (text: string) => api.scrubDocumentText(document.id, { text }),
    onSuccess: (updatedDocument) => {
      setPageTextError(null);
      setPageTextSelection("");
      const updatedPage = updatedDocument.pages.find((page) => page.id === currentPage?.id);
      if (updatedPage) setPageTextDraft(updatedPage.normalized_text ?? updatedPage.text ?? "");
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setPageTextError(actionFailureMessage("Could not scrub extracted text", error)),
  });
  const restoreHistoryVersion = useMutation({
    mutationFn: (versionId: string) => api.restoreDocumentVersion(document.id, versionId),
    onSuccess: () => {
      setHistoryRestoreError(null);
      setSelectedHistoryVersionId(null);
      setEditingPageId(null);
      setPageTextSelection("");
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
      void queryClient.invalidateQueries({ queryKey: ["domains"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setHistoryRestoreError(actionFailureMessage("Could not restore history version", error)),
  });
  const runConcordance = useMutation({
    mutationFn: () =>
      startConcordanceRun({
        backgroundDetail: document.title,
        backgroundLabel: "Document Concordance",
        label: `Document Concordance: ${document.title}`,
        scope_type: "documents",
        scope_data: { document_ids: [document.id] },
        documentId: document.id,
      }),
    onSuccess: (run) => {
      if (run.total_jobs > 0) setDocumentConcordanceRunId(run.id);
      else runConcordanceFeedback.showSuccess();
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-jobs"] });
    },
    onError: (error) => {
      setDocumentConcordanceRunId(null);
      runConcordanceFeedback.showError(actionFailureMessage("Could not start document Concordance", error));
    },
  });
  const refreshCitation = useMutation({
    mutationFn: (target: CitationKind) =>
      startConcordanceRun({
        backgroundDetail: document.title,
        backgroundLabel: "Checking APA citation",
        capability_keys: ["citation_refresh"],
        capabilityKey: "citation_refresh",
        documentId: document.id,
        force: true,
        label: `Citation check: ${document.title}`,
        scope_data: { document_ids: [document.id] },
        scope_type: "documents",
      }),
    onSuccess: (run, target) => {
      setCitationRefreshTarget(target);
      const feedback = target === "reference" ? referenceCitationFeedback : inTextCitationFeedback;
      if (run.total_jobs > 0) setCitationRunId(run.id);
      else feedback.showSuccess();
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["review"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
    },
    onError: (error, target) => {
      setCitationRunId(null);
      setCitationRefreshTarget(null);
      const feedback = target === "in-text" ? inTextCitationFeedback : referenceCitationFeedback;
      feedback.showError(actionFailureMessage("Could not start citation check", error));
    },
  });
  const updateCitation = useMutation({
    mutationFn: ({ kind, value }: { kind: CitationKind; value: string }) =>
      api.updateDocument(document.id, kind === "reference" ? { apa_citation: value.trim() || null } : { apa_in_text_citation: value.trim() || null }),
    onSuccess: () => {
      setEditingCitation(null);
      setCitationEditError(null);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setCitationEditError(actionFailureMessage("Could not save citation", error)),
  });
  const deleteAnnotation = useMutation({
    mutationFn: (annotationId: string) => api.deleteAnnotation(annotationId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
  const createAccessorySummary = useMutation({
    mutationFn: () =>
      api.createAccessorySummary(document.id, {
        prompt: accessoryPrompt.trim(),
        model: accessoryModel || accessorySummaryDefaultModel,
      }),
    onSuccess: (summary) => {
      setTrackedAccessorySummaryId(summary.id);
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["openai-usage"] });
    },
    onError: (error) => {
      accessorySummaryFeedback.showError(actionFailureMessage("Could not queue accessory summary", error));
    },
  });
  const updateAccessorySummary = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => api.updateAccessorySummary(id, { title }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
    },
  });

  useEffect(() => {
    setDraft(draftFromDocument(document));
    setReaderPageIndex(0);
    setEditing(false);
    setRecommendationsOpen(false);
    setCompositionOpen(false);
    setAccessoryComposerOpen(false);
    setAccessoryPrompt("");
    setAccessoryTitleDrafts({});
    setTrackedAccessorySummaryId(null);
    setSaveError(null);
    setEditingPageId(null);
    setPageTextDraft("");
    setPageTextError(null);
    setPageTextSelection("");
    setDocumentConcordanceRunId(null);
    setCitationRunId(null);
    setCitationRefreshTarget(null);
    setEditingCitation(null);
    setCitationDrafts({ reference: document.apa_citation || "", "in-text": document.apa_in_text_citation || "" });
    setCitationEditError(null);
    setSelectedHistoryVersionId(null);
    setHistoryRestoreError(null);
  }, [document.id]);

  useEffect(() => {
    if (editingCitation) return;
    setCitationDrafts({ reference: document.apa_citation || "", "in-text": document.apa_in_text_citation || "" });
  }, [document.apa_citation, document.apa_in_text_citation, editingCitation]);

  useEffect(() => {
    setAccessoryModel(accessorySummaryDefaultModel);
  }, [accessorySummaryDefaultModel, document.id]);

  const copyCitation = (kind: CitationKind) => {
    const text = citationText(document, kind);
    if (text) void copyToClipboard(`citation-${kind}`, decodeHtmlEntities(text));
  };
  const pages = useMemo(
    () => [...(document.pages || [])].sort((left, right) => left.page_number - right.page_number),
    [document.pages],
  );
  const pageReadableText = (page: (typeof pages)[number]) => page.normalized_text ?? page.text ?? "";
  const fullText = pages.map(pageReadableText).filter(Boolean).join("\n\n");
  const currentPageIndex = pages.length ? Math.min(readerPageIndex, pages.length - 1) : 0;
  const currentPage = pages[currentPageIndex];
  const currentPageText = currentPage ? pageReadableText(currentPage) : "";
  const pageTextEditing = Boolean(currentPage && editingPageId === currentPage.id);
  const currentPageSource = currentPage
    ? currentPage.normalized_text !== null && currentPage.normalized_text !== undefined
      ? currentPage.text_source === "manual"
        ? "manual"
        : "normalized"
      : currentPage.text_source
    : "";
  const pageTextBusy = updatePageText.isPending || scrubText.isPending;
  const scrubNeedle = pageTextSelection.trim() ? pageTextSelection : "";
  const scrubMatchCount = useMemo(
    () => (scrubNeedle ? pages.reduce((count, page) => count + countOccurrences(pageReadableText(page), scrubNeedle), 0) : 0),
    [pages, scrubNeedle],
  );
  const scrubButtonLabel = scrubMatchCount > 0 ? `Scrub (${scrubMatchCount})` : "Scrub";
  const historyRows = useMemo(
    () => [...(document.versions || [])].sort((left, right) => right.version_number - left.version_number),
    [document.versions],
  );
  const selectedHistoryIndex = historyRows.length
    ? Math.max(
        0,
        selectedHistoryVersionId ? historyRows.findIndex((version) => version.id === selectedHistoryVersionId) : 0,
      )
    : -1;
  const selectedHistoryVersion = selectedHistoryIndex >= 0 ? historyRows[selectedHistoryIndex] : undefined;
  const selectedHistoryChangedFields = selectedHistoryVersion ? changedFieldsForVersion(selectedHistoryVersion) : [];
  const selectedHistoryPreviewLines = selectedHistoryVersion ? versionPreviewLines(selectedHistoryVersion) : [];
  const selectedHistoryRestorable = selectedHistoryVersion ? versionIsRestorable(selectedHistoryVersion) : false;
  const citationRefreshActive = citationJobs.some(
    (job) => job.document_id === document.id && job.capability_key === "citation_refresh" && isActiveConcordanceStatus(job.status),
  );
  const trackedDocumentConcordanceJobs = useMemo(
    () => (documentConcordanceRunId ? citationJobs.filter((job) => job.run_id === documentConcordanceRunId && job.document_id === document.id) : []),
    [citationJobs, document.id, documentConcordanceRunId],
  );
  const trackedCitationJobs = useMemo(
    () =>
      citationRunId
        ? citationJobs.filter(
            (job) => job.run_id === citationRunId && job.document_id === document.id && job.capability_key === "citation_refresh",
          )
        : [],
    [citationJobs, citationRunId, document.id],
  );
  const documentConcordanceBusy =
    runConcordance.isPending ||
    Boolean(
      documentConcordanceRunId &&
        (!trackedDocumentConcordanceJobs.length || trackedDocumentConcordanceJobs.some((job) => isActiveConcordanceStatus(job.status))),
    );
  const citationBusy = refreshCitation.isPending || citationRefreshActive || Boolean(citationRunId);
  const accessorySummaries = document.accessory_summaries || [];
  const trackedAccessorySummary = trackedAccessorySummaryId
    ? accessorySummaries.find((summary) => summary.id === trackedAccessorySummaryId)
    : undefined;
  const accessorySummaryBusy =
    createAccessorySummary.isPending ||
    Boolean(
      trackedAccessorySummaryId &&
        (!trackedAccessorySummary || isActiveAccessorySummaryStatus(trackedAccessorySummary.status)),
    );

  useEffect(() => {
    if (!documentConcordanceRunId || trackedDocumentConcordanceJobs.length === 0) return;
    if (trackedDocumentConcordanceJobs.some((job) => isActiveConcordanceStatus(job.status))) return;
    const failedJob = trackedDocumentConcordanceJobs.find((job) => job.status === "failed");
    if (failedJob) {
      runConcordanceFeedback.showError(
        actionFailureMessage("Document Concordance failed", failedJob.last_error || "Concordance job failed without a detailed error"),
      );
    } else {
      runConcordanceFeedback.showSuccess();
    }
    setDocumentConcordanceRunId(null);
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
    void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
  }, [
    document.id,
    documentConcordanceRunId,
    queryClient,
    runConcordanceFeedback.showError,
    runConcordanceFeedback.showSuccess,
    trackedDocumentConcordanceJobs,
  ]);

  useEffect(() => {
    if (!citationRunId || trackedCitationJobs.length === 0) return;
    if (trackedCitationJobs.some((job) => isActiveConcordanceStatus(job.status))) return;
    const failedJob = trackedCitationJobs.find((job) => job.status === "failed");
    const feedback = citationRefreshTarget === "in-text" ? inTextCitationFeedback : referenceCitationFeedback;
    if (failedJob) {
      feedback.showError(
        actionFailureMessage("Citation check failed", failedJob.last_error || "Concordance job failed without a detailed error"),
      );
    } else {
      feedback.showSuccess();
    }
    setCitationRunId(null);
    setCitationRefreshTarget(null);
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["review"] });
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
    void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
  }, [
    citationRefreshTarget,
    citationRunId,
    document.id,
    inTextCitationFeedback,
    queryClient,
    referenceCitationFeedback,
    trackedCitationJobs,
  ]);

  useEffect(() => {
    if (!trackedAccessorySummaryId || !trackedAccessorySummary) return;
    if (isActiveAccessorySummaryStatus(trackedAccessorySummary.status)) return;
    if (trackedAccessorySummary.status === "failed") {
      accessorySummaryFeedback.showError(
        actionFailureMessage("Accessory summary failed", trackedAccessorySummary.last_error || "The accessory summary failed without a detailed error"),
      );
      setTrackedAccessorySummaryId(null);
      return;
    }
    accessorySummaryFeedback.showSuccess();
    setAccessoryComposerOpen(false);
    setAccessoryPrompt("");
    setTrackedAccessorySummaryId(null);
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
    void queryClient.invalidateQueries({ queryKey: ["openai-usage"] });
  }, [
    accessorySummaryFeedback.showError,
    accessorySummaryFeedback.showSuccess,
    queryClient,
    trackedAccessorySummary,
    trackedAccessorySummaryId,
  ]);

  useEffect(() => {
    if (!currentPage || editingPageId === currentPage.id) return;
    setPageTextDraft(currentPageText);
    setPageTextError(null);
    setPageTextSelection("");
  }, [currentPage?.id, currentPageText, editingPageId]);

  const scrollRatioFor = (element: Element | null) => {
    if (!element) return 0;
    const maximum = element.scrollHeight - element.clientHeight;
    return maximum > 0 ? element.scrollTop / maximum : 0;
  };

  const applyScrollRatio = (element: Element | null, ratio: number) => {
    if (!element) return;
    const maximum = element.scrollHeight - element.clientHeight;
    element.scrollTop = maximum > 0 ? maximum * ratio : 0;
  };

  const pdfScrollElement = () => {
    try {
      const frameDocument = comparePdfRef.current?.contentDocument;
      return frameDocument?.scrollingElement || frameDocument?.documentElement || frameDocument?.body || null;
    } catch {
      return null;
    }
  };

  const releaseScrollSync = () => {
    window.requestAnimationFrame(() => {
      syncScrollSourceRef.current = null;
    });
  };

  const handleCompareTextScroll = () => {
    if (readerMode !== "compare" || syncScrollSourceRef.current === "pdf") return;
    const target = pdfScrollElement();
    if (!target) return;
    syncScrollSourceRef.current = "text";
    applyScrollRatio(target, scrollRatioFor(compareTextRef.current));
    releaseScrollSync();
  };

  const handleComparePdfScroll = useCallback(() => {
    if (readerMode !== "compare" || syncScrollSourceRef.current === "text") return;
    const source = pdfScrollElement();
    if (!source) return;
    syncScrollSourceRef.current = "pdf";
    applyScrollRatio(compareTextRef.current, scrollRatioFor(source));
    releaseScrollSync();
  }, [readerMode]);

  useEffect(() => {
    if (readerMode !== "compare") return;
    const frameWindow = comparePdfRef.current?.contentWindow;
    const frameDocument = comparePdfRef.current?.contentDocument;
    if (!frameWindow && !frameDocument) return;
    frameWindow?.addEventListener("scroll", handleComparePdfScroll, { passive: true });
    frameDocument?.addEventListener("scroll", handleComparePdfScroll, { passive: true });
    return () => {
      frameWindow?.removeEventListener("scroll", handleComparePdfScroll);
      frameDocument?.removeEventListener("scroll", handleComparePdfScroll);
    };
  }, [document.id, readerMode, currentPage?.id, handleComparePdfScroll, pdfScrollListenerTick]);

  const copyFullText = () => {
    if (fullText) void copyToClipboard("full-text", fullText);
  };

  const startPageTextEdit = () => {
    if (!currentPage) return;
    setEditingPageId(currentPage.id);
    setPageTextDraft(currentPageText);
    setPageTextError(null);
    setPageTextSelection("");
  };

  const cancelPageTextEdit = () => {
    setEditingPageId(null);
    setPageTextDraft(currentPageText);
    setPageTextError(null);
    setPageTextSelection("");
  };

  const savePageTextEdit = () => {
    if (!currentPage || !pageTextEditing) return;
    updatePageText.mutate({ pageId: currentPage.id, normalizedText: pageTextDraft });
  };

  const updatePageTextSelection = (textarea: HTMLTextAreaElement) => {
    const start = textarea.selectionStart ?? 0;
    const end = textarea.selectionEnd ?? 0;
    setPageTextSelection(start === end ? "" : textarea.value.slice(Math.min(start, end), Math.max(start, end)));
  };

  const scrubSelectedText = () => {
    if (!scrubNeedle || scrubMatchCount <= 0 || pageTextBusy) return;
    scrubText.mutate(scrubNeedle);
  };

  const selectHistoryOffset = (offset: number) => {
    if (!historyRows.length || selectedHistoryIndex < 0) return;
    const nextIndex = Math.min(historyRows.length - 1, Math.max(0, selectedHistoryIndex + offset));
    setSelectedHistoryVersionId(historyRows[nextIndex].id);
    setHistoryRestoreError(null);
  };

  const restoreSelectedHistoryVersion = () => {
    if (!selectedHistoryVersion || !selectedHistoryRestorable || restoreHistoryVersion.isPending) return;
    restoreHistoryVersion.mutate(selectedHistoryVersion.id);
  };

  const startCitationEdit = (kind: CitationKind) => {
    setCitationDrafts((current) => ({ ...current, [kind]: citationText(document, kind) }));
    setCitationEditError(null);
    setEditingCitation(kind);
  };

  const cancelCitationEdit = () => {
    setCitationDrafts({ reference: document.apa_citation || "", "in-text": document.apa_in_text_citation || "" });
    setCitationEditError(null);
    setEditingCitation(null);
  };

  const saveCitationEdit = (kind: CitationKind) => {
    updateCitation.mutate({ kind, value: citationDrafts[kind] || "" });
  };

  const citationFeedbackFor = (kind: CitationKind) => (kind === "reference" ? referenceCitationFeedback.feedback : inTextCitationFeedback.feedback);
  const citationButtonBusy = (kind: CitationKind) => citationBusy && citationRefreshTarget === kind;
  const checkCitation = (kind: CitationKind) => {
    setCitationRefreshTarget(kind);
    refreshCitation.mutate(kind);
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

  const submitAccessorySummary = () => {
    if (!accessoryPrompt.trim() || accessorySummaryBusy) return;
    createAccessorySummary.mutate();
  };

  const saveAccessorySummaryTitle = (summary: AccessorySummary) => {
    const title = accessoryTitleDrafts[summary.id] ?? summary.title ?? "";
    updateAccessorySummary.mutate({ id: summary.id, title });
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
  const annotations = document.annotations || [];
  const accessoryModelOptions = preferences?.model_options[accessorySummaryTask?.model_kind || "gpt"] || [];
  const renderCitationSection = (kind: CitationKind, title: string, empty: string) => {
    const text = citationText(document, kind);
    const isEditing = editingCitation === kind;
    const busy = citationButtonBusy(kind);
    const feedback = citationFeedbackFor(kind);
    return (
      <section className="detail-section citation-section">
        <h3>{title}</h3>
        {isEditing ? (
          <form
            className="citation-editor"
            onSubmit={(event) => {
              event.preventDefault();
              saveCitationEdit(kind);
            }}
          >
            <textarea
              aria-label={`${title} text`}
              value={citationDrafts[kind]}
              onChange={(event) => setCitationDrafts((current) => ({ ...current, [kind]: event.target.value }))}
            />
            <div className="citation-editor-actions">
              <button className="primary-button compact" disabled={updateCitation.isPending} type="submit">
                <Save size={14} />
                Save
              </button>
              <button className="secondary-button compact" disabled={updateCitation.isPending} onClick={cancelCitationEdit} type="button">
                <X size={14} />
                Cancel
              </button>
            </div>
            {citationEditError ? <p className="form-error">{citationEditError}</p> : null}
          </form>
        ) : (
          <MarkdownBlock content={text} empty={empty} />
        )}
        <div className="citation-actions">
          <button className="secondary-button" onClick={() => copyCitation(kind)} disabled={!text} type="button">
            {copiedKey === `citation-${kind}` ? <CheckCircle2 size={15} /> : <Clipboard size={15} />}
            {copiedKey === `citation-${kind}` ? "Copied" : "Copy"}
          </button>
          <button className="secondary-button" onClick={() => startCitationEdit(kind)} disabled={updateCitation.isPending || isEditing} type="button">
            <Edit3 size={15} />
            Edit
          </button>
          <AsyncActionSlot busy={busy} feedback={feedback} label="Citation check in progress">
            <button
              className={asyncFeedbackClass("secondary-button", feedback, busy)}
              onClick={() => checkCitation(kind)}
              disabled={citationBusy}
              type="button"
            >
              <RefreshCw className={busy ? "spin" : ""} size={15} />
              {busy ? "Checking" : "Check"}
            </button>
          </AsyncActionSlot>
          <span className="citation-model-label">{citationProvenanceLabel(document, kind)}</span>
        </div>
      </section>
    );
  };
  const renderPdfPreview = (compare = false) => {
    const fragment = compare && currentPage ? `#page=${currentPage.page_number}&toolbar=0&navpanes=0` : "#toolbar=0&navpanes=0";
    return (
      <div className={`pdf-preview ${compare ? "compare-pane" : ""}`}>
        <iframe
          ref={compare ? comparePdfRef : undefined}
          title={`PDF preview for ${document.title}`}
          src={`/api/documents/${document.id}/original${fragment}`}
          onLoad={
            compare
              ? () => {
                  setPdfScrollListenerTick((value) => value + 1);
                  handleCompareTextScroll();
                }
              : undefined
          }
        />
        <div className="pdf-preview-meta">
          <FileSearch size={16} />
          <span>{document.page_count || "?"} pages</span>
        </div>
      </div>
    );
  };

  const renderTextReader = (compare = false) => (
    <section className={`text-reader ${compare ? "compare-pane" : ""}`}>
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
            disabled={!pages.length || currentPageIndex === 0 || pageTextBusy}
            onClick={() => setReaderPageIndex((index) => Math.max(0, index - 1))}
          >
            <ChevronLeft size={18} />
          </button>
          <span className="page-counter">{pages.length ? `${currentPage?.page_number ?? currentPageIndex + 1} / ${pages.length}` : "0 / 0"}</span>
          <button
            className="icon-button reader-arrow"
            type="button"
            title="Next page"
            disabled={!pages.length || currentPageIndex >= pages.length - 1 || pageTextBusy}
            onClick={() => setReaderPageIndex((index) => Math.min(pages.length - 1, index + 1))}
          >
            <ChevronRight size={18} />
          </button>
          <button className="secondary-button compact" onClick={copyFullText} disabled={!fullText || pageTextBusy} type="button">
            {copiedKey === "full-text" ? <CheckCircle2 size={14} /> : <Clipboard size={14} />}
            {copiedKey === "full-text" ? "Copied" : "Copy"}
          </button>
          {!pageTextEditing ? (
            <button className="secondary-button compact" disabled={!currentPage || pageTextBusy} onClick={startPageTextEdit} type="button">
              <Edit3 size={14} />
              Edit
            </button>
          ) : null}
        </div>
      </div>
      {currentPage ? (
        <article
          className={`reader-page ${currentPage.low_text ? "low-text" : ""}`}
          ref={compare ? compareTextRef : undefined}
          onScroll={compare ? handleCompareTextScroll : undefined}
        >
          <header>
            <div>
              <strong>Page {currentPage.page_number}</strong>
              <span>
                {currentPageSource}
                {currentPage.low_text ? " / low text" : ""}
              </span>
            </div>
          </header>
          {pageTextEditing ? (
            <div className="reader-page-editor">
              <textarea
                aria-label={`Extracted text for page ${currentPage.page_number}`}
                disabled={pageTextBusy}
                onChange={(event) => {
                  setPageTextDraft(event.target.value);
                  updatePageTextSelection(event.currentTarget);
                }}
                onKeyUp={(event) => updatePageTextSelection(event.currentTarget)}
                onMouseUp={(event) => updatePageTextSelection(event.currentTarget)}
                onSelect={(event) => updatePageTextSelection(event.currentTarget)}
                value={pageTextDraft}
              />
              <div className="reader-editor-tools">
                <button
                  className="secondary-button compact"
                  disabled={!scrubNeedle || scrubMatchCount <= 0 || pageTextBusy}
                  onClick={scrubSelectedText}
                  type="button"
                >
                  <Eraser size={14} />
                  {scrubButtonLabel}
                </button>
                <span className="reader-tool-spacer" />
                <button className="primary-button compact" disabled={pageTextBusy} onClick={savePageTextEdit} type="button">
                  <Save size={14} />
                  Save
                </button>
                <button className="secondary-button compact" disabled={pageTextBusy} onClick={cancelPageTextEdit} type="button">
                  <X size={14} />
                  Cancel
                </button>
              </div>
              {pageTextError ? <p className="form-error">{pageTextError}</p> : null}
            </div>
          ) : (
            <pre>{currentPageText.trim() || "No extracted text."}</pre>
          )}
        </article>
      ) : (
        <div className="empty-inline">
          <FileText size={17} />
          <span>No parsed pages yet.</span>
        </div>
      )}
    </section>
  );

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
        <AsyncActionSlot busy={documentConcordanceBusy} feedback={runConcordanceFeedback.feedback} label="Document Concordance in progress">
          <button
            className={asyncFeedbackClass("secondary-button", runConcordanceFeedback.feedback, documentConcordanceBusy)}
            onClick={() => runConcordance.mutate()}
            disabled={documentConcordanceBusy}
          >
            <RefreshCw className={documentConcordanceBusy ? "spin" : ""} size={15} />
            {documentConcordanceBusy ? "Concording" : "Concord"}
          </button>
        </AsyncActionSlot>
        <button className="secondary-button" onClick={() => setCompositionOpen(true)} type="button">
          <PieChart size={15} />
          Composition
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
      {compositionOpen ? (
        <CompositionDialog
          composition={composition.data}
          document={document}
          loading={composition.isFetching && !composition.data}
          onClose={() => setCompositionOpen(false)}
        />
      ) : null}
      <div className="reader-tabs" role="tablist" aria-label="Document reader">
        <button className={readerMode === "pdf" ? "selected" : ""} type="button" onClick={() => setReaderMode("pdf")}>
          <FileSearch size={15} />
          PDF
        </button>
        <button className={readerMode === "text" ? "selected" : ""} type="button" onClick={() => setReaderMode("text")}>
          <FileText size={15} />
          Text
        </button>
        <button className={readerMode === "compare" ? "selected" : ""} type="button" onClick={() => setReaderMode("compare")}>
          <BookOpen size={15} />
          Compare
        </button>
      </div>
      {readerMode === "pdf" ? (
        renderPdfPreview()
      ) : readerMode === "compare" ? (
        <div className="reader-compare">
          {renderPdfPreview(true)}
          {renderTextReader(true)}
        </div>
      ) : (
        renderTextReader()
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
      {renderCitationSection("reference", "APA Reference List", "Needs review.")}
      {renderCitationSection("in-text", "APA In-Text Citation", "Needs review.")}
      {recommendationsOpen ? <RecommendationsPanel document={document} /> : null}
      <section className="detail-section">
        <h3>Summary</h3>
        <MarkdownBlock content={document.rich_summary} empty="Summary pending." />
      </section>
      <section className="detail-section accessory-summary-section">
        <div className="detail-section-title-row">
          <h3>Accessory Summaries</h3>
          <button
            className="secondary-button compact"
            disabled={accessorySummaryBusy}
            onClick={() => setAccessoryComposerOpen((value) => !value)}
            type="button"
          >
            {accessoryComposerOpen ? <X size={14} /> : <Plus size={14} />}
            {accessoryComposerOpen ? "Cancel" : "Add"}
          </button>
        </div>
        {accessoryComposerOpen ? (
          <form
            className="accessory-summary-composer"
            onSubmit={(event) => {
              event.preventDefault();
              submitAccessorySummary();
            }}
          >
            <textarea
              disabled={accessorySummaryBusy}
              onChange={(event) => setAccessoryPrompt(event.target.value)}
              placeholder="Ask a question or specify a focused topic"
              rows={6}
              value={accessoryPrompt}
            />
            <div className="accessory-summary-actions">
              <ModelSelect
                defaultModel={accessorySummaryDefaultModel}
                onChange={setAccessoryModel}
                optionGroups={accessorySummaryTask?.option_groups}
                options={accessoryModelOptions}
                value={accessoryModel || accessorySummaryDefaultModel}
              />
              <AsyncActionSlot busy={accessorySummaryBusy} feedback={accessorySummaryFeedback.feedback} label="Accessory summary in progress">
                <button
                  className={asyncFeedbackClass("primary-button", accessorySummaryFeedback.feedback, accessorySummaryBusy)}
                  disabled={accessorySummaryBusy || !accessoryPrompt.trim()}
                  type="submit"
                >
                  <Sparkles className={accessorySummaryBusy ? "spin" : ""} size={15} />
                  {accessorySummaryBusy ? "Summarizing" : "Summarize"}
                </button>
              </AsyncActionSlot>
            </div>
          </form>
        ) : null}
        {accessorySummaries.length ? (
          <div className="accessory-summary-list">
            {accessorySummaries.map((summary) => {
              const titleValue = accessoryTitleDrafts[summary.id] ?? summary.title ?? "";
              return (
                <article key={summary.id} className={`accessory-summary-card ${summary.status}`}>
                  <div className="accessory-summary-head">
                    <input
                      aria-label="Accessory summary title"
                      disabled={updateAccessorySummary.isPending}
                      onBlur={() => {
                        if (titleValue !== (summary.title ?? "")) saveAccessorySummaryTitle(summary);
                      }}
                      onChange={(event) =>
                        setAccessoryTitleDrafts((current) => ({ ...current, [summary.id]: event.target.value }))
                      }
                      placeholder="Title"
                      value={titleValue}
                    />
                    <StatusPill value={summary.status} tone={accessorySummaryTone(summary)} />
                  </div>
                  <p className="accessory-summary-prompt">{summary.prompt}</p>
                  {summary.status === "complete" ? (
                    <MarkdownBlock content={summary.summary} empty="Summary pending." />
                  ) : summary.status === "failed" ? (
                    <p className="form-error">{summary.last_error || "Accessory summary failed."}</p>
                  ) : (
                    <div className="empty-inline">
                      <RefreshCw className="spin" size={17} />
                      <span>{summary.status === "running" ? "Summarizing" : "Queued"}</span>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        ) : !accessoryComposerOpen ? (
          <div className="empty-inline">
            <Sparkles size={17} />
            <span>None yet.</span>
          </div>
        ) : null}
      </section>
      <section className="detail-section">
        <h3>Annotations</h3>
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
                <small>{figure.caption || figure.gist || "Extracted figure"}</small>
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
        {historyRows.length ? (
          <div className="history-browser">
            {selectedHistoryVersion ? (
              <div className="history-toolbar">
                <button
                  className="secondary-button compact"
                  disabled={selectedHistoryIndex <= 0 || restoreHistoryVersion.isPending}
                  onClick={() => selectHistoryOffset(-1)}
                  type="button"
                >
                  <ChevronLeft size={14} />
                  Newer
                </button>
                <span className="history-current">v{selectedHistoryVersion.version_number}</span>
                <button
                  className="secondary-button compact"
                  disabled={selectedHistoryIndex >= historyRows.length - 1 || restoreHistoryVersion.isPending}
                  onClick={() => selectHistoryOffset(1)}
                  type="button"
                >
                  Older
                  <ChevronRight size={14} />
                </button>
                <button
                  className="primary-button compact"
                  disabled={!selectedHistoryRestorable || restoreHistoryVersion.isPending}
                  onClick={restoreSelectedHistoryVersion}
                  type="button"
                >
                  <RotateCcw size={14} />
                  Restore as Current
                </button>
              </div>
            ) : null}
            {selectedHistoryVersion ? (
              <div className="history-preview">
                <strong>{selectedHistoryVersion.change_note || "Snapshot"}</strong>
                <span>
                  {selectedHistoryPreviewLines.length
                    ? selectedHistoryPreviewLines.join(" / ")
                    : selectedHistoryRestorable
                      ? `v${selectedHistoryVersion.version_number}`
                      : "No restorable fields"}
                </span>
                {selectedHistoryChangedFields.length ? <small>{selectedHistoryChangedFields.join(", ")}</small> : null}
              </div>
            ) : null}
            {historyRestoreError ? <p className="form-error">{historyRestoreError}</p> : null}
            <div className="history-list">
              {historyRows.map((version) => {
                const changedFields = changedFieldsForVersion(version);
                const selected = selectedHistoryVersion?.id === version.id;
                return (
                  <button
                    key={version.id}
                    className={`history-row ${selected ? "selected" : ""}`}
                    onClick={() => {
                      setSelectedHistoryVersionId(version.id);
                      setHistoryRestoreError(null);
                    }}
                    type="button"
                  >
                    <strong>v{version.version_number}</strong>
                    <span>
                      {version.change_note || "Snapshot"}
                      {changedFields.length ? ` / ${changedFields.join(", ")}` : ""}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <p>No edit history yet.</p>
        )}
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
  const rescueFeedback = useAsyncActionFeedbackMap();
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
    onSuccess: (_job, jobId) => {
      rescueFeedback.showSuccess(jobId);
      setDropMessage("Import job requeued");
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error, jobId) => {
      const message = actionFailureMessage("Could not requeue import job", error);
      rescueFeedback.showError(jobId, message);
      setDropMessage(message);
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
        {jobs.slice(0, 20).map((job) => {
          const progress = importJobProgress(job);
          return (
            <div
              key={job.id}
              className={`job-row ${job.status}`}
              style={{ "--job-progress": `${progress}%` } as CSSProperties}
              title={`${importJobStatusLabel(job)}: ${progress}%`}
            >
              <span className="job-copy">
                <span>{importJobLabel(job)}</span>
                <ImportJobStatusDetail job={job} />
              </span>
              <span className="job-actions">
                <StatusPill value={job.status} tone={job.status === "failed" ? "warn" : job.status === "complete" ? "good" : "blue"} />
                {canRescueImportJob(job) ? (
                  <AsyncActionSlot feedback={rescueFeedback.feedbackFor(job.id)}>
                    <button
                      className={asyncFeedbackClass("icon-button compact", rescueFeedback.feedbackFor(job.id))}
                      disabled={rescueJob.isPending}
                      onClick={() => rescueJob.mutate(job.id)}
                      title="Requeue this import job"
                      type="button"
                    >
                      <RefreshCw size={15} />
                    </button>
                  </AsyncActionSlot>
                ) : null}
              </span>
            </div>
          );
        })}
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
  const rescueFeedback = useAsyncActionFeedbackMap();
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
    onSuccess: (_job, jobId) => {
      rescueFeedback.showSuccess(jobId);
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (error, jobId) => {
      rescueFeedback.showError(jobId, actionFailureMessage("Could not requeue import job", error));
    },
  });
  const queueJobs = jobs.filter(isQueueImportJob);

  return (
    <section className="workbench queue-workbench">
      <section className="queue-panel">
        <div className="panel-title-row">
          <div>
            <h2>Import Queue</h2>
            <span>{queueJobs.length ? `${queueJobs.length} active or waiting` : "No import jobs waiting"}</span>
          </div>
          <Inbox size={20} />
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
                    <AsyncActionSlot feedback={rescueFeedback.feedbackFor(job.id)}>
                      <button
                        className={asyncFeedbackClass("icon-button compact", rescueFeedback.feedbackFor(job.id))}
                        disabled={rescueJob.isPending}
                        onClick={() => rescueJob.mutate(job.id)}
                        title="Requeue this import job"
                        type="button"
                      >
                        <RefreshCw size={15} />
                      </button>
                    </AsyncActionSlot>
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
          {items.map((item) => {
            const candidateTitle = candidateMetadataText(item, "title");
            const documentTitle = citationCandidateTitle(item);
            const showCandidateTitle = candidateTitle && candidateTitle !== documentTitle;
            const reviewDate = citationCandidateReviewDate(item);
            return (
              <article key={item.id} className="review-card">
                <div className="review-card-main">
                  <div className="review-card-title">
                    <strong title={documentTitle}>{documentTitle}</strong>
                    <div className="review-card-meta">
                      <span>
                        <FileText size={14} />
                        {citationCandidateSourceLabel(item)}
                      </span>
                      {reviewDate ? <span>{reviewDate}</span> : null}
                      {typeof item.confidence === "number" ? <span>{Math.round(item.confidence * 100)}% confidence</span> : null}
                    </div>
                    {showCandidateTitle ? <small>Candidate title: {candidateTitle}</small> : null}
                  </div>
                  <div className="review-citation">
                    <MarkdownBlock compact content={item.citation_text} empty="No candidate citation." />
                  </div>
                </div>
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
            );
          })}
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

function ViewportTooltip({
  ariaLabel,
  children,
  className = "",
  text,
}: {
  ariaLabel?: string;
  children: ReactNode;
  className?: string;
  text: string;
}) {
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const tooltipRef = useRef<HTMLSpanElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0, placement: "above", ready: false });

  const updatePosition = useCallback(() => {
    if (!triggerRef.current || !tooltipRef.current) return;

    const viewportMargin = 12;
    const triggerRect = triggerRef.current.getBoundingClientRect();
    const tooltipRect = tooltipRef.current.getBoundingClientRect();
    const tooltipWidth = Math.min(tooltipRect.width, window.innerWidth - viewportMargin * 2);
    const desiredLeft = triggerRect.left + triggerRect.width / 2 - tooltipWidth / 2;
    const left = Math.min(
      Math.max(desiredLeft, viewportMargin),
      Math.max(viewportMargin, window.innerWidth - tooltipWidth - viewportMargin),
    );
    const gap = 8;
    const aboveTop = triggerRect.top - tooltipRect.height - gap;
    const belowTop = triggerRect.bottom + gap;
    const fitsAbove = aboveTop >= viewportMargin;
    const fitsBelow = belowTop + tooltipRect.height <= window.innerHeight - viewportMargin;
    const placement = fitsAbove || !fitsBelow ? "above" : "below";
    const rawTop = placement === "above" ? aboveTop : belowTop;
    const maxTop = Math.max(viewportMargin, window.innerHeight - tooltipRect.height - viewportMargin);
    const top = Math.min(Math.max(rawTop, viewportMargin), maxTop);

    setPosition({ left, top, placement, ready: true });
  }, []);

  useEffect(() => {
    if (!visible) return undefined;

    setPosition((current) => ({ ...current, ready: false }));
    const frame = window.requestAnimationFrame(updatePosition);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);

    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [text, updatePosition, visible]);

  return (
    <span
      aria-label={ariaLabel || text}
      className={`viewport-tooltip-anchor ${className}`.trim()}
      onBlur={() => setVisible(false)}
      onClick={() => setVisible(true)}
      onFocus={() => setVisible(true)}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onPointerEnter={() => setVisible(true)}
      onPointerLeave={() => setVisible(false)}
      ref={triggerRef}
      tabIndex={0}
    >
      {children}
      {visible ? (
        <span
          className="info-popover-tooltip"
          data-placement={position.placement}
          data-ready={position.ready ? "true" : "false"}
          ref={tooltipRef}
          role="tooltip"
          style={{ left: position.left, top: position.top }}
        >
          {text}
        </span>
      ) : null}
    </span>
  );
}

function InfoPopup({ text }: { text: string }) {
  return (
    <ViewportTooltip className="info-popover" text={text}>
      <Info size={14} aria-hidden="true" />
    </ViewportTooltip>
  );
}

function modelDisplayName(model?: string | null): string {
  const value = (model || "").trim();
  if (!value) return "";
  if (value.includes("+")) {
    return value
      .split(/\s*\+\s*/)
      .map((part) => modelDisplayName(part))
      .filter(Boolean)
      .join(" + ");
  }
  if (value === "docling") return "Docling";
  if (value === "marker") return "Marker";
  if (value === "pymupdf") return "PyMuPDF";
  if (value === "local") return "Local";
  return value;
}

function ModelSelect({
  value,
  options,
  optionGroups,
  defaultModel,
  onChange,
}: {
  value: string;
  options: string[];
  optionGroups?: ModelOptionGroup[];
  defaultModel: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const hasGroups = Boolean(optionGroups?.length);
  const uniqueOptions = Array.from(new Set([value, defaultModel, ...options].filter(Boolean))).sort((left, right) =>
    left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" }),
  );
  const groupedOptions = (() => {
    if (!hasGroups) return [];
    const seen = new Set<string>();
    const groups = (optionGroups || [])
      .map((group) => {
        const groupOptions = group.options.filter((option) => {
          if (!option || seen.has(option)) return false;
          seen.add(option);
          return true;
        });
        return { ...group, options: groupOptions };
      })
      .filter((group) => group.options.length);
    const currentOptions = Array.from(new Set([value, defaultModel].filter((option) => option && !seen.has(option))));
    if (currentOptions.length) {
      groups.unshift({ label: "Current", options: currentOptions });
    }
    return groups;
  })();

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
        <span>{modelDisplayName(value)}</span>
        <ChevronRight size={14} aria-hidden="true" />
      </button>
      {open ? (
        <div className="model-options" role="listbox">
          {hasGroups
            ? groupedOptions.map((group) => (
                <div className="model-options-group" key={group.label}>
                  <div className="model-options-group-label">{group.label}</div>
                  {group.options.map((option) => (
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
                      <span>{modelDisplayName(option)}</span>
                      {option === defaultModel ? <span className="model-default-marker">(Default)</span> : null}
                    </button>
                  ))}
                </div>
              ))
            : uniqueOptions.map((option) => (
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
                  <span>{modelDisplayName(option)}</span>
                  {option === defaultModel ? <span className="model-default-marker">(Default)</span> : null}
                </button>
              ))}
        </div>
      ) : null}
    </div>
  );
}

function budgetRowLabel(row: OpenAIUsageGroup, groupMode: BudgetGroupMode) {
  if (groupMode === "model") return row.model || "unknown";
  if (groupMode === "document") return row.label || row.document_id || "unlinked document";
  if (groupMode === "day") return row.calendar_start ? new Date(row.calendar_start).toLocaleDateString() : row.group_key || "unknown";
  if (groupMode === "hour") {
    return row.calendar_start
      ? new Date(row.calendar_start).toLocaleString([], { dateStyle: "short", timeStyle: "short" })
      : row.group_key || "unknown";
  }
  return (row.task_key || "unknown").replaceAll("_", " ");
}

function budgetGroupHeader(groupMode: BudgetGroupMode) {
  if (groupMode === "model") return "Model";
  if (groupMode === "task") return "Task";
  if (groupMode === "document") return "Document";
  if (groupMode === "day") return "Day";
  return "Hour";
}

function formatBudgetCost(row: Pick<OpenAIUsageGroup, "estimated_cost_usd" | "priced_request_count" | "request_count">) {
  if (!row.priced_request_count && row.request_count) return "Unpriced";
  return formatUsd(row.estimated_cost_usd);
}

function BudgetView() {
  const [period, setPeriod] = useState<OpenAIUsagePeriod>("last_month");
  const [metricMode, setMetricMode] = useState<BudgetMetricMode>("tokens_cost");
  const [groupMode, setGroupMode] = useState<BudgetGroupMode>("model");
  const usage = useQuery({
    queryKey: ["openai-usage", period],
    queryFn: () => api.openaiUsage(period),
    refetchInterval: 10000,
  });
  const summary = usage.data?.summary;
  const rows =
    groupMode === "model"
      ? usage.data?.by_model || []
      : groupMode === "task"
        ? usage.data?.by_task || []
        : groupMode === "document"
          ? usage.data?.by_document || []
          : groupMode === "day"
            ? usage.data?.by_calendar_day || []
            : usage.data?.by_calendar_hour || [];
  const showTokens = metricMode !== "cost";
  const showCost = metricMode !== "tokens";

  return (
    <section className="workbench budget-view">
      <div className="budget-panel">
        <div className="panel-title-row">
          <div>
            <h2>Budget</h2>
            <span>{summary ? `${formatMetric(summary.request_count)} recorded calls` : usage.isFetching ? "Loading usage" : "No recorded calls"}</span>
          </div>
          <CircleDollarSign size={20} />
        </div>
        <div className="budget-controls">
          <label>
            Period
            <select value={period} onChange={(event) => setPeriod(event.target.value as OpenAIUsagePeriod)}>
              {USAGE_PERIOD_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Metric
            <select value={metricMode} onChange={(event) => setMetricMode(event.target.value as BudgetMetricMode)}>
              <option value="tokens_cost">Tokens + cost</option>
              <option value="tokens">Tokens</option>
              <option value="cost">Cost</option>
            </select>
          </label>
          <label>
            Group
            <select value={groupMode} onChange={(event) => setGroupMode(event.target.value as BudgetGroupMode)}>
              <option value="model">By model</option>
              <option value="task">By task</option>
              <option value="document">By document</option>
              <option value="day">By calendar day</option>
              <option value="hour">By calendar hour</option>
            </select>
          </label>
        </div>
        <div className="budget-metric-grid">
          <div>
            <span>Estimated cost</span>
            <strong>{summary ? formatUsd(summary.estimated_cost_usd) : "$0.00"}</strong>
          </div>
          <div>
            <span>Total tokens</span>
            <strong>{formatMetric(summary?.total_tokens)}</strong>
          </div>
          <div>
            <span>Input tokens</span>
            <strong>{formatMetric(summary?.input_tokens)}</strong>
          </div>
          <div>
            <span>Cached input</span>
            <strong>{formatMetric(summary?.cached_input_tokens)}</strong>
          </div>
          <div>
            <span>Output tokens</span>
            <strong>{formatMetric(summary?.output_tokens)}</strong>
          </div>
          <div>
            <span>Unpriced calls</span>
            <strong>{formatMetric(summary?.unpriced_request_count)}</strong>
          </div>
        </div>
        <div className="budget-table">
          <div className={`budget-row header ${metricMode}`}>
            <span>{budgetGroupHeader(groupMode)}</span>
            <span>Calls</span>
            {showTokens ? (
              <>
                <span>Input</span>
                <span>Cached</span>
                <span>Output</span>
                <span>Total</span>
              </>
            ) : null}
            {showCost ? (
              <>
                <span>Cost</span>
                {metricMode === "cost" ? <span>Priced</span> : null}
                <span>Unpriced</span>
              </>
            ) : null}
          </div>
          {rows.length ? (
            rows.map((row) => (
              <div className={`budget-row ${metricMode}`} key={`${groupMode}-${row.group_key || budgetRowLabel(row, groupMode)}`}>
                <span>{budgetRowLabel(row, groupMode)}</span>
                <span>{formatMetric(row.request_count)}</span>
                {showTokens ? (
                  <>
                    <span>{formatMetric(row.input_tokens)}</span>
                    <span>{formatMetric(row.cached_input_tokens)}</span>
                    <span>{formatMetric(row.output_tokens)}</span>
                    <span>{formatMetric(row.total_tokens)}</span>
                  </>
                ) : null}
                {showCost ? (
                  <>
                    <span>{formatBudgetCost(row)}</span>
                    {metricMode === "cost" ? <span>{formatMetric(row.priced_request_count)}</span> : null}
                    <span>{formatMetric(row.unpriced_request_count)}</span>
                  </>
                ) : null}
              </div>
            ))
          ) : (
            <div className={`budget-row empty ${metricMode}`}>
              <span>No usage recorded</span>
              <span />
              {showTokens ? (
                <>
                  <span />
                  <span />
                  <span />
                  <span />
                </>
              ) : null}
              {showCost ? (
                <>
                  <span />
                  {metricMode === "cost" ? <span /> : null}
                  <span />
                </>
              ) : null}
            </div>
          )}
        </div>
        <div className="budget-footnote">
          <span>{usage.data?.pricing.updated_at ? `Pricing ${usage.data.pricing.updated_at}` : "Pricing"}</span>
          {usage.data?.pricing.source_url ? (
            <a href={usage.data.pricing.source_url} rel="noreferrer" target="_blank">
              OpenAI
              <ExternalLink size={12} />
            </a>
          ) : null}
          {usage.data?.pricing.source_urls?.Google ? (
            <a href={usage.data.pricing.source_urls.Google} rel="noreferrer" target="_blank">
              Google
              <ExternalLink size={12} />
            </a>
          ) : null}
          <span>{usage.data?.pricing.basis}</span>
        </div>
      </div>
    </section>
  );
}

function SettingsView({
  capabilities,
  runs,
  jobs,
  preferences,
  openaiUsage,
  domains,
  projects,
  savedSearches,
  selectedDocument,
  startConcordanceRun,
  query,
}: {
  capabilities: ConcordanceCapability[];
  runs: ConcordanceRun[];
  jobs: ConcordanceJob[];
  preferences?: AppPreferences;
  openaiUsage?: OpenAIUsage;
  domains: Domain[];
  projects: Project[];
  savedSearches: SavedSearch[];
  selectedDocument?: DocumentDetail;
  startConcordanceRun: StartConcordanceRun;
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
  const [libraryAlternatingRows, setLibraryAlternatingRows] = useState(preferences?.library_alternating_rows ?? true);
  const [analysisModels, setAnalysisModels] = useState<Record<string, string>>(preferences?.analysis_models || {});
  const [selectedCapabilityKeys, setSelectedCapabilityKeys] = useState<string[]>([]);
  const queryClient = useQueryClient();
  const createRunFeedback = useAsyncActionFeedback();
  const savePreferencesFeedback = useAsyncActionFeedback();

  useEffect(() => {
    if (preferences) {
      setImportWorkerConcurrency(preferences.import_worker_concurrency);
      setAccentColorDay(preferences.accent_color_day);
      setAccentColorNight(preferences.accent_color_night);
      setDocumentCacheSizeMb(preferences.document_cache_size_mb);
      setLibraryAlternatingRows(preferences.library_alternating_rows);
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
      startConcordanceRun({
        backgroundDetail: `${selectedCapabilityKeys.length} ${selectedCapabilityKeys.length === 1 ? "capability" : "capabilities"}`,
        backgroundLabel: `${scopeLabel(scopeType)} Concordance`,
        label: `${scopeType.replace("_", " ")} Concordance`,
        scope_type: scopeType,
        scope_data: scopeData(),
        capability_keys: selectedCapabilityKeys,
        force,
      }),
    onSuccess: () => {
      createRunFeedback.showSuccess();
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-jobs"] });
    },
    onError: (error) => {
      createRunFeedback.showError(actionFailureMessage("Could not start Concordance Run", error));
    },
  });
  const savePreferences = useMutation({
    mutationFn: () =>
      api.updatePreferences({
        import_worker_concurrency: importWorkerConcurrency,
        accent_color_day: accentColorDay,
        accent_color_night: accentColorNight,
        document_cache_size_mb: documentCacheSizeMb,
        library_alternating_rows: libraryAlternatingRows,
        analysis_models: analysisModels,
      }),
    onSuccess: (updatedPreferences) => {
      savePreferencesFeedback.showSuccess();
      queryClient.setQueryData(["preferences"], updatedPreferences);
      void queryClient.invalidateQueries({ queryKey: ["preferences"] });
    },
    onError: (error) => {
      savePreferencesFeedback.showError(actionFailureMessage("Could not save preferences", error));
    },
  });
  const latestRun = runs[0];
  const activeJobs = jobs.filter((job) => job.status === "queued" || job.status === "running").length;
  const progressTotal = latestRun?.total_jobs || 0;
  const progressDone = latestRun ? latestRun.completed_jobs + latestRun.failed_jobs : 0;
  const warningThreshold = preferences?.import_worker_cost_warning_threshold || 4;
  const usageSummary = openaiUsage?.summary;
  const usageTaskRows = openaiUsage?.by_task || [];
  const recentUsageRows = openaiUsage?.recent || [];
  const preferenceDirty = Boolean(
    preferences &&
      (preferences.import_worker_concurrency !== importWorkerConcurrency ||
        preferences.accent_color_day !== accentColorDay ||
        preferences.accent_color_night !== accentColorNight ||
        preferences.document_cache_size_mb !== documentCacheSizeMb ||
        preferences.library_alternating_rows !== libraryAlternatingRows ||
        !sameStringMap(preferences.analysis_models, analysisModels)),
  );
  const importCostWarning = importWorkerConcurrency > warningThreshold;
  const savePreferencesDisabled = !preferences || !preferenceDirty || savePreferences.isPending;
  const renderSaveAllButton = (placement: "top" | "bottom") => (
    <AsyncActionSlot feedback={savePreferencesFeedback.feedback}>
      <button
        aria-label={`Save all preferences from the ${placement} of Settings`}
        className={asyncFeedbackClass("primary-button settings-save-all", savePreferencesFeedback.feedback)}
        disabled={savePreferencesDisabled}
        onClick={() => savePreferences.mutate()}
        type="button"
      >
        <Save size={16} />
        {savePreferences.isPending ? "Saving" : "Save All"}
      </button>
    </AsyncActionSlot>
  );

  return (
    <section className="workbench settings-grid">
      <header className="settings-save-row">{renderSaveAllButton("top")}</header>
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
            <span>Display and processing</span>
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
        <label className="checkbox-row preference-checkbox">
          <input
            type="checkbox"
            checked={libraryAlternatingRows}
            onChange={(event) => setLibraryAlternatingRows(event.target.checked)}
          />
          <span>Alternate Library rows</span>
        </label>
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
      </div>
      <div className="model-settings-panel">
        <div className="panel-title-row">
          <div>
            <h2>Models</h2>
            <span>{preferences?.analysis_model_tasks.length || 8} document-analysis tasks</span>
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
                optionGroups={task.option_groups}
                options={preferences?.model_options[task.model_kind] || []}
                value={analysisModels[task.key] || task.selected_model || task.default_model}
              />
            </div>
          ))}
        </div>
      </div>
      <div className="openai-usage-panel">
        <div className="panel-title-row">
          <div>
            <h2>AI Usage</h2>
            <span>{usageSummary ? `${formatMetric(usageSummary.request_count)} recorded calls` : "No recorded calls"}</span>
          </div>
          <Gauge size={20} />
        </div>
        <div className="usage-metric-grid">
          <div>
            <span>Input tokens</span>
            <strong>{formatMetric(usageSummary?.input_tokens)}</strong>
          </div>
          <div>
            <span>Cached input</span>
            <strong>{formatMetric(usageSummary?.cached_input_tokens)}</strong>
          </div>
          <div>
            <span>Output tokens</span>
            <strong>{formatMetric(usageSummary?.output_tokens)}</strong>
          </div>
          <div>
            <span>PDF/file context</span>
            <strong>{formatFileSize(usageSummary?.input_file_bytes) || "0 B"}</strong>
          </div>
          <div>
            <span>Failures</span>
            <strong>{formatMetric(usageSummary?.failed_request_count)}</strong>
          </div>
        </div>
        <div className="usage-table">
          <div className="usage-row header">
            <span>Task</span>
            <span>Calls</span>
            <span>Input</span>
            <span>Cached</span>
            <span>Output</span>
            <span>Files</span>
          </div>
          {usageTaskRows.length ? (
            usageTaskRows.map((row) => (
              <div className="usage-row" key={row.task_key || "unknown"}>
                <span>{(row.task_key || "unknown").replaceAll("_", " ")}</span>
                <span>{formatMetric(row.request_count)}</span>
                <span>{formatMetric(row.input_tokens)}</span>
                <span>{formatMetric(row.cached_input_tokens)}</span>
                <span>{formatMetric(row.output_tokens)}</span>
                <span>{formatFileSize(row.input_file_bytes) || "0 B"}</span>
              </div>
            ))
          ) : (
            <div className="usage-row empty">
              <span>No usage recorded yet</span>
              <span />
              <span />
              <span />
              <span />
              <span />
            </div>
          )}
        </div>
        <div className="usage-table recent">
          <div className="usage-row header">
            <span>Recent call</span>
            <span>Model</span>
            <span>Status</span>
            <span>Input</span>
            <span>Output</span>
            <span>Files</span>
          </div>
          {recentUsageRows.length ? (
            recentUsageRows.slice(0, 6).map((row) => (
              <div className="usage-row" key={row.id}>
                <span>{row.page_number ? `${row.task_key} p.${row.page_number}` : row.task_key}</span>
                <span>{row.model}</span>
                <StatusPill value={row.status} tone={row.status === "failed" ? "warn" : "good"} />
                <span>{formatMetric(row.input_tokens)}</span>
                <span>{formatMetric(row.output_tokens)}</span>
                <span>{formatFileSize(row.input_file_bytes) || "0 B"}</span>
              </div>
            ))
          ) : (
            <div className="usage-row empty">
              <span>No calls yet</span>
              <span />
              <span />
              <span />
              <span />
              <span />
            </div>
          )}
        </div>
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
          <AsyncActionSlot busy={createRun.isPending} feedback={createRunFeedback.feedback} label="Concordance Run request in progress">
            <button
              className={asyncFeedbackClass("primary-button", createRunFeedback.feedback, createRun.isPending)}
              disabled={createRun.isPending || !scopeReady || !selectedCapabilityKeys.length}
              onClick={() => createRun.mutate()}
            >
              <RefreshCw className={createRun.isPending ? "spin" : ""} size={16} />
              {createRun.isPending ? "Starting" : "Start run"}
            </button>
          </AsyncActionSlot>
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
      <footer className="settings-save-row bottom">{renderSaveAllButton("bottom")}</footer>
    </section>
  );
}

export default function App() {
  const [activeView, setActiveView] = useState<View>("library");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<DocumentFilters>(() => emptyFilters());
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [theme, setTheme] = useState<"day" | "night">(() => (localStorage.getItem("medusa-theme") as "day" | "night") || "day");
  const [backgroundJobs, setBackgroundJobs] = useState<BackgroundJob[]>([]);
  const queryClient = useQueryClient();
  const browserHost = window.location.hostname || "";

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("medusa-theme", theme);
  }, [theme]);

  const runtimeLocation = useQuery({
    queryKey: ["runtime-location", browserHost],
    queryFn: () => api.runtimeLocation(browserHost),
    retry: 1,
    staleTime: Infinity,
  });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, enabled: Boolean(me.data), refetchInterval: 4000 });
  const preferences = useQuery({ queryKey: ["preferences"], queryFn: api.preferences, enabled: Boolean(me.data) });
  const openaiUsage = useQuery({ queryKey: ["openai-usage"], queryFn: () => api.openaiUsage(), enabled: Boolean(me.data), refetchInterval: 10000 });
  const domains = useQuery({ queryKey: ["domains"], queryFn: api.domains, enabled: Boolean(me.data), refetchInterval: 10000 });
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
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, enabled: Boolean(me.data), refetchInterval: 10000 });
  const notes = useQuery({ queryKey: ["notes"], queryFn: () => api.notes(), enabled: Boolean(me.data), refetchInterval: 10000 });
  const review = useQuery({ queryKey: ["review"], queryFn: api.reviewQueue, enabled: Boolean(me.data), refetchInterval: 10000 });
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => queryClient.clear(),
  });

  useEffect(() => {
    document.title = runtimeLocation.data?.title || MEDUSA_APP_NAME;
  }, [runtimeLocation.data?.title]);

  const startConcordanceRun = useCallback(
    async (request: ConcordanceRunRequest) => {
      const id = backgroundJobId();
      const label = request.backgroundLabel || request.label || `${scopeLabel(request.scope_type)} Concordance`;
      const detail = request.backgroundDetail || "Request received";
      setBackgroundJobs((current) => [
        {
          id,
          label,
          detail,
          status: "starting",
          documentId: request.documentId,
          capabilityKey: request.capabilityKey,
          createdAt: Date.now(),
        },
        ...current,
      ]);
      try {
        const run = await api.createConcordanceRun({
          label: request.label,
          scope_type: request.scope_type,
          scope_data: request.scope_data,
          capability_keys: request.capability_keys,
          force: request.force,
        });
        setBackgroundJobs((current) =>
          current.map((job) =>
            job.id === id
              ? {
                  ...job,
                  status: run.total_jobs > 0 ? "queued" : "complete",
                  runId: run.id,
                  completedJobs: run.completed_jobs,
                  failedJobs: run.failed_jobs,
                  totalJobs: run.total_jobs,
                  completedAt: run.total_jobs > 0 ? undefined : Date.now(),
                  detail:
                    run.total_jobs > 0
                      ? `${run.total_jobs} ${run.total_jobs === 1 ? "job" : "jobs"} queued`
                      : "Already current",
                }
              : job,
          ),
        );
        void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
        void queryClient.invalidateQueries({ queryKey: ["concordance-runs"] });
        void queryClient.invalidateQueries({ queryKey: ["concordance-jobs"] });
        return run;
      } catch (error) {
        setBackgroundJobs((current) =>
          current.map((job) =>
            job.id === id
              ? {
                  ...job,
                  status: "failed",
                  error: actionFailureMessage("Could not start background job", error),
                  completedAt: Date.now(),
                }
              : job,
          ),
        );
        throw error;
      }
    },
    [queryClient],
  );

  useEffect(() => {
    if (!selectedId && documents.data?.[0]) setSelectedId(documents.data[0].id);
  }, [documents.data, selectedId]);

  useEffect(() => {
    const runs = concordanceRuns.data || [];
    const jobs = concordanceJobs.data || [];
    const now = Date.now();
    setBackgroundJobs((current) =>
      current
        .map((job) => {
          if (!job.runId) return job;
          const run = runs.find((item) => item.id === job.runId);
          if (!run) return job;
          return backgroundJobFromRun(
            run,
            jobs.filter((item) => item.run_id === run.id),
            job,
          );
        })
        .filter((job) => !job.completedAt || now - job.completedAt < BACKGROUND_JOB_RETENTION_MS),
    );
  }, [concordanceJobs.data, concordanceRuns.data]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = Date.now();
      setBackgroundJobs((current) =>
        current.filter((job) => !job.completedAt || now - job.completedAt < BACKGROUND_JOB_RETENTION_MS),
      );
    }, 2000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key.toLowerCase() !== "b") return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      setActiveView("budget");
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  if (me.isLoading) return <div className="loading-screen">Medusa</div>;
  if (me.error || !me.data) return <Login />;

  const activeAccent = normalizeHexColor(
    theme === "night" ? preferences.data?.accent_color_night : preferences.data?.accent_color_day,
    theme === "night" ? "#6ea8ff" : "#2563eb",
  );
  const shellStyle = {
    "--accent": activeAccent,
    "--accent-soft": accentSoftColor(activeAccent, theme),
  } as CSSProperties;
  const navCounts: NavCounts = {
    library: dashboard.data?.documents ?? 0,
    domains: domains.data?.length ?? 0,
    projects: projects.data?.length ?? dashboard.data?.projects ?? 0,
    queue: (jobs.data || []).filter(isQueueImportJob).length + (review.data || []).length,
    notes: notes.data?.length ?? 0,
    import: dashboard.data?.active_import_jobs ?? 0,
  };
  const trackedRunIds = new Set(backgroundJobs.map((job) => job.runId).filter(Boolean));
  const activeServerBackgroundJobs = (concordanceRuns.data || [])
    .filter((run) => !trackedRunIds.has(run.id))
    .map((run) =>
      backgroundJobFromRun(
        run,
        (concordanceJobs.data || []).filter((job) => job.run_id === run.id),
      ),
    )
    .filter((job) => job.status === "queued" || job.status === "running")
    .slice(0, 3);
  const visibleBackgroundJobs = [...backgroundJobs, ...activeServerBackgroundJobs].sort(
    (left, right) =>
      Number(isTerminalBackgroundStatus(left.status)) - Number(isTerminalBackgroundStatus(right.status)) ||
      right.createdAt - left.createdAt,
  );

  return (
    <div className="app-shell" style={shellStyle}>
      <Header
        backgroundJobs={visibleBackgroundJobs}
        dashboard={dashboard.data}
        onOpenQueue={() => setActiveView("queue")}
        query={query}
        setQuery={setQuery}
        theme={theme}
        setTheme={setTheme}
        onLogout={() => logout.mutate()}
      />
      <main className="content">
        <section className="content-top">
          <WorkspaceNav activeView={activeView} counts={navCounts} setActiveView={setActiveView} />
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
            startConcordanceRun={startConcordanceRun}
            loading={documents.isFetching}
            alternatingRows={preferences.data?.library_alternating_rows ?? true}
            preferences={preferences.data}
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
        {activeView === "budget" ? <BudgetView /> : null}
        {activeView === "settings" ? (
          <SettingsView
            capabilities={concordanceCapabilities.data || []}
            domains={domains.data || []}
            jobs={concordanceJobs.data || []}
            openaiUsage={openaiUsage.data}
            preferences={preferences.data}
            projects={projects.data || []}
            query={query}
            runs={concordanceRuns.data || []}
            savedSearches={savedSearches.data || []}
            selectedDocument={selectedDocument.data}
            startConcordanceRun={startConcordanceRun}
          />
        ) : null}
      </main>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ChangeEvent,
  CSSProperties,
  DragEvent,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type EdgeProps,
  type Node as FlowNode,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Archive,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Bold,
  Bookmark,
  BookOpen,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  CheckSquare,
  CircleDollarSign,
  Clipboard,
  Cloud,
  CornerDownRight,
  Download,
  Edit3,
  Eraser,
  ExternalLink,
  FileSearch,
  FileText,
  Filter,
  FolderTree,
  Gauge,
  IndentDecrease,
  IndentIncrease,
  Info,
  Image,
  Inbox,
  Italic,
  Library,
  ListChecks,
  List,
  ListOrdered,
  LogOut,
  Merge,
  Moon,
  Orbit,
  PieChart,
  Play,
  Plus,
  RefreshCw,
  RemoveFormatting,
  RotateCcw,
  Save,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Tags,
  Trash2,
  Underline,
  Upload,
  UploadCloud,
  X,
} from "lucide-react";
import { api } from "./lib/api";
import type {
  AccessorySummary,
  AppPreferences,
  BackupArtifact,
  BackupEstimate,
  BackupRun,
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
  DoiStash,
  Domain,
  DomainUpdatePayload,
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
  TagOrphanPruneSuggestion,
  TagOptimizationResult,
  TagPruneSuggestion,
  TagRelationshipSuggestion,
  TagStatusSuggestion,
  TagOptimizationSuggestion,
} from "./types";

type View = "library" | "domains" | "projects" | "tags" | "queue" | "notes" | "import" | "stashes" | "budget" | "settings";
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
  progress?: number;
  totalJobs?: number;
  error?: string;
  createdAt: number;
  completedAt?: number;
};

type EscapeLayer = {
  id: symbol;
  onEscape: () => void;
  order: number;
  priority: number;
};

const ESCAPE_PRIORITY_READER = 10;
const ESCAPE_PRIORITY_EXPANDED = 20;
const ESCAPE_PRIORITY_POPOVER = 30;
const ESCAPE_PRIORITY_DIALOG = 40;
const ESCAPE_PRIORITY_MENU = 50;
const ESCAPE_PRIORITY_TOOLTIP = 60;

const escapeLayers: EscapeLayer[] = [];
let escapeLayerOrder = 0;

function handleRegisteredEscape(event: KeyboardEvent) {
  if (event.key !== "Escape" || event.defaultPrevented) return;
  const topLayer = escapeLayers.reduce<EscapeLayer | null>((selected, layer) => {
    if (!selected) return layer;
    if (layer.priority !== selected.priority) return layer.priority > selected.priority ? layer : selected;
    return layer.order > selected.order ? layer : selected;
  }, null);
  if (!topLayer) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  topLayer.onEscape();
}

function useEscapeLayer(active: boolean, onEscape: () => void, priority: number) {
  const onEscapeRef = useRef(onEscape);
  useEffect(() => {
    onEscapeRef.current = onEscape;
  }, [onEscape]);

  useEffect(() => {
    if (!active) return;
    const layer: EscapeLayer = {
      id: Symbol("escape-layer"),
      onEscape: () => onEscapeRef.current(),
      order: ++escapeLayerOrder,
      priority,
    };
    const needsListener = escapeLayers.length === 0;
    escapeLayers.push(layer);
    if (needsListener) window.addEventListener("keydown", handleRegisteredEscape, true);
    return () => {
      const index = escapeLayers.findIndex((item) => item.id === layer.id);
      if (index >= 0) escapeLayers.splice(index, 1);
      if (!escapeLayers.length) window.removeEventListener("keydown", handleRegisteredEscape, true);
    };
  }, [active, priority]);
}
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
type SettingsSaveHandler = () => Promise<boolean>;
type SelectMenuOption = { id: string; name: string };

const APA_CITATION_MODEL_KEY = "apa_citation";
const SUMMARY_MODEL_KEY = "summary";
const TAG_SUGGESTIONS_MODEL_KEY = "keywords_topics";
const ACCESSORY_SUMMARIES_MODEL_KEY = "accessory_summaries";
const CITATION_CONVENTION_APA_7 = "apa_7";
const FILTER_PANE_MIN = 260;
const FILTER_PANE_DEFAULT = 280;
const FILTER_PANE_MAX = 420;
const MEDUSA_BUILD_VERSION = import.meta.env.VITE_MEDUSA_BUILD_VERSION || "local";
const MEDUSA_APP_NAME = "medusa";
const MEDUSA_EXPANSION = "Mapped Evidence for Discovery, Understanding, Synthesis, and Analysis";
const QUEUE_IMPORT_JOB_STATUSES = new Set(["staged", "queued", "running", "failed", "restored_paused"]);
const ASYNC_ACTION_SUCCESS_FEEDBACK_MS = 900;
const ASYNC_ACTION_ERROR_FEEDBACK_MS = 5000;
const BACKGROUND_JOB_RETENTION_MS = 18000;
const IMPORT_COMPLETED_ROW_RETENTION_MS = 15000;
const IMPORT_JOB_LIST_LIMIT = 20;
const IMPORT_ACCEPT = "application/pdf,text/html,text/plain,text/markdown,.pdf,.html,.htm,.txt,.text,.md,.markdown";
const IMPORT_FILE_EXTENSIONS = [".pdf", ".html", ".htm", ".txt", ".text", ".md", ".markdown"];
const IMPORT_FILE_TYPES = new Set(["application/pdf", "text/html", "text/plain", "text/markdown", "text/x-markdown"]);
const DROPDOWN_VISIBLE_OPTION_LIMIT = 80;
const APP_TOOLTIP_DELAY_MS = 2000;
const APP_TOOLTIP_SELECTOR = [
  "[data-tooltip]",
  "button",
  "a[href]",
  "input:not([type='hidden'])",
  "select",
  "textarea",
  "[role='button']",
].join(",");
const USAGE_PERIOD_OPTIONS: Array<{ value: OpenAIUsagePeriod; label: string }> = [
  { value: "last_day", label: "Last day" },
  { value: "last_month", label: "Last month" },
  { value: "last_3_months", label: "Last 3 months" },
  { value: "all_time", label: "All time" },
];
const READ_STATUS_OPTIONS: SelectMenuOption[] = [
  { id: "unread", name: "Unread" },
  { id: "skimmed", name: "Skimmed" },
  { id: "read", name: "Read" },
];
const PRIORITY_OPTIONS: SelectMenuOption[] = [
  { id: "urgent", name: "Urgent" },
  { id: "high", name: "High" },
  { id: "normal", name: "Normal" },
  { id: "low", name: "Low" },
];
const CITATION_STATUS_OPTIONS: SelectMenuOption[] = [
  { id: "needs_review", name: "Needs review" },
  { id: "verified", name: "Verified" },
  { id: "rejected", name: "Rejected" },
];
const DUPLICATE_STATUS_OPTIONS: SelectMenuOption[] = [
  { id: "duplicates", name: "Has duplicates" },
  { id: "unique", name: "No exact duplicates" },
];
type BudgetMetricMode = "tokens_cost" | "tokens" | "cost";
type BudgetGroupMode = "model" | "task" | "document" | "day" | "hour";
type BudgetChartSegment = {
  color: string;
  displayValue: string;
  key: string;
  label: string;
  shareLabel: string;
  value: number;
};
type StashSortKey = "created" | "doi" | "title" | "status";
type TagSortKey = "name" | "status" | "documents";
type SortDirection = "asc" | "desc";
type TagMergeChoice = { target_tag_id?: string; target_name?: string; source_tag_ids?: string[] };
type BrowserHistoryMode = "none" | "push" | "replace";
type AppRoute = { view: View; documentId?: string };

const DOMAIN_COLOR_SWATCHES = ["#2563eb", "#0f766e", "#7c3aed", "#c2410c", "#be123c", "#475569"];

const navItems: Array<{ id: View; label: string; icon: typeof Library; shortcut?: string; align?: "end" }> = [
  { id: "library", label: "Library", icon: Library },
  { id: "domains", label: "Domains", icon: FolderTree },
  { id: "projects", label: "Projects", icon: ListChecks },
  { id: "tags", label: "Tags", icon: Tags },
  { id: "queue", label: "Queue", icon: Inbox },
  { id: "notes", label: "Notes", icon: BookOpen },
  { id: "import", label: "Import", icon: Upload },
  { id: "stashes", label: "Stashes", icon: Bookmark },
  { id: "budget", label: "Budget & Costs", icon: CircleDollarSign, shortcut: "B" },
  { id: "settings", label: "Settings", icon: Settings, align: "end" },
];
const DEFAULT_VIEW: View = "library";
const VIEW_PATHS: Record<View, string> = {
  library: "/library",
  domains: "/domains",
  projects: "/projects",
  tags: "/tags",
  queue: "/queue",
  notes: "/notes",
  import: "/import",
  stashes: "/stashes",
  budget: "/budget",
  settings: "/settings",
};
const VIEW_BY_PATH = new Map<string, View>(
  Object.entries(VIEW_PATHS).map(([view, path]) => [path, view as View]),
);

function normalizedAppPath(pathname: string) {
  const normalized = pathname.replace(/\/+$/, "");
  return normalized || "/";
}

function viewFromPathname(pathname: string): View | undefined {
  const path = normalizedAppPath(pathname);
  if (path === "/") return DEFAULT_VIEW;
  return VIEW_BY_PATH.get(path.toLowerCase());
}

function decodePathSegment(segment: string) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

function documentIdFromPathname(pathname: string) {
  const path = normalizedAppPath(pathname);
  const match = path.match(/^\/documents?\/([^/]+)$/i);
  return match ? decodePathSegment(match[1]) : undefined;
}

function routeFromPathname(pathname: string): AppRoute {
  const documentId = documentIdFromPathname(pathname);
  if (documentId) return { view: "library", documentId };
  return { view: viewFromPathname(pathname) || DEFAULT_VIEW };
}

function routeFromCurrentLocation(): AppRoute {
  return routeFromPathname(window.location.pathname);
}

function pathForView(view: View) {
  return VIEW_PATHS[view];
}

function pathForDocument(documentId: string) {
  return `/documents/${encodeURIComponent(documentId)}`;
}

function documentLinkUrl(documentId: string) {
  return `${window.location.origin}${pathForDocument(documentId)}`;
}

function syncBrowserUrl(path: string, state: Record<string, string | undefined>, mode: Exclude<BrowserHistoryMode, "none">) {
  if (mode === "replace") {
    window.history.replaceState(state, "", path);
    return;
  }
  if (normalizedAppPath(window.location.pathname) === path && !window.location.search && !window.location.hash) return;
  window.history.pushState(state, "", path);
}

function syncBrowserUrlForView(view: View, mode: Exclude<BrowserHistoryMode, "none">) {
  syncBrowserUrl(pathForView(view), { medusaView: view }, mode);
}

function syncBrowserUrlForDocument(documentId: string, mode: Exclude<BrowserHistoryMode, "none">) {
  syncBrowserUrl(pathForDocument(documentId), { medusaView: "library", medusaDocumentId: documentId }, mode);
}

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

function BookSearchIcon({ size = 15 }: { size?: number }) {
  return (
    <span className="book-search-icon" style={{ width: size, height: size }} aria-hidden="true">
      <BookOpen size={size} />
      <Search className="book-search-icon-lens" size={Math.max(8, Math.round(size * 0.56))} />
    </span>
  );
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

function selectedAnalysisModel(preferences: AppPreferences | undefined, key: string, fallback: string) {
  const task = preferences?.analysis_model_tasks.find((item) => item.key === key);
  return preferences?.analysis_models[key] || task?.selected_model || task?.default_model || fallback;
}

function analysisModelActionLabel(preferences: AppPreferences | undefined, key: string, fallback: string) {
  return selectedAnalysisModel(preferences, key, fallback);
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

function cleanTooltipText(value?: string | null) {
  return (value || "").replace(/\s+/g, " ").trim();
}

function capitalizeSentence(value: string) {
  const text = cleanTooltipText(value);
  if (!text) return "";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function disabledTooltipReason(element: HTMLElement) {
  return (
    cleanTooltipText(element.dataset.disabledReason) ||
    "this control is waiting on a required selection, input, or background task."
  );
}

function isTooltipElementDisabled(element: HTMLElement) {
  if (element.getAttribute("aria-disabled") === "true") return true;
  if (
    element instanceof HTMLButtonElement ||
    element instanceof HTMLInputElement ||
    element instanceof HTMLSelectElement ||
    element instanceof HTMLTextAreaElement
  ) {
    return element.disabled;
  }
  return false;
}

function labelTextForTooltipElement(element: HTMLElement) {
  const ariaLabel = cleanTooltipText(element.getAttribute("aria-label"));
  if (ariaLabel) return ariaLabel;

  const label = Array.from(document.querySelectorAll("label")).find((item) => item.control === element);
  const labelText = cleanTooltipText(label?.textContent);
  if (labelText) return labelText;

  const wrappingLabel = element.closest("label");
  const wrappingText = cleanTooltipText(wrappingLabel?.textContent);
  if (wrappingText) return wrappingText;

  return "";
}

function nativeTitleForTooltipElement(element: HTMLElement) {
  const title = cleanTooltipText(element.getAttribute("title"));
  if (title) {
    element.dataset.tooltipTitle = title;
    element.removeAttribute("title");
    return title;
  }
  return cleanTooltipText(element.dataset.tooltipTitle);
}

function visibleTextForTooltipElement(element: HTMLElement) {
  return cleanTooltipText(element.textContent);
}

function defaultTooltipForElement(element: HTMLElement) {
  const tagName = element.tagName.toLowerCase();
  const explicitLabel =
    nativeTitleForTooltipElement(element) ||
    labelTextForTooltipElement(element) ||
    cleanTooltipText(element.getAttribute("placeholder")) ||
    visibleTextForTooltipElement(element);

  if (tagName === "a") {
    const label = explicitLabel || "this link";
    if (element.hasAttribute("download")) return `Download ${label}.`;
    if (element.getAttribute("target") === "_blank") return `Open ${label} in a new tab.`;
    return `Open ${label}.`;
  }

  if (tagName === "select") {
    return `Choose ${explicitLabel || "an option"} from this dropdown.`;
  }

  if (tagName === "textarea") {
    return `Edit ${explicitLabel || "this text field"}.`;
  }

  if (tagName === "input") {
    const input = element as HTMLInputElement;
    const label = explicitLabel || "this field";
    if (input.type === "checkbox" || input.type === "radio") return `Toggle ${label}.`;
    if (input.type === "color") return `Pick the ${label} color.`;
    if (input.type === "file") return `Choose files for ${label}.`;
    if (input.type === "range" || input.type === "number") return `Adjust ${label}.`;
    if (input.type === "password") return `Enter ${label}.`;
    return `Type in ${label}.`;
  }

  if (element.getAttribute("role") === "button" || tagName === "button") {
    return explicitLabel ? `Button action: ${capitalizeSentence(explicitLabel)}.` : "";
  }

  return explicitLabel;
}

function tooltipTextForElement(element: HTMLElement) {
  const disabled = isTooltipElementDisabled(element);
  const disabledText = disabled ? cleanTooltipText(element.dataset.tooltipDisabled) : "";
  if (disabledText) return disabledText;

  const actionText = cleanTooltipText(element.dataset.tooltip) || defaultTooltipForElement(element);
  if (!actionText) return "";
  if (!disabled) return actionText;

  return `${actionText} Disabled because ${disabledTooltipReason(element)}`;
}

function tooltipCandidateFromElement(element: Element | null): HTMLElement | null {
  const candidate = element?.closest(APP_TOOLTIP_SELECTOR);
  if (!(candidate instanceof HTMLElement)) return null;
  if (candidate.classList.contains("hidden-file-input")) return null;
  if (candidate.closest("[hidden], [aria-hidden='true']")) return null;
  const style = window.getComputedStyle(candidate);
  if (style.display === "none" || style.visibility === "hidden") return null;
  const rect = candidate.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  return candidate;
}

function tooltipCandidateFromPoint(clientX: number, clientY: number) {
  return tooltipCandidateFromElement(document.elementFromPoint(clientX, clientY));
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

function backupRunStatus(run: BackupRun): BackgroundJobStatus {
  if (run.status === "complete") return "complete";
  if (run.status === "failed") return "failed";
  if (run.status === "queued") return "queued";
  return "running";
}

function backupPhaseLabel(value: string) {
  return value.replaceAll("_", " ");
}

function backupDateLabel(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "";
  return date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
}

function backupArtifactLabel(artifact: BackupArtifact) {
  const pieces = [
    artifact.filename,
    backupDateLabel(artifact.completed_at || artifact.created_at),
    artifact.hostname || "",
    formatFileSize(artifact.size_bytes),
  ].filter(Boolean);
  return pieces.join(" - ");
}

function backupRunLabel(run: BackupRun) {
  if (run.kind === "restore") return "Database restore";
  if (run.reason === "pre_restore") return "Safety backup";
  return "Database backup";
}

function backupRunTimestamp(run: BackupRun) {
  return backupDateLabel(run.completed_at || run.started_at || run.created_at);
}

function backupRunDetail(run: BackupRun) {
  if (run.filename) return run.filename;
  if (run.source_filename) return run.source_filename;
  if (run.source_uri) return run.source_uri;
  return run.status_detail || run.id;
}

function backupEstimateLabel(estimate?: BackupEstimate, loading = false) {
  if (!estimate && loading) return "Likely backup size: calculating";
  if (!estimate) return "Likely backup size: unavailable";
  const size = formatFileSize(estimate.estimated_size_bytes);
  if (!size) return "Likely backup size: unavailable";
  if (estimate.basis === "database_size_upper_bound") return `Likely backup size: up to ${size} before compression`;
  if (estimate.basis === "latest_backup") return `Likely backup size: about ${size} (last backup)`;
  return `Likely backup size: about ${size}`;
}

function backgroundJobFromBackupRun(run: BackupRun): BackgroundJob {
  const status = backupRunStatus(run);
  const terminal = isTerminalBackgroundStatus(status);
  const label =
    run.kind === "restore"
      ? "Database restore"
      : run.reason === "pre_restore"
        ? "Safety backup"
        : "Database backup";
  return {
    id: run.id,
    label,
    detail: run.status_detail || backupPhaseLabel(run.phase),
    status,
    progress: Math.max(0, Math.min(100, run.progress || 0)),
    error: run.last_error || undefined,
    createdAt: new Date(run.created_at).getTime() || Date.now(),
    completedAt: terminal ? new Date(run.completed_at || run.updated_at).getTime() || Date.now() : undefined,
  };
}

function backgroundProgress(job: BackgroundJob) {
  if (job.status === "complete" || job.status === "failed") return 100;
  if (job.progress !== undefined) return Math.max(0, Math.min(100, job.progress));
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
      <button
        className={`header-work-progress ${activeClass}`}
        data-tooltip="Open Queue to inspect active imports, Concordance runs, backups, restores, and citation review work."
        type="button"
        aria-label="Open import queue"
        onClick={onOpenQueue}
      >
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

function inputEventShiftKey(event: ChangeEvent<HTMLInputElement>) {
  const nativeEvent = event.nativeEvent as Event & { shiftKey?: unknown };
  return nativeEvent.shiftKey === true;
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

function normalizedNameList(values: string[]) {
  const seen = new Set<string>();
  return values
    .map((value) => value.trim())
    .filter(Boolean)
    .filter((value) => {
      const key = value.toLocaleLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((left, right) => left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" }));
}

function sortByName<T extends { name: string }>(values: T[]) {
  return [...values].sort((left, right) => left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" }));
}

function normalizeTagInputName(name: string) {
  return name.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean).join(" ");
}

function emptyFilters(): DocumentFilters {
  return { domain_id: "", tag_id: "", read_status: "", priority: "", citation_status: "", duplicate_status: "" };
}

function cleanFilters(filters: DocumentFilters): DocumentFilters {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => Boolean(value))) as DocumentFilters;
}

function selectOptionSearchText(option: SelectMenuOption | { id: string; name: string }) {
  return `${option.name} ${option.id}`.toLowerCase();
}

function matchingSelectOptions<T extends SelectMenuOption | { id: string; name: string }>(options: T[], query: string) {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return options;
  return options.filter((option) => selectOptionSearchText(option).includes(normalizedQuery));
}

function visibleSelectOptions<T extends SelectMenuOption | { id: string; name: string }>(options: T[]) {
  return options.slice(0, DROPDOWN_VISIBLE_OPTION_LIMIT);
}

function priorityLabel(value?: string | null) {
  return PRIORITY_OPTIONS.find((option) => option.id === value)?.name || (value ? value.replaceAll("_", " ") : "Normal");
}

function priorityClass(value?: string | null) {
  if (value === "urgent") return "urgent";
  if (value === "high") return "high";
  if (value === "low") return "low";
  return "normal";
}

function PriorityPill({ value }: { value?: string | null }) {
  return <span className={`priority-pill ${priorityClass(value)}`}>{priorityLabel(value)}</span>;
}

function savedSearchSummary(savedSearch: SavedSearch, lookup: { domains: Map<string, string>; tags: Map<string, string> }) {
  const filters = savedSearch.filters || {};
  const pieces = [
    savedSearch.query ? `"${savedSearch.query}"` : "",
    filters.domain_id ? `Domain: ${lookup.domains.get(String(filters.domain_id)) || "selected"}` : "",
    filters.tag_id ? `Tag: ${lookup.tags.get(String(filters.tag_id)) || "selected"}` : "",
    filters.read_status ? `Read: ${String(filters.read_status).replaceAll("_", " ")}` : "",
    filters.priority ? `Priority: ${priorityLabel(String(filters.priority))}` : "",
    filters.citation_status ? `Citation: ${String(filters.citation_status).replaceAll("_", " ")}` : "",
    filters.duplicate_status ? `Duplicates: ${String(filters.duplicate_status).replaceAll("_", " ")}` : "",
  ].filter(Boolean);
  return pieces.length ? pieces.join(" / ") : "All library documents";
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

function isSupportedImportFile(file: File) {
  const type = (file.type || "").split(";")[0].toLowerCase();
  const name = file.name.toLowerCase();
  return IMPORT_FILE_TYPES.has(type) || IMPORT_FILE_EXTENSIONS.some((extension) => name.endsWith(extension));
}

function importFileCountLabel(count: number) {
  return `${count} file${count === 1 ? "" : "s"}`;
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

function formatSignedUsd(value?: number | null) {
  if (value === undefined || value === null || !Number.isFinite(value)) return "Pending";
  if (value === 0) return formatUsd(0);
  return `${value > 0 ? "+" : "-"}${formatUsd(Math.abs(value))}`;
}

function formatSignedPercent(value?: number | null) {
  if (value === undefined || value === null || !Number.isFinite(value)) return "Pending";
  if (value === 0) return "0%";
  return `${value > 0 ? "+" : ""}${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value)}%`;
}

function isImportCostPreviewJob(job: ImportJob) {
  return job.status === "staged" || job.status === "queued";
}

function importQueueEstimateTotal(jobs: ImportJob[]) {
  return jobs.reduce((sum, job) => {
    const value = job.estimated_cost_usd ?? 0;
    return sum + (Number.isFinite(value) ? Math.max(0, value) : 0);
  }, 0);
}

function importQueueEstimateLabel(jobs: ImportJob[]) {
  return `Rough total ${formatUsd(importQueueEstimateTotal(jobs))}`;
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

function compositionEstimateStatusLabel(status?: string | null) {
  if (status === "over") return "Actual over estimate";
  if (status === "under") return "Actual under estimate";
  if (status === "close") return "Actual close to estimate";
  return "Waiting for actual cost";
}

function compositionEstimateBasisLabel(value?: string | null) {
  const basis = (value || "estimate").replace(/^calibrated_/, "calibrated ");
  return basis.replaceAll("_", " ");
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

const compositionPipelineEdgeTypes = {
  compositionPipeline: CompositionPipelineEdgeView,
};

const COMPOSITION_PIPELINE_NODE_WIDTH = 236;
const COMPOSITION_PIPELINE_NODE_HEIGHT = 126;
const COMPOSITION_PIPELINE_GAP = 96;
const COMPOSITION_PIPELINE_HANDLE_OFFSET = 6;
const COMPOSITION_PIPELINE_ARROW_LENGTH = 14;
const COMPOSITION_PIPELINE_ARROW_WIDTH = 12;

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
  const nodes: CompositionPipelineNode[] = pipeline.map((entry, index) => ({
    id: `pipeline-${index}`,
    type: "compositionPipeline",
    position: {
      x: index * (COMPOSITION_PIPELINE_NODE_WIDTH + COMPOSITION_PIPELINE_GAP),
      y: 88,
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style: {
      height: COMPOSITION_PIPELINE_NODE_HEIGHT,
      width: COMPOSITION_PIPELINE_NODE_WIDTH,
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
    sourceHandle: "pipeline-output",
    target: `pipeline-${index + 1}`,
    targetHandle: "pipeline-input",
    type: "compositionPipeline",
  }));
  return { nodes, edges };
}

function CompositionPipelineEdgeView({ id, sourceX, sourceY, targetX, targetY }: EdgeProps) {
  const deltaX = targetX - sourceX;
  const deltaY = targetY - sourceY;
  const length = Math.hypot(deltaX, deltaY);
  if (!length) return null;

  const unitX = deltaX / length;
  const unitY = deltaY / length;
  const edgeOffset = Math.min(COMPOSITION_PIPELINE_HANDLE_OFFSET, length * 0.2);
  const startX = sourceX - unitX * edgeOffset;
  const startY = sourceY - unitY * edgeOffset;
  const tipX = targetX + unitX * edgeOffset;
  const tipY = targetY + unitY * edgeOffset;
  const visibleLength = Math.max(Math.hypot(tipX - startX, tipY - startY), 1);
  const arrowLength = Math.min(COMPOSITION_PIPELINE_ARROW_LENGTH, visibleLength * 0.45);
  const baseX = tipX - unitX * arrowLength;
  const baseY = tipY - unitY * arrowLength;
  const perpendicularX = -unitY;
  const perpendicularY = unitX;
  const halfArrowWidth = COMPOSITION_PIPELINE_ARROW_WIDTH / 2;
  const path = `M ${startX} ${startY} L ${baseX} ${baseY}`;
  const points = [
    `${tipX},${tipY}`,
    `${baseX + perpendicularX * halfArrowWidth},${baseY + perpendicularY * halfArrowWidth}`,
    `${baseX - perpendicularX * halfArrowWidth},${baseY - perpendicularY * halfArrowWidth}`,
  ].join(" ");

  return (
    <g className="composition-pipeline-edge" data-edge-id={id}>
      <path className="composition-pipeline-edge-shadow" d={path} vectorEffect="non-scaling-stroke" />
      <path className="composition-pipeline-edge-path" d={path} vectorEffect="non-scaling-stroke" />
      <polygon className="composition-pipeline-edge-arrow" points={points} />
    </g>
  );
}

function CompositionPipelineNodeView({ data }: NodeProps<CompositionPipelineNode>) {
  const hasSpend = data.amountUsd > 0;
  const hasDuration = data.durationMs > 0;
  return (
    <div className={`composition-pipeline-node ${data.tone}`}>
      <Handle
        className="composition-pipeline-handle input"
        id="pipeline-input"
        isConnectable={false}
        position={Position.Left}
        type="target"
      />
      <span>{data.title}</span>
      <strong>{data.subtitle}</strong>
      {data.meta ? <small>{data.meta}</small> : null}
      <div>
        <em>{data.status}</em>
        {hasSpend ? <em>{formatUsd(data.amountUsd)}</em> : null}
        {hasDuration ? <em>{formatDurationMs(data.durationMs)}</em> : null}
      </div>
      <Handle
        className="composition-pipeline-handle output"
        id="pipeline-output"
        isConnectable={false}
        position={Position.Right}
        type="source"
      />
    </div>
  );
}

function importJobProgress(job: ImportJob) {
  if (job.status === "complete") return 100;
  if (job.status === "failed") return 100;
  if (job.status === "staged") return 0;
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

function importJobSortPriority(job: ImportJob) {
  if (job.status === "running") return 0;
  if (job.status === "failed") return 1;
  if (job.status === "restored_paused") return 2;
  if (job.status === "queued") return 3;
  if (job.status === "staged") return 4;
  if (job.status === "complete") return 5;
  if (job.status === "duplicate_skipped") return 6;
  if (job.status === "cleared") return 7;
  return 7;
}

function importJobTime(value?: string | null) {
  const timestamp = value ? new Date(value).getTime() : NaN;
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function compareImportJobs(left: ImportJob, right: ImportJob) {
  const priorityDelta = importJobSortPriority(left) - importJobSortPriority(right);
  if (priorityDelta) return priorityDelta;
  if (left.status === "running") {
    return importJobTime(left.locked_at || left.updated_at || left.created_at) - importJobTime(right.locked_at || right.updated_at || right.created_at);
  }
  if (left.status === "queued" || left.status === "staged" || left.status === "restored_paused") {
    return importJobTime(left.created_at) - importJobTime(right.created_at);
  }
  return importJobTime(right.updated_at || right.created_at) - importJobTime(left.updated_at || left.created_at);
}

function orderedImportJobs(jobs: ImportJob[]) {
  return [...jobs].sort(compareImportJobs);
}

function visibleImportJobs(jobs: ImportJob[], now: number, limit = IMPORT_JOB_LIST_LIMIT) {
  return orderedImportJobs(jobs.filter((job) => !isImportCompletedRowExpired(job, now))).slice(0, limit);
}

function importJobStage(job: ImportJob) {
  const pageMatch = job.current_step.match(/^normalizing_page_(\d+)$/);
  if (pageMatch) {
    const pageCount = job.document_page_count ? `/${job.document_page_count}` : "";
    return `normalizing page ${pageMatch[1]}${pageCount}`;
  }
  if (job.current_step === "staged") return "staged";
  return job.current_step.replaceAll("_", " ");
}

function importJobLabel(job: ImportJob) {
  const name = job.original_filename || job.document_title || job.current_step || "Import";
  const size = formatFileSize(job.file_size_bytes);
  return `${name}${size ? ` (${size})` : ""}${job.status === "complete" ? " (done)" : ""}`;
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
  if (job.status === "staged") return "staged";
  if (job.status === "queued") return "queued";
  if (job.status === "restored_paused") return "restored paused";
  return importJobStage(job);
}

function importJobEstimatePrefix(job: ImportJob) {
  if (job.estimated_cost_basis === "actual") return "";
  if (job.status === "staged" || job.status === "queued") return "rough ";
  return "";
}

function importJobEstimateTitle(job: ImportJob) {
  if (job.estimated_cost_basis === "actual") return "Known cost recorded so far.";
  const calibrated = job.estimated_cost_basis.startsWith("calibrated_");
  const basis = calibrated ? job.estimated_cost_basis.replace(/^calibrated_/, "") : job.estimated_cost_basis;
  const pageCount = job.estimated_cost_page_count || job.document_page_count;
  const pageText = pageCount ? ` across about ${pageCount} page${pageCount === 1 ? "" : "s"}` : "";
  const calibrationText = calibrated ? " and calibrated by prior estimate accuracy" : "";
  if (basis === "none") return "No model-cost estimate is available yet.";
  if (basis === "default") return `Rough estimate from the default per-page import cost${pageText}${calibrationText}.`;
  if (basis === "library_exemplar") return `Rough estimate from prior import costs per page${pageText}${calibrationText}.`;
  if (basis === "task_exemplar") return `Rough estimate from prior import task costs per page${pageText}${calibrationText}.`;
  if (basis === "mixed_exemplar") return `Rough estimate from prior task/model exemplars and task fallbacks${pageText}${calibrationText}.`;
  if (basis === "persisted_estimate") return `Persisted rough estimate captured when this upload was staged${pageText}${calibrationText}.`;
  return `Rough estimate from prior task/model exemplars${pageText}${calibrationText}.`;
}

function ImportJobStatusDetail({ job }: { job: ImportJob }) {
  const status = importJobStatusLabel(job);
  const model = modelDisplayName(job.current_model);
  const cost = formatUsd(job.estimated_cost_usd ?? 0);
  return (
    <small className="job-status-detail" title={job.status === "failed" ? job.last_error || undefined : importJobEstimateTitle(job)}>
      <strong>{status}</strong>
      {model ? ` (${model})` : ""}
      {` (${importJobEstimatePrefix(job)}${cost})`}
    </small>
  );
}

function importJobTone(job: ImportJob): "neutral" | "good" | "warn" | "blue" {
  if (job.status === "failed") return "warn";
  if (job.status === "complete" || job.status === "duplicate_skipped") return "good";
  if (job.status === "restored_paused" || job.status === "staged") return "neutral";
  return "blue";
}

function importJobShowsActivityGlyph(job: ImportJob) {
  return job.status === "queued" || job.status === "running" || job.status === "restored_paused";
}

function ImportJobRow({
  job,
  cancelBusy = false,
  cancelDisabled = false,
  cancelFeedback,
  cancelTitle,
  onCancel,
  onRetry,
  retryBusy = false,
  retryDisabled = false,
  retryFeedback,
  retryTitle,
  showCancelSlot = false,
  showRetrySlot = false,
}: {
  job: ImportJob;
  cancelBusy?: boolean;
  cancelDisabled?: boolean;
  cancelFeedback?: AsyncActionFeedback | null;
  cancelTitle?: string;
  onCancel?: () => void;
  onRetry?: () => void;
  retryBusy?: boolean;
  retryDisabled?: boolean;
  retryFeedback?: AsyncActionFeedback | null;
  retryTitle?: string;
  showCancelSlot?: boolean;
  showRetrySlot?: boolean;
}) {
  const progress = importJobProgress(job);
  const cancelSlot = showCancelSlot || onCancel;
  const retrySlot = showRetrySlot || onRetry;
  const showActivityGlyph = importJobShowsActivityGlyph(job);
  return (
    <div
      className={`job-row ${job.status}`}
      style={{ "--job-progress": `${progress}%` } as CSSProperties}
      title={`${importJobStatusLabel(job)}: ${progress}%`}
    >
      <span className="job-copy">
        <span>{importJobLabel(job)}</span>
        <ImportJobStatusDetail job={job} />
      </span>
      <span className="job-actions">
        <span className="job-status-cluster">
          {showActivityGlyph ? <Orbit aria-hidden="true" className="job-activity-glyph" size={15} /> : null}
          <StatusPill value={job.status} tone={importJobTone(job)} />
        </span>
        {retrySlot ? (
          <AsyncActionSlot busy={retryBusy} feedback={retryFeedback} label="Import retry in progress">
            <button
              aria-label={`Retry ${importJobLabel(job)}`}
              className={asyncFeedbackClass("icon-button compact job-retry-button", retryFeedback, retryBusy)}
              data-disabled-reason={!onRetry ? "there is no retry handler for this row." : retryTitle || importJobRetryTitle(job)}
              data-tooltip={retryTitle || importJobRetryTitle(job)}
              disabled={!onRetry || retryDisabled}
              onClick={onRetry}
              type="button"
            >
              <RefreshCw className={retryBusy ? "spin" : ""} size={15} />
            </button>
          </AsyncActionSlot>
        ) : null}
        {cancelSlot ? (
          <span className="job-cancel-slot">
            <AsyncActionSlot busy={cancelBusy} feedback={cancelFeedback} label="Import cancel in progress">
              <button
                aria-label={`Cancel ${importJobLabel(job)}`}
                className={asyncFeedbackClass("secondary-button compact job-cancel-button", cancelFeedback, cancelBusy)}
                data-disabled-reason={!onCancel ? "there is no cancel handler for this row." : cancelTitle || importJobCancelTitle(job)}
                data-tooltip={cancelTitle || importJobCancelTitle(job)}
                disabled={!onCancel || cancelDisabled}
                onClick={onCancel}
                type="button"
              >
                <X size={14} />
                Cancel
              </button>
            </AsyncActionSlot>
          </span>
        ) : null}
      </span>
    </div>
  );
}

function canRescueImportJob(job: ImportJob) {
  if (!job.document_id) return false;
  if (job.status === "failed" || job.status === "restored_paused") return true;
  if (job.status !== "running" || !job.locked_at) return false;
  return Date.now() - new Date(job.locked_at).getTime() > 15 * 60 * 1000;
}

function canRetryImportJob(job: ImportJob) {
  if (!job.document_id) return false;
  if (job.status === "complete" || job.status === "cleared" || job.status === "staged") return false;
  if (job.status === "running") return canRescueImportJob(job);
  return true;
}

function canCancelImportJob(job: ImportJob) {
  return job.status === "staged" || job.status === "queued" || job.status === "failed" || job.status === "restored_paused";
}

function importJobRetryTitle(job: ImportJob) {
  if (!job.document_id) return "This queue row has no document record to retry";
  if (job.status === "running" && !canRescueImportJob(job)) return "This import still has an active worker lock";
  return "Retry this import job";
}

function importJobCancelTitle(job: ImportJob) {
  if (job.status === "running") return "Running imports cannot be canceled while the worker lock is active";
  if (!canCancelImportJob(job)) return "This import cannot be canceled";
  if (job.status === "staged") return "Remove this staged upload before it is processed";
  return "Cancel this import/download";
}

function isImportCompletedRowExpired(job: ImportJob, now: number) {
  if (job.status === "cleared") return true;
  if (job.status !== "complete") return false;
  const completedAt = new Date(job.updated_at).getTime();
  if (Number.isNaN(completedAt)) return false;
  return now - completedAt >= IMPORT_COMPLETED_ROW_RETENTION_MS;
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
  const pattern = /(<u>.*?<\/u>|`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text))) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${match.index}`;
    if (token.startsWith("<u>")) nodes.push(<u key={key}>{token.slice(3, -4)}</u>);
    else if (token.startsWith("**")) nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith("*")) nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    else nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function stripMarkdownFormatting(value: string) {
  return value
    .replace(/\r/g, "")
    .split("\n")
    .map((line) =>
      line
        .replace(/^\s{0,3}#{1,6}\s+/, "")
        .replace(/^\s{0,3}>\s?/, "")
        .replace(/^\s*[-*]\s+/, "")
        .replace(/^\s*\d+[.)]\s+/, "")
        .replace(/<\/?(?:u|strong|em|b|i)>/gi, "")
        .replace(/\*\*([^*]+)\*\*/g, "$1")
        .replace(/__([^_]+)__/g, "$1")
        .replace(/\*([^*]+)\*/g, "$1")
        .replace(/_([^_]+)_/g, "$1")
        .replace(/`([^`]+)`/g, "$1"),
    )
    .join("\n");
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
    const quote = line.match(/^>\s?(.+)$/);
    if (quote) {
      flushParagraph();
      flushList();
      blocks.push(<blockquote key={`q-${blocks.length}`}>{renderInlineMarkdown(quote[1], `q-${blocks.length}`)}</blockquote>);
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
      data-tooltip={`Drag or use Left and Right arrow keys to ${label.toLocaleLowerCase()}.`}
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
            <input
              data-tooltip="Enter the Medusa account email for this local instance."
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            Password
            <input
              data-tooltip="Enter the Medusa password for this local instance."
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <button
            className="primary-button"
            data-disabled-reason="the sign-in request is already running."
            data-tooltip="Sign in to Medusa with the email and password in this form."
            type="submit"
            disabled={login.isPending}
          >
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
        <input
          data-tooltip="Type a global search query to filter documents by titles, notes, figures, citations, tags, domains, and searchable text."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search documents, notes, figures, citations..."
        />
      </label>
      <div className="topbar-actions">
        <HeaderWorkProgress dashboard={dashboard} jobs={backgroundJobs} onOpenQueue={onOpenQueue} />
        <span className="build-version" title={`Medusa build ${MEDUSA_BUILD_VERSION}`}>
          {MEDUSA_BUILD_VERSION}
        </span>
        <button
          className="icon-button"
          data-tooltip={theme === "day" ? "Switch Medusa to night mode." : "Switch Medusa to day mode."}
          onClick={() => setTheme(theme === "day" ? "night" : "day")}
        >
          {theme === "day" ? <Moon size={18} /> : <Sun size={18} />}
        </button>
        <button className="icon-button" data-tooltip="Sign out of this Medusa session." onClick={onLogout}>
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
  const handleNavClick = (event: ReactMouseEvent<HTMLAnchorElement>, view: View) => {
    if (event.defaultPrevented || event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    setActiveView(view);
  };

  return (
    <nav className="workspace-nav" aria-label="Main sections">
      {navItems.map((item) => {
        const Icon = item.icon;
        const rawCount = counts[item.id];
        const count = rawCount !== undefined && (item.id === "library" || rawCount > 0) ? formatNavCount(rawCount) : "";
        return (
          <a
            key={item.id}
            aria-current={activeView === item.id ? "page" : undefined}
            aria-keyshortcuts={item.shortcut}
            className={`workspace-nav-item${activeView === item.id ? " active" : ""}${item.align === "end" ? " settings" : ""}`}
            data-tooltip={`Open the ${item.label} workspace${item.shortcut ? `; keyboard shortcut ${item.shortcut}.` : "."}`}
            href={pathForView(item.id)}
            onClick={(event) => handleNavClick(event, item.id)}
          >
            <Icon size={17} />
            <span>{item.label}</span>
            {count ? <small className="workspace-nav-count">{count}</small> : null}
          </a>
        );
      })}
    </nav>
  );
}

function orderedDomainList(domains: Domain[]) {
  return [...domains].sort(
    (left, right) =>
      (left.sort_order ?? 0) - (right.sort_order ?? 0) ||
      left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" }),
  );
}

function domainChildrenByParent(domains: Domain[]) {
  return orderedDomainList(domains).reduce<Record<string, Domain[]>>((acc, domain) => {
    const parentKey = domain.parent_id || "root";
    acc[parentKey] = [...(acc[parentKey] || []), domain];
    return acc;
  }, {});
}

function domainPathLabel(domain: Domain, domains: Domain[]) {
  const byId = new Map(domains.map((item) => [item.id, item]));
  const parts: string[] = [];
  let current: Domain | undefined = domain;
  const seen = new Set<string>();
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    parts.unshift(current.name);
    current = current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return parts.join(" / ");
}

function descendantDomainIds(domainId: string, domains: Domain[]) {
  const children = domainChildrenByParent(domains);
  const ids = new Set<string>();
  const visit = (id: string) => {
    (children[id] || []).forEach((child) => {
      if (ids.has(child.id)) return;
      ids.add(child.id);
      visit(child.id);
    });
  };
  visit(domainId);
  return ids;
}

function DomainTree({ domains }: { domains: Domain[] }) {
  const children = useMemo(() => domainChildrenByParent(domains), [domains]);
  const roots = children.root || [];
  const domainIds = useMemo(() => new Set(domains.map((domain) => domain.id)), [domains]);

  const render = (domain: Domain, depth = 0) => (
    <div key={domain.id} className="domain-row" style={{ paddingLeft: 10 + depth * 16 }}>
      <span className="domain-dot" style={{ background: domain.color || "var(--blue)" }} />
      <span>{domain.name}</span>
      <small>{domain.document_count}</small>
      {(children[domain.id] || []).map((child) => render(child, depth + 1))}
    </div>
  );

  return (
    <div className="domain-tree">
      {roots.map((domain) => render(domain))}
      {domains
        .filter((domain) => domain.parent_id && !domainIds.has(domain.parent_id))
        .map((domain) => render(domain))}
    </div>
  );
}

function DomainsView({ domains, documents }: { domains: Domain[]; documents: DocumentSummary[] }) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const [searchText, setSearchText] = useState("");
  const [newName, setNewName] = useState("");
  const [newParentId, setNewParentId] = useState("");
  const [newColor, setNewColor] = useState(DOMAIN_COLOR_SWATCHES[0]);
  const [draft, setDraft] = useState<DomainUpdatePayload>({ name: "", parent_id: null, description: "", color: DOMAIN_COLOR_SWATCHES[0] });
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const children = useMemo(() => domainChildrenByParent(domains), [domains]);
  const selected = domains.find((domain) => domain.id === selectedId) || null;
  const selectedDescendants = useMemo(() => (selected ? descendantDomainIds(selected.id, domains) : new Set<string>()), [domains, selected]);
  const parentOptions = useMemo(
    () => domainPickerItems(domains.filter((domain) => !selected || (domain.id !== selected.id && !selectedDescendants.has(domain.id)))),
    [domains, selected, selectedDescendants],
  );
  const allParentOptions = useMemo(() => domainPickerItems(domains), [domains]);
  const selectedDocuments = useMemo(
    () => (selected ? documents.filter((document) => document.domains.some((domain) => domain.id === selected.id)) : []),
    [documents, selected],
  );
  const matchingDomains = useMemo(() => {
    const normalized = searchText.trim().toLowerCase();
    if (!normalized) return [];
    return orderedDomainList(domains).filter((domain) => domainPathLabel(domain, domains).toLowerCase().includes(normalized));
  }, [domains, searchText]);
  const selectedSiblings = useMemo(() => {
    if (!selected) return [];
    return children[selected.parent_id || "root"] || [];
  }, [children, selected]);
  const selectedSiblingIndex = selected ? selectedSiblings.findIndex((domain) => domain.id === selected.id) : -1;
  const selectedPath = selected ? domainPathLabel(selected, domains) : "";
  const selectedChildCount = selected ? (children[selected.id] || []).length : 0;
  const canSave = Boolean(selected && String(draft.name || "").trim());
  const createDomain = useMutation({
    mutationFn: () => api.createDomain(newName.trim(), newParentId || null, newColor),
    onSuccess: (domain) => {
      setSelectedId(domain.id);
      setNewName("");
      setNotice(`Added ${domain.name}`);
      setError(null);
      refreshDomainManagementData(queryClient);
    },
    onError: (mutationError) => setError(actionFailureMessage("Could not add domain", mutationError)),
  });
  const updateDomain = useMutation({
    mutationFn: ({ id, body }: { id: string; body: DomainUpdatePayload }) => api.updateDomain(id, body),
    onSuccess: (domain) => {
      setSelectedId(domain.id);
      setNotice(`Saved ${domain.name}`);
      setError(null);
      refreshDomainManagementData(queryClient);
    },
    onError: (mutationError) => setError(actionFailureMessage("Could not save domain", mutationError)),
  });
  const reorderDomains = useMutation({
    mutationFn: api.reorderDomains,
    onSuccess: () => {
      setNotice("Domain order updated");
      setError(null);
      refreshDomainManagementData(queryClient);
    },
    onError: (mutationError) => setError(actionFailureMessage("Could not reorder domains", mutationError)),
  });
  const deleteDomain = useMutation({
    mutationFn: api.deleteDomain,
    onSuccess: (result) => {
      setSelectedId((current) => (current === result.deleted_id ? domains.find((domain) => domain.id !== result.deleted_id)?.id || "" : current));
      setConfirmingDeleteId(null);
      setNotice(`Deleted domain; updated ${result.updated_documents} document${result.updated_documents === 1 ? "" : "s"}`);
      setError(null);
      refreshDomainManagementData(queryClient);
    },
    onError: (mutationError) => setError(actionFailureMessage("Could not delete domain", mutationError)),
  });

  useEffect(() => {
    if (!domains.length) {
      setSelectedId("");
      return;
    }
    if (!selectedId || !domains.some((domain) => domain.id === selectedId)) setSelectedId(orderedDomainList(domains)[0]?.id || "");
  }, [domains, selectedId]);

  useEffect(() => {
    if (!selected) return;
    setDraft({
      name: selected.name,
      parent_id: selected.parent_id || null,
      description: selected.description || "",
      color: normalizeHexColor(selected.color, DOMAIN_COLOR_SWATCHES[0]),
      sort_order: selected.sort_order,
    });
    setConfirmingDeleteId(null);
  }, [selected]);

  const saveSelected = () => {
    if (!selected || !canSave) return;
    updateDomain.mutate({
      id: selected.id,
      body: {
        name: String(draft.name || "").trim(),
        parent_id: draft.parent_id || null,
        description: String(draft.description || "").trim() || null,
        color: normalizeHexColor(draft.color, DOMAIN_COLOR_SWATCHES[0]),
        sort_order: typeof draft.sort_order === "number" ? draft.sort_order : selected.sort_order,
      },
    });
  };
  const moveSelected = (direction: -1 | 1) => {
    if (!selected || selectedSiblingIndex < 0) return;
    const targetIndex = selectedSiblingIndex + direction;
    if (targetIndex < 0 || targetIndex >= selectedSiblings.length) return;
    const nextSiblings = [...selectedSiblings];
    [nextSiblings[selectedSiblingIndex], nextSiblings[targetIndex]] = [nextSiblings[targetIndex], nextSiblings[selectedSiblingIndex]];
    reorderDomains.mutate(nextSiblings.map((domain, index) => ({ id: domain.id, parent_id: domain.parent_id || null, sort_order: index })));
  };
  const renderDomainButton = (domain: Domain, depth: number, pathOverride?: string) => {
    const childCount = (children[domain.id] || []).length;
    const selectedRow = selected?.id === domain.id;
    return (
      <button
        key={`${domain.id}-${pathOverride || "tree"}`}
        className={`domain-manager-row${selectedRow ? " selected" : ""}`}
        data-tooltip={`Select ${domain.name} in the domain editor.`}
        onClick={() => setSelectedId(domain.id)}
        style={{ paddingLeft: 12 + depth * 18 }}
        type="button"
      >
        <span className="domain-dot" style={{ background: domain.color || "var(--blue)" }} />
        <span className="domain-manager-row-text">
          <strong>{domain.name}</strong>
          <small>{pathOverride || `${childCount} child${childCount === 1 ? "" : "ren"} / ${domain.document_count} documents`}</small>
        </span>
        <small>{domain.document_count}</small>
      </button>
    );
  };
  const renderDomainNode = (domain: Domain, depth = 0): ReactNode => (
    <div key={domain.id}>
      {renderDomainButton(domain, depth)}
      {(children[domain.id] || []).map((child) => renderDomainNode(child, depth + 1))}
    </div>
  );
  const busy = createDomain.isPending || updateDomain.isPending || reorderDomains.isPending || deleteDomain.isPending;
  const domainBusyReason = createDomain.isPending
    ? "a domain create request is already running."
    : updateDomain.isPending
      ? "a domain save request is already running."
      : reorderDomains.isPending
        ? "a domain reorder request is already running."
        : deleteDomain.isPending
          ? "a domain delete request is already running."
          : "";

  return (
    <section className="workbench domains-workbench">
      <aside className="domain-directory">
        <div className="domain-create-panel">
          <div className="inline-form">
            <input data-tooltip="Type the name for a new domain." value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="New domain" />
            <button
              className="primary-button"
              data-disabled-reason={createDomain.isPending ? domainBusyReason : "a new domain name is required."}
              data-tooltip="Create this domain at the selected parent level."
              disabled={!newName.trim() || createDomain.isPending}
              onClick={() => createDomain.mutate()}
              type="button"
            >
              <Plus size={16} />
              Add
            </button>
          </div>
          <div className="domain-create-options">
            <select data-tooltip="Choose where the new domain will be nested." value={newParentId} onChange={(event) => setNewParentId(event.target.value)}>
              <option value="">Top-level</option>
              {allParentOptions.map((domain) => (
                <option key={domain.id} value={domain.id}>
                  {domain.name}
                </option>
              ))}
            </select>
            <input aria-label="New domain color" data-tooltip="Pick the color for the new domain." type="color" value={newColor} onChange={(event) => setNewColor(event.target.value)} />
          </div>
        </div>
        <label className="domain-search">
          <Search size={16} />
          <input data-tooltip="Type to search domain names and paths." value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search domains" />
        </label>
        <div className="domain-manager-tree">
          {searchText.trim()
            ? matchingDomains.map((domain) => renderDomainButton(domain, 0, domainPathLabel(domain, domains)))
            : (children.root || []).map((domain) => renderDomainNode(domain))}
          {!domains.length ? <p className="empty-note">No domains yet.</p> : null}
          {domains.length && searchText.trim() && !matchingDomains.length ? <p className="empty-note">No matching domains.</p> : null}
        </div>
      </aside>
      <section className="domain-editor">
        <div className="panel-title-row">
          <div>
            <h2>{selected?.name || "Domains"}</h2>
            <span>{selected ? selectedPath : "Create a domain to start organizing the library."}</span>
          </div>
          <FolderTree size={20} />
        </div>
        {error ? <p className="form-error">{error}</p> : null}
        {notice ? <p className="tag-operation-notice">{notice}</p> : null}
        {selected ? (
          <>
            <div className="domain-stat-grid">
              <span>
                <strong>{selected.document_count}</strong>
                Documents
              </span>
              <span>
                <strong>{selectedChildCount}</strong>
                Children
              </span>
              <span>
                <strong>{selected.parent_id ? "Nested" : "Root"}</strong>
                Level
              </span>
            </div>
            <div className="domain-edit-grid">
              <label>
                Name
                <input
                  data-tooltip="Edit the selected domain name."
                  value={String(draft.name || "")}
                  onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                />
              </label>
              <label>
                Parent
                <select data-tooltip="Choose the selected domain's parent domain." value={draft.parent_id || ""} onChange={(event) => setDraft((current) => ({ ...current, parent_id: event.target.value || null }))}>
                  <option value="">Top-level</option>
                  {parentOptions.map((domain) => (
                    <option key={domain.id} value={domain.id}>
                      {domain.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="domain-description-field">
                Description
                <textarea
                  data-tooltip="Edit the optional description for this domain."
                  value={String(draft.description || "")}
                  onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
                  placeholder="Optional scope note"
                />
              </label>
              <div className="domain-color-field">
                <span>Color</span>
                <div className="domain-color-controls">
                  {DOMAIN_COLOR_SWATCHES.map((color) => (
                    <button
                      key={color}
                      aria-label={`Use ${color}`}
                      className={normalizeHexColor(draft.color, DOMAIN_COLOR_SWATCHES[0]) === color ? "selected" : ""}
                      data-tooltip={`Set the selected domain color to ${color}.`}
                      onClick={() => setDraft((current) => ({ ...current, color }))}
                      style={{ background: color }}
                      type="button"
                    />
                  ))}
                  <input
                    aria-label="Domain color"
                    data-tooltip="Pick a custom color for the selected domain."
                    type="color"
                    value={normalizeHexColor(draft.color, DOMAIN_COLOR_SWATCHES[0])}
                    onChange={(event) => setDraft((current) => ({ ...current, color: event.target.value }))}
                  />
                </div>
              </div>
            </div>
            <div className="domain-editor-actions">
              <button
                className="primary-button"
                data-disabled-reason={busy ? domainBusyReason : "the selected domain needs a name."}
                data-tooltip="Save the selected domain's name, parent, description, color, and ordering metadata."
                disabled={!canSave || busy}
                onClick={saveSelected}
                type="button"
              >
                <Save size={16} />
                Save
              </button>
              <button
                className="secondary-button"
                data-disabled-reason={busy ? domainBusyReason : "the selected domain is already first among its siblings."}
                data-tooltip="Move the selected domain up among siblings."
                disabled={selectedSiblingIndex <= 0 || busy}
                onClick={() => moveSelected(-1)}
                type="button"
              >
                <ArrowUp size={16} />
                Up
              </button>
              <button
                className="secondary-button"
                data-disabled-reason={busy ? domainBusyReason : "the selected domain is already last among its siblings."}
                data-tooltip="Move the selected domain down among siblings."
                disabled={selectedSiblingIndex < 0 || selectedSiblingIndex >= selectedSiblings.length - 1 || busy}
                onClick={() => moveSelected(1)}
                type="button"
              >
                <ArrowDown size={16} />
                Down
              </button>
              <button
                className="secondary-button"
                data-disabled-reason={domainBusyReason}
                data-tooltip="Prepare the new-domain form to create a child under the selected domain."
                disabled={busy}
                onClick={() => {
                  setNewParentId(selected.id);
                  setNewName("");
                }}
                type="button"
              >
                <CornerDownRight size={16} />
                Add Child
              </button>
              <button
                className="secondary-button danger"
                data-disabled-reason={domainBusyReason}
                data-tooltip="Open a confirmation prompt to soft-delete this domain and detach it from affected documents and notes."
                disabled={busy}
                onClick={() => setConfirmingDeleteId(selected.id)}
                type="button"
              >
                <Trash2 size={16} />
                Delete
              </button>
            </div>
            {confirmingDeleteId === selected.id ? (
              <div className="domain-delete-confirm">
                <span>Delete {selected.name}?</span>
                <button
                  className="secondary-button compact"
                  data-disabled-reason="the domain delete request is already running."
                  data-tooltip="Cancel domain deletion and close this confirmation prompt."
                  disabled={deleteDomain.isPending}
                  onClick={() => setConfirmingDeleteId(null)}
                  type="button"
                >
                  <X size={15} />
                  Cancel
                </button>
                <button
                  className="primary-button compact"
                  data-disabled-reason="the domain delete request is already running."
                  data-tooltip="Confirm soft deletion of this domain, detach it from documents and notes, and preserve affected history/search updates."
                  disabled={deleteDomain.isPending}
                  onClick={() => deleteDomain.mutate(selected.id)}
                  type="button"
                >
                  <Trash2 size={15} />
                  Confirm
                </button>
              </div>
            ) : null}
          </>
        ) : (
          <p className="empty-note">Create a domain, then select it to edit nesting, color, order, and document assignments.</p>
        )}
      </section>
      <aside className="domain-documents-panel">
        <div className="panel-title-row">
          <div>
            <h2>Documents</h2>
            <span>{selected ? `${selectedDocuments.length} direct matches` : "No domain selected"}</span>
          </div>
          <FileText size={20} />
        </div>
        <div className="domain-document-list">
          {selectedDocuments.map((document) => (
            <article key={document.id} className="domain-document-row">
              <strong>{document.title}</strong>
              <span>
                {authorLine(document)}
                {document.publication_year ? ` / ${document.publication_year}` : ""}
              </span>
            </article>
          ))}
          {selected && !selectedDocuments.length ? <p className="empty-note">No documents are directly assigned to this domain.</p> : null}
          {!selected ? <p className="empty-note">Select a domain to inspect assigned documents.</p> : null}
        </div>
      </aside>
    </section>
  );
}

function refreshDomainManagementData(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["domains"] });
  void queryClient.invalidateQueries({ queryKey: ["documents"] });
  void queryClient.invalidateQueries({ queryKey: ["document"] });
  void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  void queryClient.invalidateQueries({ queryKey: ["notes"] });
}

function BulkMultiSelect({
  createFromSearchLabel,
  emptyLabel,
  extraCount = 0,
  footer,
  label,
  onCreateFromSearch,
  onChange,
  options,
  selectedIds,
  searchPlaceholder = "Type to filter",
}: {
  createFromSearchLabel?: string;
  emptyLabel: string;
  extraCount?: number;
  footer?: ReactNode;
  label: string;
  onCreateFromSearch?: (value: string) => void;
  onChange: (ids: string[]) => void;
  options: Array<{ id: string; name: string }>;
  selectedIds: string[];
  searchPlaceholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const selectedCount = selectedIds.length + extraCount;
  const selectedOptions = options.filter((option) => selectedIds.includes(option.id));
  const triggerLabel =
    selectedCount === 1 && selectedOptions[0]
      ? selectedOptions[0].name
      : selectedCount
        ? `${label} ${selectedCount}`
        : label;
  const matchingOptions = useMemo(() => matchingSelectOptions(options, searchText), [options, searchText]);
  const visibleOptions = useMemo(() => visibleSelectOptions(matchingOptions), [matchingOptions]);
  const hiddenOptionCount = Math.max(0, matchingOptions.length - visibleOptions.length);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", closeOnOutsideClick);
    return () => window.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);
  useEscapeLayer(open, () => setOpen(false), ESCAPE_PRIORITY_MENU);
  useEffect(() => {
    if (!open) {
      setSearchText("");
      setActiveIndex(0);
      return;
    }
    const handle = window.setTimeout(() => searchRef.current?.focus(), 0);
    return () => window.clearTimeout(handle);
  }, [open]);
  useEffect(() => {
    setActiveIndex(0);
  }, [searchText, open]);

  const toggleId = (id: string) => {
    onChange(selectedIds.includes(id) ? selectedIds.filter((selectedId) => selectedId !== id) : uniqueValues([...selectedIds, id]));
  };
  const chooseActive = () => {
    const option = visibleOptions[activeIndex];
    if (option) {
      toggleId(option.id);
      return;
    }
    const customValue = searchText.trim();
    if (customValue && onCreateFromSearch) {
      onCreateFromSearch(customValue);
      setSearchText("");
    }
  };

  return (
    <div className="bulk-multi-select" ref={wrapperRef}>
      <button
        aria-expanded={open}
        aria-haspopup="listbox"
        className="bulk-multi-trigger"
        data-tooltip={`Open the ${label} picker to search, select, or clear ${label.toLocaleLowerCase()} values.`}
        type="button"
        onClick={() => setOpen((value) => !value)}
      >
        <span>{triggerLabel}</span>
        <ChevronRight size={14} />
      </button>
      {open ? (
        <div className="bulk-multi-menu">
          <input
            ref={searchRef}
            className="select-search-input"
            data-tooltip={`Type to filter ${label.toLocaleLowerCase()} options; press Enter to toggle the highlighted match${onCreateFromSearch ? " or create the typed value" : ""}.`}
            onChange={(event) => setSearchText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex((index) => Math.min(Math.max(0, visibleOptions.length - 1), index + 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex((index) => Math.max(0, index - 1));
              } else if (event.key === "Enter") {
                event.preventDefault();
                chooseActive();
              }
            }}
            placeholder={searchPlaceholder}
            value={searchText}
          />
          {visibleOptions.length ? (
            visibleOptions.map((option, index) => (
              <label className={index === activeIndex ? "active" : ""} key={option.id}>
                <input type="checkbox" checked={selectedIds.includes(option.id)} onChange={() => toggleId(option.id)} />
                <span>{option.name}</span>
              </label>
            ))
          ) : (
            <div className="bulk-multi-empty">
              {searchText.trim() && onCreateFromSearch ? `${createFromSearchLabel || "Add"} "${searchText.trim()}" with Enter` : emptyLabel}
            </div>
          )}
          {hiddenOptionCount > 0 ? <div className="bulk-multi-note">Type to narrow {hiddenOptionCount} more</div> : null}
          {footer ? <div className="bulk-multi-footer">{footer}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function LibrarySingleSelect({
  emptyLabel,
  onChange,
  options,
  placeholder,
  searchPlaceholder = "Type to filter",
  value,
}: {
  emptyLabel: string;
  onChange: (value: string) => void;
  options: SelectMenuOption[];
  placeholder: string;
  searchPlaceholder?: string;
  value: string;
}) {
  const [open, setOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const selected = options.find((option) => option.id === value);
  const matchingOptions = useMemo(() => matchingSelectOptions(options, searchText), [options, searchText]);
  const visibleOptions = useMemo(() => visibleSelectOptions(matchingOptions), [matchingOptions]);
  const hiddenOptionCount = Math.max(0, matchingOptions.length - visibleOptions.length);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", closeOnOutsideClick);
    return () => window.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);
  useEscapeLayer(open, () => setOpen(false), ESCAPE_PRIORITY_MENU);
  useEffect(() => {
    if (!open) {
      setSearchText("");
      setActiveIndex(0);
      return;
    }
    const handle = window.setTimeout(() => searchRef.current?.focus(), 0);
    return () => window.clearTimeout(handle);
  }, [open]);
  useEffect(() => {
    setActiveIndex(0);
  }, [searchText, open]);

  const choose = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
  };
  const chooseActive = () => {
    const option = visibleOptions[activeIndex];
    if (option) choose(option.id);
    else if (!searchText.trim()) choose("");
  };

  return (
    <div className="bulk-multi-select library-single-select" ref={wrapperRef}>
      <button
        aria-expanded={open}
        aria-haspopup="listbox"
        className={`bulk-multi-trigger ${selected ? "has-value" : ""}`}
        data-tooltip={`Open the ${placeholder} dropdown to search and choose one value.`}
        type="button"
        onClick={() => setOpen((value) => !value)}
      >
        <span>{selected?.name || placeholder}</span>
        <ChevronRight size={14} />
      </button>
      {open ? (
        <div className="bulk-multi-menu single-select-menu" role="listbox">
          <input
            ref={searchRef}
            className="select-search-input"
            data-tooltip={`Type to filter ${placeholder.toLocaleLowerCase()} options; press Enter to choose the highlighted match.`}
            onChange={(event) => setSearchText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex((index) => Math.min(Math.max(0, visibleOptions.length - 1), index + 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex((index) => Math.max(0, index - 1));
              } else if (event.key === "Enter") {
                event.preventDefault();
                chooseActive();
              }
            }}
            placeholder={searchPlaceholder}
            value={searchText}
          />
          <button
            aria-selected={!value}
            className={!value && !searchText ? "selected" : ""}
            data-tooltip={`Clear this filter back to ${placeholder}.`}
            role="option"
            type="button"
            onClick={() => choose("")}
          >
            <span>{placeholder}</span>
          </button>
          {visibleOptions.length ? (
            visibleOptions.map((option, index) => (
              <button
                aria-selected={value === option.id}
                className={[value === option.id ? "selected" : "", index === activeIndex ? "active" : ""].filter(Boolean).join(" ")}
                data-tooltip={`Choose ${option.name} for this ${placeholder.toLocaleLowerCase()} filter.`}
                key={option.id}
                role="option"
                type="button"
                onClick={() => choose(option.id)}
              >
                <span>{option.name}</span>
              </button>
            ))
          ) : (
            <div className="bulk-multi-empty">{emptyLabel}</div>
          )}
          {hiddenOptionCount > 0 ? <div className="bulk-multi-note">Type to narrow {hiddenOptionCount} more</div> : null}
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
  setSelectedId: (id: string, options?: { updateUrl?: boolean }) => void;
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
  const queryClient = useQueryClient();
  const titleCleanupFeedback = useAsyncActionFeedback();
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
  const titleCleanup = useMutation({
    mutationFn: api.cleanupDocumentTitles,
    onSuccess: () => {
      titleCleanupFeedback.showSuccess();
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => {
      titleCleanupFeedback.showError(actionFailureMessage("Could not clean up titles", error));
    },
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
  useEscapeLayer(readerOpen, () => setReaderOpen(false), ESCAPE_PRIORITY_READER);
  const paneStyle = {
    "--filter-pane-width": `${filterWidth}px`,
    "--detail-pane-width": `${detailWidth}px`,
  } as CSSProperties;
  const sortedDocuments = useMemo(
    () =>
      [...documents].sort((left, right) => {
        const titleOrder = left.title.trim().localeCompare(right.title.trim(), undefined, { sensitivity: "base", numeric: true });
        return titleOrder || left.id.localeCompare(right.id);
      }),
    [documents],
  );
  const allVisibleSelected = sortedDocuments.length > 0 && sortedDocuments.every((item) => selectedIds.includes(item.id));
  const domainOptions = useMemo(() => domainPickerItems(domains).map(({ id, name }) => ({ id, name })), [domains]);
  const sortedTags = useMemo(() => [...tags].sort((left, right) => left.name.localeCompare(right.name)), [tags]);
  const tagOptions = useMemo(() => sortedTags.map(({ id, name }) => ({ id, name })), [sortedTags]);
  const sortedProjects = useMemo(() => [...projects].sort((left, right) => left.name.localeCompare(right.name)), [projects]);
  const projectOptions = useMemo(() => sortedProjects.map(({ id, name }) => ({ id, name })), [sortedProjects]);
  const savedSearchLookup = useMemo(
    () => ({
      domains: new Map(domainOptions.map((option) => [option.id, option.name])),
      tags: new Map(tagOptions.map((option) => [option.id, option.name])),
    }),
    [domainOptions, tagOptions],
  );
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

  const activateDocument = (id: string, options?: { updateUrl?: boolean }) => {
    setSelectedId(id, options);
  };

  const handleDocumentLinkClick = (event: ReactMouseEvent<HTMLAnchorElement>, id: string) => {
    event.stopPropagation();
    if (event.defaultPrevented || event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    activateDocument(id);
  };

  const toggleSelected = (id: string) => {
    activateDocument(id, { updateUrl: false });
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
          preferences={preferences}
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
          <div className="filter-field">
            <span>Domain</span>
            <LibrarySingleSelect
              emptyLabel="No domains"
              onChange={(value) => setFilterValue("domain_id", value)}
              options={domainOptions}
              placeholder="Any domain"
              value={filters.domain_id || ""}
            />
          </div>
          <div className="filter-field">
            <span>Tag</span>
            <LibrarySingleSelect
              emptyLabel="No tags"
              onChange={(value) => setFilterValue("tag_id", value)}
              options={tagOptions}
              placeholder="Any tag"
              value={filters.tag_id || ""}
            />
          </div>
          <div className="filter-field">
            <span>Read</span>
            <LibrarySingleSelect
              emptyLabel="No read statuses"
              onChange={(value) => setFilterValue("read_status", value)}
              options={READ_STATUS_OPTIONS}
              placeholder="Any read status"
              value={filters.read_status || ""}
            />
          </div>
          <div className="filter-field">
            <span>Priority</span>
            <LibrarySingleSelect
              emptyLabel="No priorities"
              onChange={(value) => setFilterValue("priority", value)}
              options={PRIORITY_OPTIONS}
              placeholder="Any priority"
              value={filters.priority || ""}
            />
          </div>
          <div className="filter-field">
            <span>Citation</span>
            <LibrarySingleSelect
              emptyLabel="No citation statuses"
              onChange={(value) => setFilterValue("citation_status", value)}
              options={CITATION_STATUS_OPTIONS}
              placeholder="Any citation status"
              value={filters.citation_status || ""}
            />
          </div>
          <div className="filter-field">
            <span>Duplicates</span>
            <LibrarySingleSelect
              emptyLabel="No duplicate statuses"
              onChange={(value) => setFilterValue("duplicate_status", value)}
              options={DUPLICATE_STATUS_OPTIONS}
              placeholder="Any duplicate status"
              value={filters.duplicate_status || ""}
            />
          </div>
          <button className="secondary-button" data-tooltip="Clear all Library filters and show the unfiltered document list." onClick={() => setFilters(emptyFilters())}>
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
          <input data-tooltip="Type a name for the current Library filter view." value={saveName} onChange={(event) => setSaveName(event.target.value)} placeholder="Name current view" />
          <button
            className="secondary-button"
            type="submit"
            data-disabled-reason={saveSearch.isPending ? "a saved-search create request is already running." : "a saved-search name is required."}
            data-tooltip="Save the current Library filters as a reusable saved search."
            disabled={!saveName.trim() || saveSearch.isPending}
          >
            <Save size={14} />
          </button>
        </form>
        <div className="saved-search-list">
          {savedSearches.map((savedSearch) => (
            <div key={savedSearch.id}>
              <button
                className="saved-search-apply"
                data-tooltip={`Apply the ${savedSearch.name} saved search filters to the Library.`}
                type="button"
                onClick={() => applySavedSearch(savedSearch)}
              >
                <span>
                  <strong>{savedSearch.name}</strong>
                  <small>{savedSearchSummary(savedSearch, savedSearchLookup)}</small>
                </span>
                {savedSearch.filters.priority ? <PriorityPill value={savedSearch.filters.priority} /> : null}
              </button>
              <button type="button" data-tooltip={`Delete the ${savedSearch.name} saved search.`} onClick={() => deleteSearch.mutate(savedSearch.id)}>
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
        <div className="domain-tool-row">
          <AsyncActionSlot busy={titleCleanup.isPending} feedback={titleCleanupFeedback.feedback} label="Title cleanup in progress">
            <button
              className={asyncFeedbackClass("secondary-button", titleCleanupFeedback.feedback, titleCleanup.isPending)}
              data-disabled-reason={
                titleCleanup.isPending
                  ? "title cleanup is already running."
                  : !documents.length
                    ? "there are no documents to clean up."
                    : ""
              }
              data-tooltip="Normalize every document title by trimming leading and trailing whitespace and collapsing repeated whitespace to one space."
              disabled={titleCleanup.isPending || !documents.length}
              onClick={() => titleCleanup.mutate()}
              type="button"
            >
              <Eraser className={titleCleanup.isPending ? "spin" : ""} size={15} />
              Title Cleanup
            </button>
          </AsyncActionSlot>
        </div>
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
              data-tooltip={allVisibleSelected ? "Clear the selection for every visible document." : "Select every visible document in the current Library result list."}
              type="checkbox"
              checked={allVisibleSelected}
              onChange={() => {
                if (allVisibleSelected) {
                  setSelectedIds([]);
                  return;
                }
                setSelectedIds(sortedDocuments.map((item) => item.id));
                if (sortedDocuments[0]) activateDocument(sortedDocuments[0].id, { updateUrl: false });
              }}
            />
            <strong>{loading ? "Searching..." : `${sortedDocuments.length} documents`}</strong>
          </label>
          {selectedIds.length ? (
            <div className="bulk-bar">
              <span>{selectedIds.length} selected</span>
              <LibrarySingleSelect
                emptyLabel="No read statuses"
                onChange={setBulkReadStatus}
                options={READ_STATUS_OPTIONS}
                placeholder="Read status"
                value={bulkReadStatus}
              />
              <LibrarySingleSelect
                emptyLabel="No priorities"
                onChange={setBulkPriority}
                options={PRIORITY_OPTIONS}
                placeholder="Priority"
                value={bulkPriority}
              />
              <BulkMultiSelect
                createFromSearchLabel="Add tag"
                emptyLabel="No tags"
                extraCount={bulkCustomTag.trim() ? 1 : 0}
                footer={
                  <input
                    className="bulk-custom-tag"
                    data-tooltip="Type a new tag to include in the pending bulk tag update."
                    placeholder="New tag"
                    value={bulkCustomTag}
                    onChange={(event) => setBulkCustomTag(event.target.value)}
                  />
                }
                label="Tags"
                onCreateFromSearch={setBulkCustomTag}
                onChange={setBulkTagIds}
                options={tagOptions}
                searchPlaceholder="Type tag text"
                selectedIds={bulkTagIds}
              />
              <LibrarySingleSelect
                emptyLabel="No domains"
                onChange={setBulkDomainId}
                options={domainOptions}
                placeholder="Domain"
                value={bulkDomainId}
              />
              <BulkMultiSelect
                emptyLabel="No projects"
                label="Project"
                onChange={setBulkProjectIds}
                options={projectOptions}
                searchPlaceholder="Type project name"
                selectedIds={bulkProjectIds}
              />
              <button
                className="primary-button"
                data-disabled-reason={bulkUpdate.isPending ? "a bulk update is already saving." : "choose at least one bulk edit value first."}
                data-tooltip="Apply the selected bulk read status, priority, tags, domain, and projects to the selected documents."
                disabled={!hasBulkUpdate || bulkUpdate.isPending}
                onClick={() => bulkUpdate.mutate()}
              >
                <CheckSquare size={15} />
                Apply
              </button>
            </div>
          ) : null}
        </div>
        <div className={`rows ${alternatingRows ? "alternating-rows" : ""}`}>
          {sortedDocuments.map((item) => (
            <div
              key={item.id}
              className={`doc-row ${selectedId === item.id ? "selected" : ""}`}
              onClick={() => activateDocument(item.id)}
            >
              <input
                aria-label={`Select ${item.title}`}
                data-tooltip={`Toggle selection for ${item.title} for bulk edits.`}
                checked={selectedIds.includes(item.id)}
                onClick={(event) => event.stopPropagation()}
                onPointerDown={(event) => event.stopPropagation()}
                onChange={() => toggleSelected(item.id)}
                type="checkbox"
              />
              <a
                className="doc-row-main"
                data-tooltip={`Open ${item.title} in the detail pane.`}
                href={pathForDocument(item.id)}
                onClick={(event) => handleDocumentLinkClick(event, item.id)}
              >
                <span className="doc-row-title">{item.title}</span>
                <span className="doc-row-byline">
                  <span className="doc-row-pages">{pageCountMarker(item)}</span>
                  <span className="doc-row-year">{item.publication_year || "n.d."}</span>
                  <span className="doc-row-authors">{authorLine(item)}</span>
                </span>
              </a>
              <div className="row-meta">
                <PriorityPill value={item.priority} />
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
type CitationRefreshTarget = CitationKind | "doi";

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
    tag_names: normalizedNameList(document.tags.map((tag) => tag.name)).join(", "),
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

function RecommendationsPanel({ document, onClose }: { document: DocumentDetail; onClose?: () => void }) {
  const [hideExisting, setHideExisting] = useStoredBoolean("medusa-recommendations-hide-existing-v2", true);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const autoRefreshKeyRef = useRef<string | null>(null);
  const { copiedKey, copyToClipboard } = useClipboardNotice();
  const queryClient = useQueryClient();
  const refreshFeedback = useAsyncActionFeedback();
  const selectedDownloadFeedback = useAsyncActionFeedback();
  const newDownloadFeedback = useAsyncActionFeedback();
  const stashFeedback = useAsyncActionFeedbackMap();
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
  const stashDoi = useMutation({
    mutationFn: (item: DocumentRecommendation) =>
      api.createDoiStash({
        doi: item.doi || "",
        title: item.title,
        source_url: item.source_url || undefined,
        source_provider: item.source_provider,
        source_document_id: item.source_document_id,
        recommendation_id: item.id,
      }),
    onSuccess: (_stash, item) => {
      stashFeedback.showSuccess(item.id);
      setNotice(`Stashed DOI ${item.doi}`);
      void queryClient.invalidateQueries({ queryKey: ["doi-stashes"] });
    },
    onError: (error, item) => {
      const message = actionFailureMessage("Could not stash DOI", error);
      stashFeedback.showError(item.id, message);
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

  useEffect(() => {
    const autoRefreshKey = `${document.id}:${hideExisting}`;
    if (
      !canRefresh ||
      recommendations.isFetching ||
      recommendations.isError ||
      refresh.isPending ||
      recommendations.data === undefined ||
      rows.length > 0 ||
      autoRefreshKeyRef.current === autoRefreshKey
    ) {
      return;
    }
    autoRefreshKeyRef.current = autoRefreshKey;
    refresh.mutate();
  }, [
    canRefresh,
    document.id,
    hideExisting,
    recommendations.data,
    recommendations.isError,
    recommendations.isFetching,
    refresh,
    rows.length,
  ]);

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
              data-disabled-reason={
                refresh.isPending
                  ? "recommendation refresh is already running."
                  : "recommendations need a completed document with a DOI."
              }
              data-tooltip="Refresh related-paper recommendations for this document from scholarly metadata services."
              disabled={!canRefresh || refresh.isPending}
              onClick={() => refresh.mutate()}
              type="button"
            >
              <RefreshCw className={refresh.isPending ? "spin" : ""} size={14} />
              Refresh
            </button>
          </AsyncActionSlot>
          {onClose ? (
            <button className="icon-button compact" data-tooltip="Close the related-papers recommendations panel." onClick={onClose} type="button">
              <X size={15} />
            </button>
          ) : null}
        </div>
      </div>
      <div className="recommendations-download-row">
        <label className="select-all-row">
          <input
            data-disabled-reason="there are no new recommendations available for selection."
            data-tooltip={allSelectableSelected ? "Clear all selectable recommendation rows." : "Select all new recommendation rows that are not already in the library."}
            type="checkbox"
            checked={allSelectableSelected}
            onChange={toggleAllSelectable}
            disabled={!selectableRows.length}
          />
          <strong>{selectedCount ? `${selectedCount} selected` : "Select new papers"}</strong>
        </label>
        <AsyncActionSlot feedback={selectedDownloadFeedback.feedback}>
          <button
            className={asyncFeedbackClass("secondary-button compact", selectedDownloadFeedback.feedback)}
            data-disabled-reason={
              download.isPending
                ? "recommendation downloads are already being queued."
                : !selectedCount
                  ? "select one or more new recommendation rows first."
                  : "none of the selected recommendations has an open PDF URL."
            }
            data-tooltip="Queue imports for the selected new recommendations that have open PDF URLs."
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
            data-disabled-reason={
              download.isPending
                ? "recommendation downloads are already being queued."
                : !newRows.length
                  ? "there are no new recommendation rows."
                  : "no new recommendation has an open PDF URL."
            }
            data-tooltip="Queue imports for every new recommendation that has an open PDF URL."
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
            const doiCopied = copiedKey === `doi-${item.id}`;
            const titleCopied = copiedKey === `title-${item.id}`;
            const statusPill = inLibrary ? (
              <StatusPill value="In library" tone="good" />
            ) : item.status === "download_failed" ? (
              <StatusPill value="Download failed" tone="warn" />
            ) : item.has_pdf ? (
              <StatusPill value="PDF" tone="blue" />
            ) : null;
            return (
              <article key={item.id} className={`recommendation-row ${inLibrary ? "in-library" : ""}`}>
                <input
                  aria-label={`Select ${item.title}`}
                  data-disabled-reason="this recommendation is already in the library or has already been imported."
                  data-tooltip={`Toggle selection for ${item.title} before queueing recommendation imports.`}
                  type="checkbox"
                  checked={selectedIds.includes(item.id)}
                  disabled={inLibrary}
                  onChange={() => toggleSelected(item.id)}
                />
                <strong className="recommendation-title">{item.title}</strong>
                <div className="recommendation-row-status">{statusPill}</div>
                <div className="recommendation-copy">
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
                  <div className="recommendation-left-actions">
                    <button
                      className={`secondary-button compact recommendation-copy-action${doiCopied ? " copy-acknowledged" : ""}`}
                      data-disabled-reason="this recommendation does not include a DOI."
                      data-tooltip="Copy this recommendation DOI to the clipboard."
                      disabled={!item.doi}
                      onClick={() => item.doi && void copyToClipboard(`doi-${item.id}`, item.doi)}
                      type="button"
                    >
                      {doiCopied ? <CheckCircle2 size={15} /> : <Clipboard size={15} />}
                      DOI
                    </button>
                    <button
                      className={`secondary-button compact recommendation-copy-action${titleCopied ? " copy-acknowledged" : ""}`}
                      data-tooltip="Copy this recommendation title to the clipboard."
                      onClick={() => void copyToClipboard(`title-${item.id}`, item.title)}
                      type="button"
                    >
                      {titleCopied ? <CheckCircle2 size={15} /> : <Clipboard size={15} />}
                      Title
                    </button>
                    <AsyncActionSlot feedback={stashFeedback.feedbackFor(item.id)}>
                      <button
                        className={asyncFeedbackClass("secondary-button compact recommendation-copy-action", stashFeedback.feedbackFor(item.id))}
                        data-disabled-reason={stashDoi.isPending ? "a DOI stash request is already running." : "this recommendation does not include a DOI to stash."}
                        data-tooltip="Save this DOI to Stashes for later PDF follow-up."
                        disabled={!item.doi || stashDoi.isPending}
                        onClick={() => stashDoi.mutate(item)}
                        type="button"
                      >
                        <Bookmark size={15} />
                        Stash
                      </button>
                    </AsyncActionSlot>
                    <a
                      className="secondary-button compact recommendation-copy-action"
                      href={item.scholar_url}
                      target="_blank"
                      rel="noreferrer"
                      data-tooltip="Open a manual Google Scholar search for this recommendation in a new tab."
                    >
                      <Search size={15} />
                      Scholar
                    </a>
                  </div>
                  {item.source_url ? (
                    <a
                      className="icon-button compact recommendation-source-action"
                      href={item.source_url}
                      target="_blank"
                      rel="noreferrer"
                      data-tooltip="Open this recommendation's source page in a new tab."
                    >
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
          <span>{refresh.isPending ? "Finding related papers." : "No related papers found yet."}</span>
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
  const estimateComparison = composition?.estimate_comparison || null;
  const pipelineGraph = useMemo(() => pipelineNodesAndEdges(pipeline), [pipeline]);
  const duration = formatDuration(composition?.total_duration_seconds);
  useEscapeLayer(true, onClose, ESCAPE_PRIORITY_DIALOG);
  return (
    <div
      className="modal-backdrop composition-backdrop"
      data-escape-layer="dialog"
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
          <button className="icon-button" type="button" data-tooltip="Close the document composition dialog." onClick={onClose}>
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
            {estimateComparison ? (
              <section className="composition-section composition-estimate-panel">
                <div className="composition-section-title">
                  <div>
                    <h3>Estimate vs Actual</h3>
                    <span>{compositionEstimateBasisLabel(estimateComparison.basis)}</span>
                  </div>
                  <strong>{compositionEstimateStatusLabel(estimateComparison.status)}</strong>
                </div>
                <div className="composition-estimate-grid">
                  <div className="composition-estimate-row">
                    <span>Estimated</span>
                    <strong>{formatUsd(estimateComparison.estimated_cost_usd)}</strong>
                    <small>
                      {estimateComparison.estimated_page_count
                        ? `${estimateComparison.estimated_page_count} pages`
                        : "Page count unavailable"}
                    </small>
                  </div>
                  <div className="composition-estimate-row">
                    <span>Actual</span>
                    <strong>{formatUsd(estimateComparison.actual_cost_usd)}</strong>
                    <small>{estimateComparison.actual_cost_usd > 0 ? "Recorded model spend" : "Not recorded yet"}</small>
                  </div>
                  <div className="composition-estimate-row">
                    <span>Difference</span>
                    <strong>{formatSignedUsd(estimateComparison.variance_usd)}</strong>
                    <small>{formatSignedPercent(estimateComparison.variance_percent)}</small>
                  </div>
                </div>
              </section>
            ) : null}
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
                    edgeTypes={compositionPipelineEdgeTypes}
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
  const titleEditInputRef = useRef<HTMLInputElement | null>(null);
  const doiEditInputRef = useRef<HTMLInputElement | null>(null);
  const summaryTextareaRef = useRef<HTMLTextAreaElement | null>(null);
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
  const [editingDoi, setEditingDoi] = useState(false);
  const [doiDraft, setDoiDraft] = useState(document.doi || "");
  const [doiEditError, setDoiEditError] = useState<string | null>(null);
  const [editingSummary, setEditingSummary] = useState(false);
  const [summaryDraft, setSummaryDraft] = useState(document.rich_summary || "");
  const [summaryEditError, setSummaryEditError] = useState<string | null>(null);
  const [tagNameDraft, setTagNameDraft] = useState("");
  const [tagEditError, setTagEditError] = useState<string | null>(null);
  const [documentConcordanceRunId, setDocumentConcordanceRunId] = useState<string | null>(null);
  const [citationRunId, setCitationRunId] = useState<string | null>(null);
  const [citationRefreshTarget, setCitationRefreshTarget] = useState<CitationRefreshTarget | null>(null);
  const [summaryRunId, setSummaryRunId] = useState<string | null>(null);
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
  const doiRefreshFeedback = useAsyncActionFeedback();
  const referenceCitationFeedback = useAsyncActionFeedback();
  const inTextCitationFeedback = useAsyncActionFeedback();
  const summaryRefreshFeedback = useAsyncActionFeedback();
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
  const updateDocumentTags = useMutation({
    mutationFn: (tagNames: string[]) => api.updateDocument(document.id, { tag_names: tagNames }),
    onSuccess: (updatedDocument) => {
      setTagNameDraft("");
      setTagEditError(null);
      setDraft((current) => ({
        ...current,
        tag_names: normalizedNameList(updatedDocument.tags.map((tag) => tag.name)).join(", "),
      }));
      queryClient.setQueryData(["document", document.id], updatedDocument);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["tags"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setTagEditError(actionFailureMessage("Could not update tags", error)),
  });
  const updateDoi = useMutation({
    mutationFn: (value: string) => api.updateDocument(document.id, { doi: value.trim() || null }),
    onSuccess: (updatedDocument) => {
      setEditingDoi(false);
      setDoiDraft(updatedDocument.doi || "");
      setDoiEditError(null);
      setDraft(draftFromDocument(updatedDocument));
      queryClient.setQueryData(["document", document.id], updatedDocument);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setDoiEditError(actionFailureMessage("Could not save DOI", error)),
  });
  const updateSummary = useMutation({
    mutationFn: (value: string) => api.updateDocument(document.id, { rich_summary: value.trim() || null }),
    onSuccess: (updatedDocument) => {
      setEditingSummary(false);
      setSummaryDraft(updatedDocument.rich_summary || "");
      setSummaryEditError(null);
      setDraft(draftFromDocument(updatedDocument));
      queryClient.setQueryData(["document", document.id], updatedDocument);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setSummaryEditError(actionFailureMessage("Could not save summary", error)),
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
    mutationFn: (target: CitationRefreshTarget) =>
      startConcordanceRun({
        backgroundDetail: document.title,
        backgroundLabel: target === "doi" ? "Refreshing DOI" : "Refreshing APA citation",
        capability_keys: ["citation_refresh"],
        capabilityKey: "citation_refresh",
        documentId: document.id,
        force: true,
        label: `${target === "doi" ? "DOI" : "Citation"} refresh: ${document.title}`,
        scope_data: { document_ids: [document.id] },
        scope_type: "documents",
      }),
    onSuccess: (run, target) => {
      setCitationRefreshTarget(target);
      const feedback =
        target === "doi" ? doiRefreshFeedback : target === "reference" ? referenceCitationFeedback : inTextCitationFeedback;
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
      const feedback = target === "doi" ? doiRefreshFeedback : target === "in-text" ? inTextCitationFeedback : referenceCitationFeedback;
      feedback.showError(actionFailureMessage(target === "doi" ? "Could not start DOI refresh" : "Could not start citation refresh", error));
    },
  });
  const refreshSummary = useMutation({
    mutationFn: () =>
      startConcordanceRun({
        backgroundDetail: document.title,
        backgroundLabel: "Refreshing summary",
        capability_keys: ["summary_refresh"],
        capabilityKey: "summary_refresh",
        documentId: document.id,
        force: true,
        label: `Summary refresh: ${document.title}`,
        scope_data: { document_ids: [document.id] },
        scope_type: "documents",
      }),
    onSuccess: (run) => {
      if (run.total_jobs > 0) setSummaryRunId(run.id);
      else summaryRefreshFeedback.showSuccess();
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["concordance-jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
    },
    onError: (error) => {
      setSummaryRunId(null);
      summaryRefreshFeedback.showError(actionFailureMessage("Could not start summary refresh", error));
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
    setEditingDoi(false);
    setDoiDraft(document.doi || "");
    setDoiEditError(null);
    setEditingSummary(false);
    setSummaryDraft(document.rich_summary || "");
    setSummaryEditError(null);
    setTagNameDraft("");
    setTagEditError(null);
    setEditingPageId(null);
    setPageTextDraft("");
    setPageTextError(null);
    setPageTextSelection("");
    setDocumentConcordanceRunId(null);
    setCitationRunId(null);
    setCitationRefreshTarget(null);
    setSummaryRunId(null);
    setEditingCitation(null);
    setCitationDrafts({ reference: document.apa_citation || "", "in-text": document.apa_in_text_citation || "" });
    setCitationEditError(null);
    setSelectedHistoryVersionId(null);
    setHistoryRestoreError(null);
  }, [document.id]);

  useEffect(() => {
    if (!editingDoi) setDoiDraft(document.doi || "");
  }, [document.doi, editingDoi]);

  useEffect(() => {
    if (!editingSummary) setSummaryDraft(document.rich_summary || "");
  }, [document.rich_summary, editingSummary]);

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
  const copyDoi = () => {
    if (document.doi) void copyToClipboard("document-doi", document.doi);
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
  const summaryRefreshActive = citationJobs.some(
    (job) => job.document_id === document.id && job.capability_key === "summary_refresh" && isActiveConcordanceStatus(job.status),
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
  const trackedSummaryJobs = useMemo(
    () =>
      summaryRunId
        ? citationJobs.filter((job) => job.run_id === summaryRunId && job.document_id === document.id && job.capability_key === "summary_refresh")
        : [],
    [citationJobs, document.id, summaryRunId],
  );
  const documentConcordanceBusy =
    runConcordance.isPending ||
    Boolean(
      documentConcordanceRunId &&
        (!trackedDocumentConcordanceJobs.length || trackedDocumentConcordanceJobs.some((job) => isActiveConcordanceStatus(job.status))),
    );
  const citationBusy = refreshCitation.isPending || citationRefreshActive || Boolean(citationRunId);
  const summaryRefreshBusy =
    refreshSummary.isPending ||
    summaryRefreshActive ||
    Boolean(summaryRunId && (!trackedSummaryJobs.length || trackedSummaryJobs.some((job) => isActiveConcordanceStatus(job.status))));
  const pageTextBusyReason = updatePageText.isPending
    ? "a parsed-text save is already running."
    : scrubText.isPending
      ? "a scrub edit is already running."
      : "";
  const citationBusyReason = refreshCitation.isPending
    ? "a citation refresh request is already starting."
    : citationRefreshActive || citationRunId
      ? "a DOI or citation refresh is already queued or running for this document."
      : "";
  const summaryRefreshBusyReason = refreshSummary.isPending
    ? "a summary refresh request is already starting."
    : summaryRefreshActive || summaryRunId
      ? "a summary refresh is already queued or running for this document."
      : "";
  const documentConcordanceBusyReason = runConcordance.isPending
    ? "a document Concordance request is already starting."
    : documentConcordanceBusy
      ? "a document Concordance Run is already queued or running."
      : "";
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
  const accessorySummaryBusyReason = createAccessorySummary.isPending
    ? "an Accessory Summary request is already starting."
    : accessorySummaryBusy
      ? "an Accessory Summary is already queued or running for this document."
      : "";
  const sortedDocumentTags = useMemo(() => sortByName(document.tags), [document.tags]);
  const sortedAvailableTags = useMemo(() => sortByName(tags), [tags]);
  const currentTagNames = useMemo(() => normalizedNameList(sortedDocumentTags.map((tag) => tag.name)), [sortedDocumentTags]);
  const tagUpdateBusy = updateDocumentTags.isPending;
  const tagUpdateBusyReason = "a tag update is already saving for this document.";

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
    const feedback =
      citationRefreshTarget === "doi"
        ? doiRefreshFeedback
        : citationRefreshTarget === "in-text"
          ? inTextCitationFeedback
          : referenceCitationFeedback;
    if (failedJob) {
      feedback.showError(
        actionFailureMessage(
          citationRefreshTarget === "doi" ? "DOI refresh failed" : "Citation refresh failed",
          failedJob.last_error || "Concordance job failed without a detailed error",
        ),
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
    doiRefreshFeedback,
    inTextCitationFeedback,
    queryClient,
    referenceCitationFeedback,
    trackedCitationJobs,
  ]);

  useEffect(() => {
    if (!summaryRunId || trackedSummaryJobs.length === 0) return;
    if (trackedSummaryJobs.some((job) => isActiveConcordanceStatus(job.status))) return;
    const failedJob = trackedSummaryJobs.find((job) => job.status === "failed");
    if (failedJob) {
      summaryRefreshFeedback.showError(
        actionFailureMessage("Summary refresh failed", failedJob.last_error || "Concordance job failed without a detailed error"),
      );
    } else {
      summaryRefreshFeedback.showSuccess();
    }
    setSummaryRunId(null);
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
    void queryClient.invalidateQueries({ queryKey: ["document", document.id] });
    void queryClient.invalidateQueries({ queryKey: ["openai-usage"] });
  }, [document.id, queryClient, summaryRefreshFeedback, summaryRunId, trackedSummaryJobs]);

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
  const doiCheckBusy = citationBusy && citationRefreshTarget === "doi";
  const checkDoi = () => {
    setCitationRefreshTarget("doi");
    refreshCitation.mutate("doi");
  };
  const startDoiEdit = () => {
    setDoiDraft(document.doi || "");
    setDoiEditError(null);
    setEditingDoi(true);
    window.requestAnimationFrame(() => doiEditInputRef.current?.focus());
  };
  const cancelDoiEdit = () => {
    setDoiDraft(document.doi || "");
    setDoiEditError(null);
    setEditingDoi(false);
  };
  const saveDoiEdit = () => {
    updateDoi.mutate(doiDraft);
  };
  const copySummary = () => {
    if (document.rich_summary) void copyToClipboard("document-summary", decodeHtmlEntities(document.rich_summary));
  };
  const startSummaryEdit = () => {
    setSummaryDraft(document.rich_summary || "");
    setSummaryEditError(null);
    setEditingSummary(true);
    window.requestAnimationFrame(() => summaryTextareaRef.current?.focus());
  };
  const cancelSummaryEdit = () => {
    setSummaryDraft(document.rich_summary || "");
    setSummaryEditError(null);
    setEditingSummary(false);
  };
  const saveSummaryEdit = () => {
    updateSummary.mutate(summaryDraft);
  };
  const checkSummary = () => {
    refreshSummary.mutate();
  };
  const replaceSummarySelection = (replacement: string, nextSelectionStart: number, nextSelectionEnd: number) => {
    const textarea = summaryTextareaRef.current;
    const start = textarea?.selectionStart ?? summaryDraft.length;
    const end = textarea?.selectionEnd ?? summaryDraft.length;
    const nextValue = `${summaryDraft.slice(0, start)}${replacement}${summaryDraft.slice(end)}`;
    setSummaryDraft(nextValue);
    window.requestAnimationFrame(() => {
      summaryTextareaRef.current?.focus();
      summaryTextareaRef.current?.setSelectionRange(start + nextSelectionStart, start + nextSelectionEnd);
    });
  };
  const applySummaryInlineFormat = (prefix: string, suffix: string, placeholder: string) => {
    if (updateSummary.isPending) return;
    const textarea = summaryTextareaRef.current;
    const start = textarea?.selectionStart ?? summaryDraft.length;
    const end = textarea?.selectionEnd ?? summaryDraft.length;
    const selected = summaryDraft.slice(start, end) || placeholder;
    replaceSummarySelection(`${prefix}${selected}${suffix}`, prefix.length, prefix.length + selected.length);
  };
  const applySummaryLineFormat = (formatter: (line: string, index: number) => string) => {
    if (updateSummary.isPending) return;
    const textarea = summaryTextareaRef.current;
    const start = textarea?.selectionStart ?? summaryDraft.length;
    const end = textarea?.selectionEnd ?? summaryDraft.length;
    const lineStart = summaryDraft.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
    const nextLineBreak = summaryDraft.indexOf("\n", end);
    const lineEnd = nextLineBreak === -1 ? summaryDraft.length : nextLineBreak;
    const original = summaryDraft.slice(lineStart, lineEnd);
    const replacement = original
      .split("\n")
      .map((line, index) => formatter(line, index))
      .join("\n");
    const nextValue = `${summaryDraft.slice(0, lineStart)}${replacement}${summaryDraft.slice(lineEnd)}`;
    setSummaryDraft(nextValue);
    window.requestAnimationFrame(() => {
      summaryTextareaRef.current?.focus();
      summaryTextareaRef.current?.setSelectionRange(lineStart, lineStart + replacement.length);
    });
  };
  const clearSummaryFormatting = () => {
    if (updateSummary.isPending) return;
    const textarea = summaryTextareaRef.current;
    const start = textarea?.selectionStart ?? 0;
    const end = textarea?.selectionEnd ?? 0;
    if (start !== end) {
      const cleaned = stripMarkdownFormatting(summaryDraft.slice(start, end));
      replaceSummarySelection(cleaned, 0, cleaned.length);
      return;
    }
    setSummaryDraft(stripMarkdownFormatting(summaryDraft));
    window.requestAnimationFrame(() => summaryTextareaRef.current?.focus());
  };

  const toggleDocumentEditing = () => {
    if (editing) {
      setEditing(false);
      return;
    }
    setEditing(true);
    window.requestAnimationFrame(() => titleEditInputRef.current?.focus());
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

  useEscapeLayer(recommendationsOpen, () => setRecommendationsOpen(false), ESCAPE_PRIORITY_POPOVER);
  useEscapeLayer(accessoryComposerOpen && !accessorySummaryBusy, () => setAccessoryComposerOpen(false), ESCAPE_PRIORITY_EXPANDED);
  useEscapeLayer(editingDoi && !updateDoi.isPending, () => setEditingDoi(false), ESCAPE_PRIORITY_EXPANDED);
  useEscapeLayer(editingSummary && !updateSummary.isPending, () => setEditingSummary(false), ESCAPE_PRIORITY_EXPANDED);
  useEscapeLayer(editing && !updateDocument.isPending, () => setEditing(false), ESCAPE_PRIORITY_EXPANDED);
  useEscapeLayer(pageTextEditing && !pageTextBusy, cancelPageTextEdit, ESCAPE_PRIORITY_EXPANDED);
  useEscapeLayer(Boolean(editingCitation) && !updateCitation.isPending, cancelCitationEdit, ESCAPE_PRIORITY_EXPANDED);

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
      tag_names: normalizedNameList(splitCommaList(draft.tag_names)),
      domain_ids: draft.domain_ids,
      attribute_values: nextAttributes,
    });
  };
  const setDocumentTags = (tagNames: string[]) => {
    if (tagUpdateBusy) return;
    updateDocumentTags.mutate(normalizedNameList(tagNames));
  };
  const addDocumentTag = () => {
    const name = tagNameDraft.trim();
    if (!name || tagUpdateBusy) return;
    const normalizedKey = name.toLocaleLowerCase();
    if (currentTagNames.some((tagName) => tagName.toLocaleLowerCase() === normalizedKey)) {
      setTagNameDraft("");
      setTagEditError(null);
      return;
    }
    setDocumentTags([...currentTagNames, name]);
  };
  const removeDocumentTag = (name: string) => {
    const normalizedKey = name.trim().toLocaleLowerCase();
    setDocumentTags(currentTagNames.filter((tagName) => tagName.toLocaleLowerCase() !== normalizedKey));
  };
  const annotations = document.annotations || [];
  const accessoryModelOptions = preferences?.model_options[accessorySummaryTask?.model_kind || "gpt"] || [];
  const renderTagsSection = () => {
    const existingTagNames = new Set(currentTagNames.map((name) => name.toLocaleLowerCase()));
    const availableTags = sortedAvailableTags.filter((tag) => !existingTagNames.has(tag.name.toLocaleLowerCase()));
    return (
      <section className="detail-section detail-tags-section">
        <h3>TAGS</h3>
        <div className="detail-tag-list">
          {sortedDocumentTags.length ? (
            sortedDocumentTags.map((tag) => (
              <span className="detail-tag-chip" key={tag.id}>
                <span>{tag.name}</span>
                <button
                  aria-label={`Remove ${tag.name}`}
                  data-disabled-reason={tagUpdateBusyReason}
                  data-tooltip={`Remove the ${tag.name} tag from this document.`}
                  disabled={tagUpdateBusy}
                  onClick={() => removeDocumentTag(tag.name)}
                  type="button"
                >
                  <X size={12} />
                </button>
              </span>
            ))
          ) : (
            <span className="detail-tags-empty">No tags yet.</span>
          )}
          <form
            className="detail-tag-add"
            onSubmit={(event) => {
              event.preventDefault();
              addDocumentTag();
            }}
          >
            <input
              aria-label="Add tag"
              data-disabled-reason={tagUpdateBusyReason}
              data-tooltip="Type an existing or new tag name to add it to this document."
              disabled={tagUpdateBusy}
              list={`detail-known-tags-${document.id}`}
              onChange={(event) => {
                setTagNameDraft(event.target.value);
                if (tagEditError) setTagEditError(null);
              }}
              placeholder="Add tag"
              value={tagNameDraft}
            />
            <datalist id={`detail-known-tags-${document.id}`}>
              {availableTags.map((tag) => (
                <option key={tag.id} value={tag.name} />
              ))}
            </datalist>
            <button
              aria-label="Add tag"
              className="icon-button compact"
              data-disabled-reason={tagUpdateBusy ? tagUpdateBusyReason : "a tag name is required."}
              data-tooltip="Add the typed tag to this document."
              disabled={!tagNameDraft.trim() || tagUpdateBusy}
              type="submit"
            >
              <Plus size={14} />
            </button>
          </form>
        </div>
        {tagEditError ? <p className="form-error">{tagEditError}</p> : null}
      </section>
    );
  };
  const renderDoiSection = () => (
    <section className="detail-section doi-section">
      <h3>DOI</h3>
      <div className="doi-value">{document.doi ? <code>{document.doi}</code> : <span>No DOI recorded.</span>}</div>
      {editingDoi ? (
        <form
          className="doi-editor"
          data-escape-layer="expanded"
          onSubmit={(event) => {
            event.preventDefault();
            saveDoiEdit();
          }}
        >
          <input
            aria-label="DOI"
            data-disabled-reason="the DOI change is already saving."
            data-tooltip="Edit the document DOI; leave it blank to clear the stored DOI."
            disabled={updateDoi.isPending}
            onChange={(event) => {
              setDoiDraft(event.target.value);
              if (doiEditError) setDoiEditError(null);
            }}
            placeholder="10.0000/example"
            ref={doiEditInputRef}
            value={doiDraft}
          />
          <div className="doi-editor-actions">
            <button
              className="primary-button compact"
              data-disabled-reason="the DOI change is already saving."
              data-tooltip="Save this DOI to the document and refresh document search surfaces."
              disabled={updateDoi.isPending}
              type="submit"
            >
              <Save size={14} />
              Save
            </button>
            <button
              className="secondary-button compact"
              data-disabled-reason="the DOI change is already saving."
              data-tooltip="Discard the DOI draft and close DOI editing."
              disabled={updateDoi.isPending}
              onClick={cancelDoiEdit}
              type="button"
            >
              <X size={14} />
              Cancel
            </button>
          </div>
          {doiEditError ? <p className="form-error">{doiEditError}</p> : null}
        </form>
      ) : null}
      <div className="doi-actions">
        <button
          className="secondary-button"
          data-disabled-reason="this document does not have a DOI to copy."
          data-tooltip="Copy the stored DOI for this document to the clipboard."
          disabled={!document.doi}
          onClick={copyDoi}
          type="button"
        >
          {copiedKey === "document-doi" ? <CheckCircle2 size={15} /> : <Clipboard size={15} />}
          {copiedKey === "document-doi" ? "Copied" : "Copy"}
        </button>
        <button
          className="secondary-button"
          data-disabled-reason={updateDoi.isPending ? "the DOI change is already saving." : "the DOI editor is already open."}
          data-tooltip="Open DOI editing so you can add, correct, or clear the document DOI."
          onClick={startDoiEdit}
          disabled={updateDoi.isPending || editingDoi}
          type="button"
        >
          <Edit3 size={15} />
          Edit
        </button>
        <AsyncActionSlot busy={doiCheckBusy} feedback={doiRefreshFeedback.feedback} label="DOI refresh in progress">
          <button
            className={asyncFeedbackClass("secondary-button", doiRefreshFeedback.feedback, doiCheckBusy)}
            data-disabled-reason={citationBusyReason}
            data-tooltip="Queue a DOI and APA citation refresh for this document using the selected APA model fallback."
            onClick={checkDoi}
            disabled={citationBusy}
            type="button"
          >
            <RefreshCw className={doiCheckBusy ? "spin" : ""} size={15} />
            {doiCheckBusy ? "Refreshing" : "Refresh"}
          </button>
        </AsyncActionSlot>
        <span className="citation-model-label">{analysisModelActionLabel(preferences, APA_CITATION_MODEL_KEY, "gpt-5.5")}</span>
      </div>
    </section>
  );
  const renderSummarySection = () => (
    <section className="detail-section summary-section">
      <h3>Summary</h3>
      {editingSummary ? (
        <form
          className="summary-editor"
          data-escape-layer="expanded"
          onSubmit={(event) => {
            event.preventDefault();
            saveSummaryEdit();
          }}
        >
          <div className="summary-editor-toolbar" aria-label="Summary formatting tools">
            <button
              className="icon-button compact"
              data-disabled-reason="the summary edit is already saving."
              data-tooltip="Wrap the selected summary text in Markdown bold markers."
              disabled={updateSummary.isPending}
              onClick={() => applySummaryInlineFormat("**", "**", "bold text")}
              type="button"
            >
              <Bold size={14} />
            </button>
            <button
              className="icon-button compact"
              data-disabled-reason="the summary edit is already saving."
              data-tooltip="Wrap the selected summary text in Markdown italic markers."
              disabled={updateSummary.isPending}
              onClick={() => applySummaryInlineFormat("*", "*", "italic text")}
              type="button"
            >
              <Italic size={14} />
            </button>
            <button
              className="icon-button compact"
              data-disabled-reason="the summary edit is already saving."
              data-tooltip="Wrap the selected summary text in underline HTML tags."
              disabled={updateSummary.isPending}
              onClick={() => applySummaryInlineFormat("<u>", "</u>", "underlined text")}
              type="button"
            >
              <Underline size={14} />
            </button>
            <button
              className="icon-button compact"
              data-disabled-reason="the summary edit is already saving."
              data-tooltip="Turn the selected summary lines into a Markdown bullet list."
              disabled={updateSummary.isPending}
              onClick={() =>
                applySummaryLineFormat((line) => {
                  const text = line.replace(/^\s*(?:[-*]|\d+[.)])\s+/, "").trim();
                  return text ? `- ${text}` : "- ";
                })
              }
              type="button"
            >
              <List size={14} />
            </button>
            <button
              className="icon-button compact"
              data-disabled-reason="the summary edit is already saving."
              data-tooltip="Turn the selected summary lines into a Markdown numbered list."
              disabled={updateSummary.isPending}
              onClick={() =>
                applySummaryLineFormat((line, index) => {
                  const text = line.replace(/^\s*(?:[-*]|\d+[.)])\s+/, "").trim();
                  return text ? `${index + 1}. ${text}` : `${index + 1}. `;
                })
              }
              type="button"
            >
              <ListOrdered size={14} />
            </button>
            <button
              className="icon-button compact"
              data-disabled-reason="the summary edit is already saving."
              data-tooltip="Prefix selected summary lines with Markdown blockquote indentation."
              disabled={updateSummary.isPending}
              onClick={() => applySummaryLineFormat((line) => (line.startsWith(">") ? line : `> ${line}`))}
              type="button"
            >
              <IndentIncrease size={14} />
            </button>
            <button
              className="icon-button compact"
              data-disabled-reason="the summary edit is already saving."
              data-tooltip="Remove one Markdown blockquote indentation marker from selected summary lines."
              disabled={updateSummary.isPending}
              onClick={() => applySummaryLineFormat((line) => line.replace(/^>\s?/, ""))}
              type="button"
            >
              <IndentDecrease size={14} />
            </button>
            <button
              className="icon-button compact"
              data-disabled-reason="the summary edit is already saving."
              data-tooltip="Remove common Markdown and underline formatting markers from the summary draft."
              disabled={updateSummary.isPending}
              onClick={clearSummaryFormatting}
              type="button"
            >
              <RemoveFormatting size={14} />
            </button>
          </div>
          <textarea
            aria-label="Summary Markdown"
            data-disabled-reason="the summary edit is already saving."
            data-tooltip="Edit the Markdown summary that appears in the document detail pane and contributes to search."
            disabled={updateSummary.isPending}
            onChange={(event) => {
              setSummaryDraft(event.target.value);
              if (summaryEditError) setSummaryEditError(null);
            }}
            ref={summaryTextareaRef}
            value={summaryDraft}
          />
          <div className="summary-editor-actions">
            <button
              className="primary-button compact"
              data-disabled-reason="the summary edit is already saving."
              data-tooltip="Save this edited summary to the document and refresh search."
              disabled={updateSummary.isPending}
              type="submit"
            >
              <Save size={14} />
              Save
            </button>
            <button
              className="secondary-button compact"
              data-disabled-reason="the summary edit is already saving."
              data-tooltip="Discard the summary draft and close summary editing."
              disabled={updateSummary.isPending}
              onClick={cancelSummaryEdit}
              type="button"
            >
              <X size={14} />
              Cancel
            </button>
          </div>
          {summaryEditError ? <p className="form-error">{summaryEditError}</p> : null}
        </form>
      ) : (
        <MarkdownBlock content={document.rich_summary} empty="Summary pending." />
      )}
      <div className="citation-actions">
        <button
          className="secondary-button"
          data-disabled-reason="this document does not have a generated or edited summary to copy."
          data-tooltip="Copy this document summary to the clipboard."
          onClick={copySummary}
          disabled={!document.rich_summary}
          type="button"
        >
          {copiedKey === "document-summary" ? <CheckCircle2 size={15} /> : <Clipboard size={15} />}
          {copiedKey === "document-summary" ? "Copied" : "Copy"}
        </button>
        <button
          className="secondary-button"
          data-disabled-reason={updateSummary.isPending ? "the summary edit is already saving." : "the summary editor is already open."}
          data-tooltip="Open the Markdown summary editor for this document."
          onClick={startSummaryEdit}
          disabled={updateSummary.isPending || editingSummary}
          type="button"
        >
          <Edit3 size={15} />
          Edit
        </button>
        <AsyncActionSlot busy={summaryRefreshBusy} feedback={summaryRefreshFeedback.feedback} label="Summary refresh in progress">
          <button
            className={asyncFeedbackClass("secondary-button", summaryRefreshFeedback.feedback, summaryRefreshBusy)}
            data-disabled-reason={summaryRefreshBusyReason}
            data-tooltip="Queue a summary-only Concordance refresh using the selected Summary model."
            onClick={checkSummary}
            disabled={summaryRefreshBusy}
            type="button"
          >
            <RefreshCw className={summaryRefreshBusy ? "spin" : ""} size={15} />
            {summaryRefreshBusy ? "Refreshing" : "Refresh"}
          </button>
        </AsyncActionSlot>
        <span className="citation-model-label">{analysisModelActionLabel(preferences, SUMMARY_MODEL_KEY, "gpt-5.4")}</span>
      </div>
    </section>
  );
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
            data-escape-layer="expanded"
            onSubmit={(event) => {
              event.preventDefault();
              saveCitationEdit(kind);
            }}
          >
            <textarea
              aria-label={`${title} text`}
              data-disabled-reason="a citation edit is already saving."
              data-tooltip={`Edit the ${title} Markdown text stored for this document.`}
              value={citationDrafts[kind]}
              onChange={(event) => setCitationDrafts((current) => ({ ...current, [kind]: event.target.value }))}
            />
            <div className="citation-editor-actions">
              <button
                className="primary-button compact"
                data-disabled-reason="a citation edit is already saving."
                data-tooltip={`Save the edited ${title} text to this document.`}
                disabled={updateCitation.isPending}
                type="submit"
              >
                <Save size={14} />
                Save
              </button>
              <button
                className="secondary-button compact"
                data-disabled-reason="a citation edit is already saving."
                data-tooltip={`Discard the ${title} draft and close citation editing.`}
                disabled={updateCitation.isPending}
                onClick={cancelCitationEdit}
                type="button"
              >
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
          <button
            className="secondary-button"
            data-disabled-reason={`this document does not have ${title} text to copy.`}
            data-tooltip={`Copy the ${title} text to the clipboard.`}
            onClick={() => copyCitation(kind)}
            disabled={!text}
            type="button"
          >
            {copiedKey === `citation-${kind}` ? <CheckCircle2 size={15} /> : <Clipboard size={15} />}
            {copiedKey === `citation-${kind}` ? "Copied" : "Copy"}
          </button>
          <button
            className="secondary-button"
            data-disabled-reason={updateCitation.isPending ? "a citation edit is already saving." : "this citation editor is already open."}
            data-tooltip={`Open the editor for the ${title} text.`}
            onClick={() => startCitationEdit(kind)}
            disabled={updateCitation.isPending || isEditing}
            type="button"
          >
            <Edit3 size={15} />
            Edit
          </button>
          <AsyncActionSlot busy={busy} feedback={feedback} label="Citation refresh in progress">
            <button
              className={asyncFeedbackClass("secondary-button", feedback, busy)}
              data-disabled-reason={citationBusyReason}
              data-tooltip={`Queue an APA citation refresh for the ${title} text using DOI/Crossref evidence first and the selected APA model as fallback.`}
              onClick={() => checkCitation(kind)}
              disabled={citationBusy}
              type="button"
            >
              <RefreshCw className={busy ? "spin" : ""} size={15} />
              {busy ? "Refreshing" : "Refresh"}
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
            data-disabled-reason={
              pageTextBusy
                ? pageTextBusyReason
                : !pages.length
                  ? "this document does not have parsed pages yet."
                  : "the reader is already on the first parsed page."
            }
            data-tooltip="Move the parsed-text reader to the previous page."
            disabled={!pages.length || currentPageIndex === 0 || pageTextBusy}
            onClick={() => setReaderPageIndex((index) => Math.max(0, index - 1))}
          >
            <ChevronLeft size={18} />
          </button>
          <span className="page-counter">{pages.length ? `${currentPage?.page_number ?? currentPageIndex + 1} / ${pages.length}` : "0 / 0"}</span>
          <button
            className="icon-button reader-arrow"
            type="button"
            data-disabled-reason={
              pageTextBusy
                ? pageTextBusyReason
                : !pages.length
                  ? "this document does not have parsed pages yet."
                  : "the reader is already on the last parsed page."
            }
            data-tooltip="Move the parsed-text reader to the next page."
            disabled={!pages.length || currentPageIndex >= pages.length - 1 || pageTextBusy}
            onClick={() => setReaderPageIndex((index) => Math.min(pages.length - 1, index + 1))}
          >
            <ChevronRight size={18} />
          </button>
          <button
            className="secondary-button compact"
            data-disabled-reason={pageTextBusy ? pageTextBusyReason : "this document does not have parsed text to copy."}
            data-tooltip="Copy all parsed document text to the clipboard."
            onClick={copyFullText}
            disabled={!fullText || pageTextBusy}
            type="button"
          >
            {copiedKey === "full-text" ? <CheckCircle2 size={14} /> : <Clipboard size={14} />}
            {copiedKey === "full-text" ? "Copied" : "Copy"}
          </button>
          {!pageTextEditing ? (
            <button
              className="secondary-button compact"
              data-disabled-reason={pageTextBusy ? pageTextBusyReason : "there is no parsed page selected to edit."}
              data-tooltip="Open the parsed page text editor for the current page."
              disabled={!currentPage || pageTextBusy}
              onClick={startPageTextEdit}
              type="button"
            >
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
            <div className="reader-page-editor" data-escape-layer="expanded">
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
                  data-disabled-reason={
                    pageTextBusy
                      ? pageTextBusyReason
                      : !scrubNeedle
                        ? "select exact text in the parsed page editor first."
                        : "the selected text does not appear in the parsed document text."
                  }
                  data-tooltip="Remove the selected exact text everywhere it appears in this document's parsed pages and record the edit in history."
                  disabled={!scrubNeedle || scrubMatchCount <= 0 || pageTextBusy}
                  onClick={scrubSelectedText}
                  type="button"
                >
                  <Eraser size={14} />
                  {scrubButtonLabel}
                </button>
                <span className="reader-tool-spacer" />
                <button
                  className="primary-button compact"
                  data-disabled-reason={pageTextBusyReason}
                  data-tooltip="Save the edited parsed text for this page, rebuild document search, and record the change in history."
                  disabled={pageTextBusy}
                  onClick={savePageTextEdit}
                  type="button"
                >
                  <Save size={14} />
                  Save
                </button>
                <button
                  className="secondary-button compact"
                  data-disabled-reason={pageTextBusyReason}
                  data-tooltip="Discard parsed page text edits and close the editor."
                  disabled={pageTextBusy}
                  onClick={cancelPageTextEdit}
                  type="button"
                >
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
          <PriorityPill value={document.priority} />
        </div>
      </div>
      <div className="detail-actions">
        <button
          className="secondary-button"
          data-tooltip={editing ? "Close the document metadata correction form without saving." : "Open the document metadata correction form."}
          onClick={toggleDocumentEditing}
        >
          {editing ? <X size={15} /> : <Edit3 size={15} />}
          {editing ? "Cancel" : "Edit"}
        </button>
        <button
          className="secondary-button"
          data-tooltip="Copy a bookmarkable link that opens Library with this document focused."
          onClick={() => copyToClipboard("document-link", documentLinkUrl(document.id))}
          type="button"
        >
          {copiedKey === "document-link" ? <CheckCircle2 size={15} /> : <Clipboard size={15} />}
          {copiedKey === "document-link" ? "Copied" : "Link"}
        </button>
        <AsyncActionSlot busy={documentConcordanceBusy} feedback={runConcordanceFeedback.feedback} label="Document Concordance in progress">
          <button
            className={asyncFeedbackClass("secondary-button", runConcordanceFeedback.feedback, documentConcordanceBusy)}
            data-disabled-reason={documentConcordanceBusyReason}
            data-tooltip="Queue a document-scoped Concordance Run to bring this document up to the current selected capabilities."
            onClick={() => runConcordance.mutate()}
            disabled={documentConcordanceBusy}
          >
            <RefreshCw className={documentConcordanceBusy ? "spin" : ""} size={15} />
            {documentConcordanceBusy ? "Concording" : "Concord"}
          </button>
        </AsyncActionSlot>
        <button
          className="secondary-button"
          data-tooltip="Open this document's cost composition, provider spend, local processing time, issues, and pipeline chart."
          onClick={() => setCompositionOpen(true)}
          type="button"
        >
          <PieChart size={15} />
          Composition
        </button>
        {onOpenReader && !readerExpanded ? (
          <button className="secondary-button" data-tooltip="Expand this document into full Reader mode." onClick={onOpenReader} type="button">
            <BookOpen size={15} />
            Reader
          </button>
        ) : null}
        <button
          className="secondary-button"
          aria-expanded={recommendationsOpen}
          data-tooltip={document.doi ? "Open related-paper recommendations for this DOI-bearing document." : "Open the recommendations panel to see why related papers are unavailable."}
          onClick={() => setRecommendationsOpen((value) => !value)}
          type="button"
        >
          <BookSearchIcon size={15} />
          Related
        </button>
        <a
          className="secondary-button"
          data-tooltip="Open the authenticated original PDF in a new browser tab."
          href={`/api/documents/${document.id}/original`}
          target="_blank"
          rel="noreferrer"
        >
          <FileSearch size={15} />
          Open Original
        </a>
        <a
          className="secondary-button"
          data-tooltip="Download the authenticated original PDF using the Settings Download Naming template."
          href={`/api/documents/${document.id}/original?download=1`}
          download
        >
          <Download size={15} />
          Download Original
        </a>
        {onCloseReader && readerExpanded ? (
          <button
            className="secondary-button reader-close-action"
            data-tooltip="Close expanded Reader mode and return to the normal Library panes."
            onClick={onCloseReader}
            type="button"
          >
            <X size={15} />
            Close
          </button>
        ) : null}
      </div>
      {compositionOpen ? (
        <CompositionDialog
          composition={composition.data}
          document={document}
          loading={composition.isFetching && !composition.data}
          onClose={() => setCompositionOpen(false)}
        />
      ) : null}
      <div className="reader-surface">
        <div className="reader-tabs" role="tablist" aria-label="Document reader">
          <button
            className={readerMode === "pdf" ? "selected" : ""}
            data-tooltip="Show the authenticated original PDF preview."
            type="button"
            onClick={() => {
              setRecommendationsOpen(false);
              setReaderMode("pdf");
            }}
          >
            <FileSearch size={15} />
            PDF
          </button>
          <button
            className={readerMode === "text" ? "selected" : ""}
            data-tooltip="Show the normalized parsed-text reader for this document."
            type="button"
            onClick={() => {
              setRecommendationsOpen(false);
              setReaderMode("text");
            }}
          >
            <FileText size={15} />
            Text
          </button>
          <button
            className={readerMode === "compare" ? "selected" : ""}
            data-tooltip="Show the original PDF beside the parsed text editor for page-by-page comparison."
            type="button"
            onClick={() => {
              setRecommendationsOpen(false);
              setReaderMode("compare");
            }}
          >
            <BookOpen size={15} />
            Compare
          </button>
        </div>
        {recommendationsOpen ? (
          <div className="recommendations-popover" data-escape-layer="popover">
            <RecommendationsPanel document={document} onClose={() => setRecommendationsOpen(false)} />
          </div>
        ) : null}
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
      </div>
      {editing ? (
        <form
          className="document-editor"
          data-escape-layer="expanded"
          onSubmit={(event) => {
            event.preventDefault();
            saveCorrection();
          }}
        >
          <label>
            Title
            <input ref={titleEditInputRef} value={draft.title} onChange={(event) => setDraftValue("title", event.target.value)} />
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
              {sortedAvailableTags.map((tag) => (
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
                data-tooltip="Add another custom attribute row to the correction form."
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
                  <button
                    className="icon-button"
                    type="button"
                    data-tooltip="Remove this custom attribute row from the correction draft."
                    onClick={() => removeAttribute(index)}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              ))}
            </div>
          </div>
          <button
            className="primary-button"
            data-disabled-reason="the document correction is already saving."
            data-tooltip="Save the document metadata correction, rebuild affected search text, and record the change in history."
            type="submit"
            disabled={updateDocument.isPending}
          >
            <Save size={15} />
            Save correction
          </button>
          {saveError ? <p className="form-error">{saveError}</p> : null}
        </form>
      ) : null}
      {renderTagsSection()}
      {renderDoiSection()}
      {renderCitationSection("reference", "APA Reference List", "Needs review.")}
      {renderCitationSection("in-text", "APA In-Text Citation", "Needs review.")}
      {renderSummarySection()}
      <section className="detail-section accessory-summary-section">
        <div className="detail-section-title-row">
          <h3>Accessory Summaries</h3>
          <button
            className="secondary-button compact"
            data-disabled-reason={accessorySummaryBusyReason}
            data-tooltip={accessoryComposerOpen ? "Close the Accessory Summary prompt composer." : "Open the Accessory Summary prompt composer for this document."}
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
            data-escape-layer="expanded"
            onSubmit={(event) => {
              event.preventDefault();
              submitAccessorySummary();
            }}
          >
            <textarea
              data-disabled-reason={accessorySummaryBusyReason}
              data-tooltip="Type the question or focused topic for a new Accessory Summary on this document."
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
                  data-disabled-reason={accessorySummaryBusy ? accessorySummaryBusyReason : "an Accessory Summary prompt is required."}
                  data-tooltip="Queue a durable Accessory Summary job for this document using the selected model."
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
                      data-disabled-reason="an Accessory Summary title update is already saving."
                      data-tooltip="Edit the optional display title for this Accessory Summary; it saves when the field loses focus."
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
                  data-disabled-reason="an annotation delete request is already running."
                  data-tooltip="Delete this annotation from the document; deleted annotations are removed from active search."
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
              <a
                key={figure.id}
                data-tooltip="Open this extracted figure asset in a new browser tab."
                href={`/api/figures/${figure.id}/asset`}
                target="_blank"
                rel="noreferrer"
              >
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
                  data-disabled-reason={
                    restoreHistoryVersion.isPending
                      ? "a history restore is already running."
                      : "this is the newest available history snapshot."
                  }
                  data-tooltip="Step to the next newer document history snapshot."
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
                  data-disabled-reason={
                    restoreHistoryVersion.isPending
                      ? "a history restore is already running."
                      : "this is the oldest available history snapshot."
                  }
                  data-tooltip="Step to the next older document history snapshot."
                  disabled={selectedHistoryIndex >= historyRows.length - 1 || restoreHistoryVersion.isPending}
                  onClick={() => selectHistoryOffset(1)}
                  type="button"
                >
                  Older
                  <ChevronRight size={14} />
                </button>
                <button
                  className="primary-button compact"
                  data-disabled-reason={
                    restoreHistoryVersion.isPending
                      ? "a history restore is already running."
                      : "the selected history snapshot has no restorable document or page fields."
                  }
                  data-tooltip="Restore the selected history snapshot as the current document state and append a new history entry."
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
                    data-tooltip={`Select history snapshot v${version.version_number} for preview and possible restore.`}
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
          <button
            className="text-button"
            data-tooltip={`Clear all selected default ${title.toLocaleLowerCase()} values for the next import batch.`}
            type="button"
            onClick={() => onChange([])}
          >
            Clear
          </button>
        ) : null}
      </div>
      <div className="selected-chips" aria-label={`${title} selected defaults`}>
        {selected.length ? (
          selected.map((item) => (
            <button
              key={item.id}
              data-tooltip={`Remove ${item.name} from the default ${title.toLocaleLowerCase()} applied to this import batch.`}
              type="button"
              onClick={() => removeItem(item.id)}
            >
              <span>{item.name}</span>
              <X size={13} />
            </button>
          ))
        ) : (
          <span>No default</span>
        )}
      </div>
      <input
        data-tooltip={`Search available ${title.toLocaleLowerCase()} to apply as defaults before importing PDFs.`}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={`Find ${title.toLowerCase()}`}
      />
      <div className="picker-options">
        {options.map((item) => (
          <button
            key={item.id}
            data-tooltip={`Add ${item.name} to the default ${title.toLocaleLowerCase()} for this import batch.`}
            type="button"
            onClick={() => addItem(item.id)}
          >
            <span>{item.name}</span>
            {item.meta ? <small>{item.meta}</small> : null}
          </button>
        ))}
        {!options.length ? <span className="picker-empty">No matches</span> : null}
      </div>
      {onCreate ? (
        <div className="inline-create">
          <input
            data-tooltip={`Type the name for ${createLabel.toLocaleLowerCase()} to create and select it for this import batch.`}
            value={createName}
            onChange={(event) => setCreateName(event.target.value)}
            placeholder={createLabel}
          />
          <button
            className="secondary-button"
            data-disabled-reason={creating ? `a ${title.toLocaleLowerCase()} create request is already running.` : "a name is required."}
            data-tooltip={`Create ${createName.trim() || createLabel.toLocaleLowerCase()} and add it to this import batch's default ${title.toLocaleLowerCase()}.`}
            disabled={!canCreate || creating}
            onClick={handleCreate}
            type="button"
          >
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

function stashStatusLabel(stash: DoiStash) {
  if (stash.status === "imported") return "Imported";
  if (stash.status === "import_queued") return stash.import_job_status === "running" ? "Import running" : "Import queued";
  if (stash.status === "import_failed") return "Import failed";
  return "Stashed";
}

function stashStatusTone(stash: DoiStash): "neutral" | "good" | "warn" | "blue" {
  if (stash.status === "imported") return "good";
  if (stash.status === "import_queued") return "blue";
  if (stash.status === "import_failed") return "warn";
  return "neutral";
}

function stashSortLabel(key: StashSortKey) {
  if (key === "created") return "Created";
  if (key === "doi") return "DOI";
  if (key === "title") return "Title";
  return "Status";
}

function tagSortLabel(key: TagSortKey) {
  if (key === "name") return "Tag";
  if (key === "status") return "Status";
  return "Documents";
}

function formatTagOptimizationConfidence(value: number) {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function formatTagStatus(value?: string | null) {
  const normalized = (value || "canonical").replace(/_/g, " ");
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function formatRelationshipType(value: string) {
  return value.replace(/_/g, " ");
}

function StashesView({ stashes }: { stashes: DoiStash[] }) {
  const [sortKey, setSortKey] = useState<StashSortKey>("created");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [draggingStashId, setDraggingStashId] = useState<string | null>(null);
  const [uploadingStashId, setUploadingStashId] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const queryClient = useQueryClient();
  const uploadFeedback = useAsyncActionFeedbackMap();
  const removeFeedback = useAsyncActionFeedbackMap();
  const sortedStashes = useMemo(() => {
    const direction = sortDirection === "asc" ? 1 : -1;
    return [...stashes].sort((left, right) => {
      const leftValue =
        sortKey === "created"
          ? left.created_at
          : sortKey === "doi"
            ? left.doi
            : sortKey === "title"
              ? left.title || left.doi
              : stashStatusLabel(left);
      const rightValue =
        sortKey === "created"
          ? right.created_at
          : sortKey === "doi"
            ? right.doi
            : sortKey === "title"
              ? right.title || right.doi
              : stashStatusLabel(right);
      return String(leftValue).localeCompare(String(rightValue)) * direction;
    });
  }, [sortDirection, sortKey, stashes]);

  const upload = useMutation({
    mutationFn: ({ stash, file }: { stash: DoiStash; file: File }) => api.uploadDoiStashPdf(stash.id, file),
    onMutate: ({ stash }) => {
      setUploadingStashId(stash.id);
      setNotice(`Uploading PDF for ${stash.doi}`);
    },
    onSuccess: (_updated, { stash }) => {
      uploadFeedback.showSuccess(stash.id);
      setNotice(`Queued PDF for ${stash.doi}`);
      void queryClient.invalidateQueries({ queryKey: ["doi-stashes"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error, { stash }) => {
      const message = actionFailureMessage("Could not upload PDF", error);
      uploadFeedback.showError(stash.id, message);
      setNotice(message);
    },
    onSettled: () => {
      setUploadingStashId(null);
      setDraggingStashId(null);
    },
  });

  const remove = useMutation({
    mutationFn: (stash: DoiStash) => api.deleteDoiStash(stash.id),
    onSuccess: (_result, stash) => {
      removeFeedback.showSuccess(stash.id);
      setNotice(`Removed ${stash.doi}`);
      void queryClient.invalidateQueries({ queryKey: ["doi-stashes"] });
    },
    onError: (error, stash) => {
      const message = actionFailureMessage("Could not remove stash", error);
      removeFeedback.showError(stash.id, message);
      setNotice(message);
    },
  });

  const chooseSort = (key: StashSortKey) => {
    if (key === sortKey) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDirection(key === "created" ? "desc" : "asc");
  };

  const handleUploadFiles = (stash: DoiStash, incomingFiles: FileList | File[]) => {
    const files = Array.from(incomingFiles);
    const pdf = files.find((file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"));
    if (!pdf) {
      const message = "Choose a PDF file.";
      uploadFeedback.showError(stash.id, message);
      setNotice(message);
      return;
    }
    upload.mutate({ stash, file: pdf });
  };

  return (
    <section className="workbench stashes-view">
      <div className="stashes-head">
        <div>
          <h2>DOI Stashes</h2>
          <p>{stashes.length ? `${stashes.length} saved DOI${stashes.length === 1 ? "" : "s"}` : "No stashed DOIs yet"}</p>
        </div>
        <div className="stash-sort-controls" aria-label="Sort stashes">
          <ArrowUpDown size={15} />
          {(["created", "doi", "title", "status"] as StashSortKey[]).map((key) => (
            <button
              key={key}
              className={`secondary-button compact ${sortKey === key ? "active" : ""}`}
              data-tooltip={`Sort stashed DOIs by ${stashSortLabel(key).toLocaleLowerCase()}; press again to reverse direction.`}
              onClick={() => chooseSort(key)}
              type="button"
            >
              {stashSortLabel(key)}
              {sortKey === key ? (sortDirection === "asc" ? " asc" : " desc") : ""}
            </button>
          ))}
        </div>
      </div>
      {notice ? <p className="stash-notice">{notice}</p> : null}
      {sortedStashes.length ? (
        <div className="stash-list">
          {sortedStashes.map((stash) => {
            const inputId = `stash-upload-${stash.id}`;
            const busy = uploadingStashId === stash.id;
            return (
              <article key={stash.id} className="stash-row">
                <div className="stash-main">
                  <div className="stash-title-line">
                    <strong>{stash.title || stash.doi}</strong>
                    <StatusPill value={stashStatusLabel(stash)} tone={stashStatusTone(stash)} />
                  </div>
                  <code>{stash.doi}</code>
                  <span>
                    {[stash.source_provider, stash.imported_document_title, backupDateLabel(stash.created_at)].filter(Boolean).join(" / ")}
                  </span>
                </div>
                <div className="stash-actions">
                  <input
                    id={inputId}
                    className="hidden-file-input"
                    accept="application/pdf,.pdf"
                    data-disabled-reason="a PDF upload is already running for this stash."
                    data-tooltip="Choose a PDF file to import for this stashed DOI."
                    type="file"
                    onChange={(event) => {
                      if (event.currentTarget.files?.length) handleUploadFiles(stash, event.currentTarget.files);
                      event.currentTarget.value = "";
                    }}
                  />
                  <AsyncActionSlot busy={busy} feedback={uploadFeedback.feedbackFor(stash.id)} label="Stash PDF upload in progress">
                    <label
                      aria-disabled={busy}
                      className={`stash-upload-button ${busy ? "disabled" : ""}`}
                      data-disabled-reason="a PDF upload is already running for this stash."
                      data-tooltip="Choose a PDF file to import for this stashed DOI through the normal import pipeline."
                      htmlFor={inputId}
                      role="button"
                      tabIndex={busy ? -1 : 0}
                    >
                      <Upload size={14} />
                      Upload PDF
                    </label>
                  </AsyncActionSlot>
                  <label
                    aria-disabled={busy}
                    className={`stash-upload-drop ${draggingStashId === stash.id ? "dragging" : ""} ${busy ? "disabled" : ""}`}
                    data-disabled-reason="a PDF upload is already running for this stash."
                    data-tooltip="Drop a PDF here to import it for this stashed DOI through the normal import pipeline."
                    htmlFor={inputId}
                    onDragEnter={(event) => {
                      event.preventDefault();
                      setDraggingStashId(stash.id);
                    }}
                    onDragOver={(event) => {
                      event.preventDefault();
                      event.dataTransfer.dropEffect = "copy";
                    }}
                    onDragLeave={() => setDraggingStashId(null)}
                    onDrop={(event) => {
                      event.preventDefault();
                      setDraggingStashId(null);
                      handleUploadFiles(stash, event.dataTransfer.files);
                    }}
                    role="button"
                    tabIndex={busy ? -1 : 0}
                  >
                    <UploadCloud size={14} />
                    Drag PDF Here To Upload
                  </label>
                  {stash.source_url ? (
                    <a
                      className="secondary-button compact"
                      data-tooltip="Open the saved source evidence for this DOI stash in a new tab."
                      href={stash.source_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink size={14} />
                      Source
                    </a>
                  ) : null}
                  <AsyncActionSlot feedback={removeFeedback.feedbackFor(stash.id)}>
                    <button
                      className={asyncFeedbackClass("secondary-button compact", removeFeedback.feedbackFor(stash.id))}
                      data-disabled-reason="a DOI stash remove request is already running."
                      data-tooltip="Remove this DOI from Stashes without deleting any imported document."
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(stash)}
                      type="button"
                    >
                      <Trash2 size={14} />
                      Remove
                    </button>
                  </AsyncActionSlot>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-inline">
          <Bookmark size={17} />
          <span>Stashed DOI recommendations will appear here.</span>
        </div>
      )}
    </section>
  );
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
  const [processingListNow, setProcessingListNow] = useState(() => Date.now());
  const queryClient = useQueryClient();
  const cancelFeedback = useAsyncActionFeedbackMap();
  const rescueFeedback = useAsyncActionFeedbackMap();
  const processUploadsFeedback = useAsyncActionFeedback();
  const sortedTags = useMemo(() => [...tags].sort((left, right) => left.name.localeCompare(right.name)), [tags]);
  const sortedProjects = useMemo(() => [...projects].sort((left, right) => left.name.localeCompare(right.name)), [projects]);
  const domainItems = useMemo(() => domainPickerItems(domains), [domains]);
  const tagItems = useMemo<ImportPickerItem[]>(
    () => sortedTags.map((tag) => ({ id: tag.id, name: tag.name })),
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
  const refreshImportQueueData = () => {
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };
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
      setDropMessage(`Staging ${importFileCountLabel(incomingFiles.length)}`);
    },
    onSuccess: (_batch, { incomingFiles }) => {
      setDropMessage(`Staged ${importFileCountLabel(incomingFiles.length)}`);
      refreshImportQueueData();
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
      setDropMessage(`Checking ${importFileCountLabel(incomingFiles.length)}`);
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
      refreshImportQueueData();
    },
    onError: (error, jobId) => {
      const message = actionFailureMessage("Could not requeue import job", error);
      rescueFeedback.showError(jobId, message);
      setDropMessage(message);
    },
  });
  const cancelJob = useMutation({
    mutationFn: (jobId: string) => api.cancelImportJob(jobId),
    onSuccess: (_job, jobId) => {
      cancelFeedback.showSuccess(jobId);
      setDropMessage("Import job canceled");
      refreshImportQueueData();
    },
    onError: (error, jobId) => {
      const message = actionFailureMessage("Could not cancel import job", error);
      cancelFeedback.showError(jobId, message);
      setDropMessage(message);
    },
  });
  const processStagedUploads = useMutation({
    mutationFn: api.processStagedImportJobs,
    onSuccess: (result) => {
      processUploadsFeedback.showSuccess();
      setDropMessage(result.updated_count ? `Processing ${importFileCountLabel(result.updated_count)}` : "No staged uploads");
      refreshImportQueueData();
    },
    onError: (error) => {
      const message = actionFailureMessage("Could not process staged uploads", error);
      processUploadsFeedback.showError(message);
      setDropMessage(message);
    },
  });
  const isDraggingFiles = dragDepth > 0;
  const importBusy = upload.isPending || duplicatePreflight.isPending;
  const duplicateFiles = duplicateCheck?.files.filter((file) => file.duplicate_in_upload || file.existing_documents.length > 0) || [];
  const retainedProcessingJobCount = jobs.filter((job) => !isImportCompletedRowExpired(job, processingListNow)).length;
  const processingJobs = visibleImportJobs(jobs, processingListNow);
  const hiddenProcessingJobCount = Math.max(0, retainedProcessingJobCount - processingJobs.length);
  const stagedJobs = jobs.filter((job) => job.status === "staged");
  const costPreviewJobs = jobs.filter(isImportCostPreviewJob);
  const processUploadsBusy = processStagedUploads.isPending;
  const processUploadsDisabled = !stagedJobs.length || importBusy || processUploadsBusy;

  useEffect(() => {
    if (!jobs.some((job) => job.status === "complete")) return undefined;
    const interval = window.setInterval(() => setProcessingListNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [jobs]);

  const hasDraggedFiles = (event: DragEvent<HTMLElement>) => Array.from(event.dataTransfer.types).includes("Files");
  const importFiles = (incomingFiles: FileList | File[]) => {
    const allFiles = Array.from(incomingFiles);
    const supportedFiles = allFiles.filter(isSupportedImportFile);
    if (importBusy) {
      setDropMessage("Import already running");
      return;
    }
    if (!supportedFiles.length) {
      setDropMessage(allFiles.length ? "PDF, HTML, or text only" : "No files selected");
      return;
    }
    const rejectedCount = allFiles.length - supportedFiles.length;
    if (rejectedCount > 0) {
      setDropMessage(`Staging ${supportedFiles.length}; ignored ${rejectedCount}`);
    }
    duplicatePreflight.mutate(supportedFiles);
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
          <strong>{isDraggingFiles ? "Release to check" : importBusy ? "Working" : "Drop documents"}</strong>
          <span className="dropzone-hint">{isDraggingFiles ? "Files will be checked for duplicates" : "PDF, HTML, TXT, or MD"}</span>
          <span className="dropzone-status">{dropMessage}</span>
        </div>
        <input
          aria-label="Import PDF, HTML, or text files"
          data-disabled-reason="an import or duplicate preflight check is already running."
          data-tooltip="Choose one or more PDF, HTML, or plain-text files; Medusa will hash them, check for duplicates, convert non-PDF files to PDF, and stage them with the current batch defaults."
          type="file"
          multiple
          accept={IMPORT_ACCEPT}
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
                    {file.source_kind && file.source_kind !== "pdf" && file.stored_filename ? ` / ${file.source_kind.toUpperCase()} -> ${file.stored_filename}` : ""}
                    {file.duplicate_in_upload ? " / duplicate in this drop" : ""}
                    {file.existing_documents.length ? ` / matches ${file.existing_documents[0].title}` : ""}
                  </small>
                </span>
                <StatusPill value={file.existing_documents.length ? "In library" : "In batch"} tone="warn" />
              </div>
            ))}
          </div>
          <div className="duplicate-actions">
            <button
              className="secondary-button"
              data-disabled-reason="the duplicate decision is already being uploaded."
              data-tooltip="Skip every exact duplicate in this upload and only import files without checksum matches."
              disabled={upload.isPending}
              onClick={() => applyDuplicateStrategy("skip")}
              type="button"
            >
              <X size={15} />
              Skip duplicates
            </button>
            <button
              className="secondary-button"
              data-disabled-reason="the duplicate decision is already being uploaded."
              data-tooltip="Reprocess matching existing document records with the newly uploaded duplicate files."
              disabled={upload.isPending}
              onClick={() => applyDuplicateStrategy("overwrite")}
              type="button"
            >
              <RefreshCw size={15} />
              Overwrite
            </button>
            <button
              className="primary-button"
              data-disabled-reason="the duplicate decision is already being uploaded."
              data-tooltip="Import the duplicate files anyway as separate document records with the same checksums."
              disabled={upload.isPending}
              onClick={() => applyDuplicateStrategy("import_anyway")}
              type="button"
            >
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
              Defaults are optional. Selected domains, tags, projects, priority, and read state will be applied to every staged document.
            </p>
          </div>
          <StatusPill value={selectedDefaultCount ? `${selectedDefaultCount} defaults` : "No organization defaults"} tone={selectedDefaultCount ? "blue" : "neutral"} />
        </div>
        <div className="import-default-controls">
          <label>
            Batch label
            <input
              data-tooltip="Type an optional label that will be stored on this import batch."
              value={batchLabel}
              onChange={(event) => setBatchLabel(event.target.value)}
              placeholder="Optional import label"
            />
          </label>
          <label>
            Priority
            <select data-tooltip="Choose the priority that will be applied to every document in this import batch." value={priority} onChange={(event) => setPriority(event.target.value)}>
              <option value="urgent">Urgent</option>
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
          </label>
          <label>
            Read status
            <select data-tooltip="Choose the read status that will be applied to every document in this import batch." value={readStatus} onChange={(event) => setReadStatus(event.target.value)}>
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
            hint="Apply known tags or create a tag before dropping files."
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
        <div className="job-list-head">
          <h2>Processing</h2>
          <div className="job-list-head-actions">
            <span>
              {hiddenProcessingJobCount
                ? `Showing ${processingJobs.length} of ${retainedProcessingJobCount}, active first`
                : retainedProcessingJobCount
                  ? `${retainedProcessingJobCount} visible`
                  : "No recent import jobs"}
            </span>
            <span className="queue-estimate-total" title="Rough total for staged and queued imports. Estimates use page count and prior import cost exemplars when available.">
              {costPreviewJobs.length ? `${importQueueEstimateLabel(costPreviewJobs)} for ${costPreviewJobs.length}` : "Rough total $0.00"}
            </span>
            <AsyncActionSlot busy={processUploadsBusy} feedback={processUploadsFeedback.feedback} label="Process uploads in progress">
              <button
                className={asyncFeedbackClass("primary-button compact", processUploadsFeedback.feedback, processUploadsBusy)}
                data-disabled-reason={
                  processUploadsBusy
                    ? "staged uploads are already being released."
                    : importBusy
                      ? "uploads are still being checked or staged."
                      : "there are no staged uploads ready to process."
                }
                data-tooltip="Start all staged uploads through the import processing pipeline."
                disabled={processUploadsDisabled}
                onClick={() => processStagedUploads.mutate()}
                type="button"
              >
                <Play className={processUploadsBusy ? "spin" : ""} size={15} />
                Process Uploads
              </button>
            </AsyncActionSlot>
          </div>
        </div>
        {processingJobs.map((job) => (
          <ImportJobRow
            key={job.id}
            job={job}
            cancelBusy={cancelJob.isPending}
            cancelDisabled={!canCancelImportJob(job) || cancelJob.isPending}
            cancelFeedback={cancelFeedback.feedbackFor(job.id)}
            cancelTitle={importJobCancelTitle(job)}
            onCancel={isQueueImportJob(job) ? () => cancelJob.mutate(job.id) : undefined}
            onRetry={canRescueImportJob(job) ? () => rescueJob.mutate(job.id) : undefined}
            retryBusy={rescueJob.isPending}
            retryDisabled={rescueJob.isPending}
            retryFeedback={rescueFeedback.feedbackFor(job.id)}
            retryTitle="Requeue this import job"
            showCancelSlot={isQueueImportJob(job)}
            showRetrySlot={canRescueImportJob(job)}
          />
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
      <select data-tooltip="Choose this resource's run-sheet status." value={item.status} onChange={(event) => update.mutate({ status: event.target.value })}>
        <option value="candidate">Candidate</option>
        <option value="reading">Reading</option>
        <option value="used">Used</option>
        <option value="rejected">Rejected</option>
      </select>
      <select data-tooltip="Choose this resource's project priority." value={item.priority} onChange={(event) => update.mutate({ priority: event.target.value })}>
        <option value="urgent">Urgent</option>
        <option value="high">High</option>
        <option value="normal">Normal</option>
        <option value="low">Low</option>
      </select>
      <label className="used-toggle">
        <input
          data-tooltip="Mark whether this resource is used in the project's final output; enabling it also sets the status to Used."
          type="checkbox"
          checked={item.used_in_output}
          onChange={(event) => update.mutate({ used_in_output: event.target.checked, status: event.target.checked ? "used" : item.status })}
        />
        <span>Used</span>
      </label>
      <input
        data-tooltip="Edit this resource's run-sheet note; it saves when the field loses focus."
        value={note}
        onChange={(event) => setNote(event.target.value)}
        onBlur={() => {
          if (note !== (item.note || "")) update.mutate({ note });
        }}
        placeholder="Run-sheet note"
      />
      <button
        className="icon-button"
        data-disabled-reason="a project resource remove request is already running."
        data-tooltip="Remove this resource from the project run sheet without deleting the document from the library."
        onClick={() => remove.mutate()}
        disabled={remove.isPending}
      >
        <Trash2 size={15} />
      </button>
    </article>
  );
}

function TagRenameDialog({
  busy,
  error,
  onClose,
  onSubmit,
  tag,
}: {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (name: string) => void;
  tag: Tag;
}) {
  const [name, setName] = useState(tag.name);
  useEscapeLayer(true, onClose, ESCAPE_PRIORITY_DIALOG);
  const trimmedName = name.trim();
  return (
    <div
      className="modal-backdrop"
      data-escape-layer="dialog"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <form
        className="tag-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tag-rename-title"
        onSubmit={(event) => {
          event.preventDefault();
          if (trimmedName) onSubmit(trimmedName);
        }}
      >
        <div className="tag-dialog-head">
          <div>
            <span>Rename</span>
            <h2 id="tag-rename-title">{tag.name}</h2>
          </div>
          <button className="icon-button" type="button" data-tooltip="Close the tag rename dialog without saving." onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <label className="tag-dialog-field">
          Name
          <input data-tooltip="Type the new tag name." value={name} autoFocus onChange={(event) => setName(event.target.value)} />
        </label>
        {error ? <p className="form-error">{error}</p> : null}
        <div className="tag-dialog-actions">
          <button
            className="secondary-button"
            type="button"
            data-disabled-reason="a tag rename is already running."
            data-tooltip="Close the tag rename dialog without saving."
            onClick={onClose}
            disabled={busy}
          >
            <X size={16} />
            Cancel
          </button>
          <button
            className="primary-button"
            type="submit"
            data-disabled-reason={busy ? "a tag rename is already running." : "a new tag name is required."}
            data-tooltip={`Rename ${tag.name} to ${trimmedName || "the typed name"} and update affected document search/history.`}
            disabled={!trimmedName || busy}
          >
            <Edit3 size={16} />
            Rename
          </button>
        </div>
      </form>
    </div>
  );
}

function TagMergeDialog({
  busy,
  error,
  onClose,
  onSubmit,
  tags,
}: {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (choice: TagMergeChoice) => void;
  tags: Tag[];
}) {
  const sortedTags = useMemo(() => sortByName(tags), [tags]);
  const [mode, setMode] = useState<"keep" | "new">("keep");
  const [keepId, setKeepId] = useState(sortedTags[0]?.id || "");
  const [name, setName] = useState("");
  useEscapeLayer(true, onClose, ESCAPE_PRIORITY_DIALOG);
  useEffect(() => {
    if (!sortedTags.some((tag) => tag.id === keepId)) setKeepId(sortedTags[0]?.id || "");
  }, [keepId, sortedTags]);
  const trimmedName = name.trim();
  const canSubmit = mode === "new" ? Boolean(trimmedName) : Boolean(keepId);
  return (
    <div
      className="modal-backdrop"
      data-escape-layer="dialog"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <form
        className="tag-dialog merge"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tag-merge-title"
        onSubmit={(event) => {
          event.preventDefault();
          if (!canSubmit) return;
          onSubmit(mode === "new" ? { target_name: trimmedName } : { target_tag_id: keepId });
        }}
      >
        <div className="tag-dialog-head">
          <div>
            <span>Merge</span>
            <h2 id="tag-merge-title">{tags.length} tags selected</h2>
          </div>
          <button className="icon-button" type="button" data-tooltip="Close the tag merge dialog without merging tags." onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="tag-merge-options">
          {sortedTags.map((tag) => (
            <label key={tag.id} className="tag-choice">
              <input
                data-tooltip={`Choose ${tag.name} as the tag that will remain after merge.`}
                type="radio"
                checked={mode === "keep" && keepId === tag.id}
                onChange={() => {
                  setMode("keep");
                  setKeepId(tag.id);
                }}
              />
              <span>
                <strong>{tag.name}</strong>
                <small>{tag.document_count} documents</small>
              </span>
            </label>
          ))}
          <label className="tag-choice custom">
            <input data-tooltip="Choose a different merged tag name instead of keeping one selected tag." type="radio" checked={mode === "new"} onChange={() => setMode("new")} />
            <span>
              <strong>Different name</strong>
              <input
                data-tooltip="Type the new merged tag name."
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setMode("new");
                }}
                placeholder="Merged tag name"
              />
            </span>
          </label>
        </div>
        {error ? <p className="form-error">{error}</p> : null}
        <div className="tag-dialog-actions">
          <button
            className="secondary-button"
            type="button"
            data-disabled-reason="a tag merge is already running."
            data-tooltip="Close the tag merge dialog without merging tags."
            onClick={onClose}
            disabled={busy}
          >
            <X size={16} />
            Cancel
          </button>
          <button
            className="primary-button"
            type="submit"
            data-disabled-reason={busy ? "a tag merge is already running." : "choose a tag to keep or type a merged tag name."}
            data-tooltip="Merge the selected tags into the chosen tag name, update affected document search, and record document history."
            disabled={!canSubmit || busy}
          >
            <Tags size={16} />
            Confirm Merge
          </button>
        </div>
      </form>
    </div>
  );
}

function TagSuggestionMergeIntoDialog({
  busy,
  error,
  onClose,
  onSubmit,
  suggestion,
  tags,
}: {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (name: string) => void;
  suggestion: TagOptimizationSuggestion;
  tags: Tag[];
}) {
  const [name, setName] = useState("");
  useEscapeLayer(true, onClose, ESCAPE_PRIORITY_DIALOG);
  const sortedSourceTags = useMemo(() => sortByName(suggestion.source_tags), [suggestion.source_tags]);
  const normalizedName = normalizeTagInputName(name);
  const existingTag = useMemo(
    () => (normalizedName ? tags.find((tag) => normalizeTagInputName(tag.name) === normalizedName) : undefined),
    [normalizedName, tags],
  );
  return (
    <div
      className="modal-backdrop"
      data-escape-layer="dialog"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <form
        className="tag-dialog merge"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tag-merge-into-title"
        onSubmit={(event) => {
          event.preventDefault();
          if (!normalizedName || busy) return;
          onSubmit(normalizedName);
        }}
      >
        <div className="tag-dialog-head">
          <div>
            <span>Merge Into</span>
            <h2 id="tag-merge-into-title">{suggestion.target_name}</h2>
          </div>
          <button className="icon-button" type="button" data-tooltip="Close the merge-into dialog without changing tags." onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <label className="tag-dialog-field">
          Tag name
          <input
            data-tooltip="Type the tag name that should receive these source tags."
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
            placeholder={suggestion.target_name}
          />
        </label>
        <div className="tag-merge-preview tag-suggestion-tags" aria-label="Source tags">
          {sortedSourceTags.map((tag) => (
            <span key={tag.id}>
              {tag.name}
              <small>{tag.document_count}</small>
            </span>
          ))}
        </div>
        {existingTag ? (
          <p className="tag-merge-duplicate">
            A tag named <strong>{existingTag.name}</strong> already exists. Confirming will merge into that tag.
          </p>
        ) : null}
        {error ? <p className="form-error">{error}</p> : null}
        <div className="tag-dialog-actions">
          <button
            className="secondary-button"
            type="button"
            data-disabled-reason="a tag merge is already running."
            data-tooltip="Close the merge-into dialog without changing tags."
            onClick={onClose}
            disabled={busy}
          >
            <X size={16} />
            Cancel
          </button>
          <button
            className="primary-button"
            type="submit"
            data-disabled-reason={busy ? "a tag merge is already running." : "a tag name is required."}
            data-tooltip={
              existingTag
                ? `Merge these source tags into the existing ${existingTag.name} tag.`
                : `Merge these source tags into ${normalizedName || "the typed tag name"}.`
            }
            disabled={!normalizedName || busy}
          >
            <Merge size={16} />
            {existingTag ? "Use Existing Tag" : "Merge Into Tag"}
          </button>
        </div>
      </form>
    </div>
  );
}

function TagsView({ tags, preferences }: { tags: Tag[]; preferences?: AppPreferences }) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectionAnchorId, setSelectionAnchorId] = useState<string | null>(null);
  const [searchText, setSearchText] = useState("");
  const [sortKey, setSortKey] = useState<TagSortKey>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [renameOpen, setRenameOpen] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [operationError, setOperationError] = useState<string | null>(null);
  const [optimizationResult, setOptimizationResult] = useState<TagOptimizationResult | null>(null);
  const [optimizationError, setOptimizationError] = useState<string | null>(null);
  const [optimizationPaneOpen, setOptimizationPaneOpen] = useState(false);
  const [optimizationStartedAt, setOptimizationStartedAt] = useState<number | null>(null);
  const [optimizationNow, setOptimizationNow] = useState(() => Date.now());
  const [mergeIntoSuggestion, setMergeIntoSuggestion] = useState<TagOptimizationSuggestion | null>(null);
  const queryClient = useQueryClient();
  const tagIdSet = useMemo(() => new Set(tags.map((tag) => tag.id)), [tags]);
  const selectedTags = useMemo(() => tags.filter((tag) => selectedIds.includes(tag.id)), [selectedIds, tags]);
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const visibleTags = useMemo(() => {
    const normalizedSearch = searchText.trim().toLowerCase();
    const direction = sortDirection === "asc" ? 1 : -1;
    return tags
      .filter((tag) => {
        if (!normalizedSearch) return true;
        return tag.name.toLowerCase().includes(normalizedSearch);
      })
      .sort((left, right) => {
        if (sortKey === "status") {
          const statusCompare = formatTagStatus(left.status).localeCompare(formatTagStatus(right.status), undefined, {
            numeric: true,
            sensitivity: "base",
          });
          return statusCompare * direction || left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" });
        }
        if (sortKey === "documents") {
          const countCompare = (left.document_count - right.document_count) * direction;
          return countCompare || left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" });
        }
        return left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" }) * direction;
      });
  }, [searchText, sortDirection, sortKey, tags]);
  const allVisibleSelected = visibleTags.length > 0 && visibleTags.every((tag) => selectedSet.has(tag.id));
  const selectedDocumentCount = selectedTags.reduce((total, tag) => total + tag.document_count, 0);
  const optimizationScopeIds = useMemo(
    () => (selectedIds.length ? selectedIds : visibleTags.map((tag) => tag.id)),
    [selectedIds, visibleTags],
  );
  const optimizationScopeLabel = selectedIds.length ? `${selectedIds.length} selected` : `${visibleTags.length} visible`;
  const tagSuggestionsModel = preferences
    ? selectedAnalysisModel(preferences, TAG_SUGGESTIONS_MODEL_KEY, "gpt-5.4-mini")
    : "Loading model";
  const optimizationElapsedSeconds = optimizationStartedAt
    ? Math.max(0, Math.floor((optimizationNow - optimizationStartedAt) / 1000))
    : 0;
  const allOptimizationSuggestions = useMemo(
    () => [
      ...(optimizationResult?.suggestions ?? []),
      ...(optimizationResult?.singleton_suggestions ?? []),
      ...(optimizationResult?.orphan_merge_suggestions ?? []),
    ],
    [optimizationResult],
  );
  const orphanMergeSuggestions = optimizationResult?.orphan_merge_suggestions ?? [];
  const relationshipSuggestions = optimizationResult?.relationship_suggestions ?? [];
  const statusSuggestions = optimizationResult?.status_suggestions ?? [];
  const pruningSuggestions = optimizationResult?.pruning_suggestions ?? [];
  const orphanPruneSuggestions = optimizationResult?.orphan_prune_suggestions ?? [];
  const governanceSuggestionCount =
    allOptimizationSuggestions.length +
    relationshipSuggestions.length +
    statusSuggestions.length +
    pruningSuggestions.length +
    orphanPruneSuggestions.length;
  const optimizationAffectedDocuments = useMemo(
    () =>
      allOptimizationSuggestions.reduce((total, suggestion) => total + suggestion.affected_documents, 0) +
      pruningSuggestions.length,
    [allOptimizationSuggestions, pruningSuggestions],
  );
  const renameTag = useMutation({
    mutationFn: ({ tag, name }: { tag: Tag; name: string }) => api.renameTag(tag.id, name),
    onSuccess: (result) => {
      setRenameOpen(false);
      setOperationError(null);
      setSelectedIds([result.tag.id]);
      setNotice(`Renamed ${result.updated_documents} document${result.updated_documents === 1 ? "" : "s"}`);
      refreshTagManagementData(queryClient);
    },
    onError: (error) => setOperationError(actionFailureMessage("Could not rename tag", error)),
  });
  const mergeTags = useMutation({
    mutationFn: (choice: TagMergeChoice) =>
      api.mergeTags({
        source_tag_ids: choice.source_tag_ids || selectedIds,
        target_tag_id: choice.target_tag_id || null,
        target_name: choice.target_name || null,
      }),
    onSuccess: (result, choice) => {
      setMergeOpen(false);
      setMergeIntoSuggestion(null);
      setOperationError(null);
      setOptimizationError(null);
      setSelectedIds([result.tag.id]);
      setNotice(`Merged into ${result.tag.name}; updated ${result.updated_documents} document${result.updated_documents === 1 ? "" : "s"}`);
      const approvedSourceIds = new Set(choice.source_tag_ids || selectedIds);
      setOptimizationResult((current) =>
        current
          ? {
              ...current,
              suggestions: current.suggestions.filter((suggestion) => !suggestion.source_tag_ids.some((tagId) => approvedSourceIds.has(tagId))),
              singleton_suggestions: (current.singleton_suggestions ?? []).filter(
                (suggestion) => !suggestion.source_tag_ids.some((tagId) => approvedSourceIds.has(tagId)),
              ),
              orphan_merge_suggestions: (current.orphan_merge_suggestions ?? []).filter(
                (suggestion) => !suggestion.source_tag_ids.some((tagId) => approvedSourceIds.has(tagId)),
              ),
            }
          : current,
      );
      refreshTagManagementData(queryClient);
    },
    onError: (error) => setOperationError(actionFailureMessage("Could not merge tags", error)),
  });
  const updateTagGovernance = useMutation({
    mutationFn: ({ tagId, status }: { tagId: string; status: string }) => api.updateTagGovernance(tagId, { status }),
    onSuccess: (updatedTag) => {
      setOperationError(null);
      setOptimizationResult((current) =>
        current
          ? {
              ...current,
              status_suggestions: (current.status_suggestions ?? []).filter((suggestion) => suggestion.tag.id !== updatedTag.id),
            }
          : current,
      );
      setNotice(`Marked ${updatedTag.name} as ${updatedTag.status}`);
      refreshTagManagementData(queryClient);
    },
    onError: (error) => setOperationError(actionFailureMessage("Could not update tag status", error)),
  });
  const createTagRelationship = useMutation({
    mutationFn: (suggestion: TagRelationshipSuggestion) =>
      api.createTagRelationship({
        source_tag_id: suggestion.source_tag.id,
        target_tag_id: suggestion.target_tag.id,
        relationship_type: suggestion.relationship_type,
        rationale: suggestion.rationale,
        confidence: suggestion.confidence,
      }),
    onSuccess: (_, suggestion) => {
      setOperationError(null);
      setOptimizationResult((current) =>
        current
          ? {
              ...current,
              relationship_suggestions: (current.relationship_suggestions ?? []).filter((item) => item.id !== suggestion.id),
            }
          : current,
      );
      setNotice(`Approved ${formatRelationshipType(suggestion.relationship_type)} relationship`);
      refreshTagManagementData(queryClient);
    },
    onError: (error) => setOperationError(actionFailureMessage("Could not approve relationship", error)),
  });
  const pruneTagAssignment = useMutation({
    mutationFn: (suggestion: TagPruneSuggestion) =>
      api.pruneTagAssignment({
        document_id: suggestion.document_id,
        tag_id: suggestion.tag.id,
        rationale: suggestion.rationale,
      }),
    onSuccess: (_, suggestion) => {
      setOperationError(null);
      setOptimizationResult((current) =>
        current
          ? {
              ...current,
              pruning_suggestions: (current.pruning_suggestions ?? []).filter((item) => item.id !== suggestion.id),
            }
          : current,
      );
      setNotice(`Pruned ${suggestion.tag.name} from one document`);
      refreshTagManagementData(queryClient);
    },
    onError: (error) => setOperationError(actionFailureMessage("Could not prune assignment", error)),
  });
  const pruneOrphanTag = useMutation({
    mutationFn: (suggestion: TagOrphanPruneSuggestion) =>
      api.pruneOrphanTag({
        tag_id: suggestion.tag.id,
        rationale: suggestion.rationale,
      }),
    onSuccess: (result, suggestion) => {
      setOperationError(null);
      setOptimizationResult((current) =>
        current
          ? {
              ...current,
              orphan_prune_suggestions: (current.orphan_prune_suggestions ?? []).filter((item) => item.id !== suggestion.id),
            }
          : current,
      );
      setSelectedIds((current) => current.filter((tagId) => tagId !== result.tag_id));
      setNotice(`Pruned orphaned tag ${result.tag_name}`);
      refreshTagManagementData(queryClient);
    },
    onError: (error) => setOperationError(actionFailureMessage("Could not prune orphaned tag", error)),
  });
  const optimizeTags = useMutation({
    mutationFn: () => api.optimizeTags({ tag_ids: optimizationScopeIds }),
    onSuccess: (result) => {
      setOptimizationStartedAt(null);
      setOptimizationResult(result);
      setOptimizationError(null);
      setOperationError(null);
      setOptimizationPaneOpen(true);
      const suggestionCount =
        result.suggestions.length +
        (result.singleton_suggestions?.length ?? 0) +
        (result.orphan_merge_suggestions?.length ?? 0) +
        (result.relationship_suggestions?.length ?? 0) +
        (result.status_suggestions?.length ?? 0) +
        (result.pruning_suggestions?.length ?? 0) +
        (result.orphan_prune_suggestions?.length ?? 0);
      setNotice(
        suggestionCount
          ? `Found ${suggestionCount} optimization suggestion${suggestionCount === 1 ? "" : "s"}`
          : `No optimization suggestions found for ${optimizationScopeLabel}`,
      );
    },
    onError: (error) => {
      setOptimizationStartedAt(null);
      setOptimizationPaneOpen(true);
      setOptimizationError(actionFailureMessage("Could not optimize tags", error));
    },
  });
  useEffect(() => {
    if (!optimizeTags.isPending) return undefined;
    const interval = window.setInterval(() => setOptimizationNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [optimizeTags.isPending]);
  const approveAllTagOptimizations = useMutation({
    mutationFn: () =>
      api.approveAllTagOptimizations({
        merge_suggestions: allOptimizationSuggestions.map((suggestion) => ({
          id: suggestion.id,
          source_tag_ids: suggestion.source_tag_ids,
          target_tag_id: suggestion.target_tag_id ?? null,
          target_name: suggestion.target_name,
        })),
        relationship_suggestions: relationshipSuggestions.map((suggestion) => ({
          id: suggestion.id,
          source_tag_id: suggestion.source_tag.id,
          target_tag_id: suggestion.target_tag.id,
          relationship_type: suggestion.relationship_type,
          rationale: suggestion.rationale,
          confidence: suggestion.confidence,
        })),
        status_suggestions: statusSuggestions.map((suggestion) => ({
          id: suggestion.id,
          tag_id: suggestion.tag.id,
          suggested_status: suggestion.suggested_status,
          rationale: suggestion.rationale,
        })),
        pruning_suggestions: pruningSuggestions.map((suggestion) => ({
          id: suggestion.id,
          document_id: suggestion.document_id,
          tag_id: suggestion.tag.id,
          rationale: suggestion.rationale,
        })),
        orphan_prune_suggestions: orphanPruneSuggestions.map((suggestion) => ({
          id: suggestion.id,
          tag_id: suggestion.tag.id,
          rationale: suggestion.rationale,
        })),
      }),
    onSuccess: (result) => {
      const applied =
        result.merges_applied +
        result.relationships_applied +
        result.statuses_applied +
        result.prunes_applied +
        result.orphans_pruned;
      const skipped = result.skipped.length;
      setOptimizationResult((current) =>
        current
          ? {
              ...current,
              suggestions: [],
              singleton_suggestions: [],
              orphan_merge_suggestions: [],
              relationship_suggestions: [],
              status_suggestions: [],
              pruning_suggestions: [],
              orphan_prune_suggestions: [],
            }
          : current,
      );
      setOperationError(null);
      setOptimizationError(null);
      setNotice(
        `Approved ${applied} optimization action${applied === 1 ? "" : "s"}`
        + (skipped ? `; skipped ${skipped} stale suggestion${skipped === 1 ? "" : "s"}` : ""),
      );
      refreshTagManagementData(queryClient);
    },
    onError: (error) => {
      setOperationError(actionFailureMessage("Could not approve all optimizations", error));
    },
  });
  const approveAllDisabled =
    !governanceSuggestionCount ||
    optimizeTags.isPending ||
    mergeTags.isPending ||
    updateTagGovernance.isPending ||
    createTagRelationship.isPending ||
    pruneTagAssignment.isPending ||
    pruneOrphanTag.isPending ||
    approveAllTagOptimizations.isPending;

  useEffect(() => {
    setSelectedIds((current) => current.filter((id) => tagIdSet.has(id)));
    setSelectionAnchorId((current) => (current && tagIdSet.has(current) ? current : null));
    setOptimizationResult((current) =>
      current
        ? {
            ...current,
            suggestions: current.suggestions.filter((suggestion) => suggestion.source_tag_ids.every((tagId) => tagIdSet.has(tagId))),
            singleton_suggestions: (current.singleton_suggestions ?? []).filter((suggestion) =>
              suggestion.source_tag_ids.every((tagId) => tagIdSet.has(tagId)),
            ),
            orphan_merge_suggestions: (current.orphan_merge_suggestions ?? []).filter((suggestion) =>
              suggestion.source_tag_ids.every((tagId) => tagIdSet.has(tagId)),
            ),
            relationship_suggestions: (current.relationship_suggestions ?? []).filter(
              (suggestion) => tagIdSet.has(suggestion.source_tag.id) && tagIdSet.has(suggestion.target_tag.id),
            ),
            status_suggestions: (current.status_suggestions ?? []).filter((suggestion) => tagIdSet.has(suggestion.tag.id)),
            pruning_suggestions: (current.pruning_suggestions ?? []).filter((suggestion) => tagIdSet.has(suggestion.tag.id)),
            orphan_prune_suggestions: (current.orphan_prune_suggestions ?? []).filter((suggestion) => tagIdSet.has(suggestion.tag.id)),
          }
        : current,
    );
  }, [tagIdSet]);

  const chooseSort = (key: TagSortKey) => {
    if (key === sortKey) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDirection(key === "documents" ? "desc" : "asc");
  };
  const clearTagSelection = () => {
    setSelectedIds([]);
    setSelectionAnchorId(null);
  };
  const toggleTag = (id: string, selected: boolean, shiftKey = false) => {
    const visibleIds = visibleTags.map((tag) => tag.id);
    const anchorIndex = selectionAnchorId ? visibleIds.indexOf(selectionAnchorId) : -1;
    const currentIndex = visibleIds.indexOf(id);
    const shouldApplyRange = shiftKey && anchorIndex >= 0 && currentIndex >= 0;
    const affectedIds = shouldApplyRange
      ? visibleIds.slice(Math.min(anchorIndex, currentIndex), Math.max(anchorIndex, currentIndex) + 1)
      : [id];

    setSelectedIds((current) =>
      selected ? uniqueValues([...current, ...affectedIds]) : current.filter((item) => !affectedIds.includes(item)),
    );
    if (!shouldApplyRange) {
      setSelectionAnchorId(id);
    }
  };
  const toggleVisibleTags = () => {
    if (allVisibleSelected) {
      const visibleIds = new Set(visibleTags.map((tag) => tag.id));
      setSelectedIds((current) => current.filter((id) => !visibleIds.has(id)));
      setSelectionAnchorId((current) => (current && visibleIds.has(current) ? null : current));
      return;
    }
    setSelectedIds((current) => uniqueValues([...current, ...visibleTags.map((tag) => tag.id)]));
    setSelectionAnchorId(visibleTags[0]?.id ?? null);
  };
  const openRename = () => {
    if (selectedTags.length !== 1) return;
    setOperationError(null);
    setRenameOpen(true);
  };
  const openMerge = () => {
    if (selectedTags.length < 2) return;
    setOperationError(null);
    setMergeOpen(true);
  };
  const dismissSuggestion = (suggestionId: string) => {
    setOptimizationResult((current) =>
      current
        ? {
            ...current,
            suggestions: current.suggestions.filter((suggestion) => suggestion.id !== suggestionId),
            singleton_suggestions: (current.singleton_suggestions ?? []).filter((suggestion) => suggestion.id !== suggestionId),
            orphan_merge_suggestions: (current.orphan_merge_suggestions ?? []).filter((suggestion) => suggestion.id !== suggestionId),
          }
        : current,
    );
  };
  const approveSuggestion = (suggestion: TagOptimizationSuggestion) => {
    setOperationError(null);
    mergeTags.mutate({ source_tag_ids: suggestion.source_tag_ids, target_name: suggestion.target_name });
  };
  const openSuggestionMergeInto = (suggestion: TagOptimizationSuggestion) => {
    setOperationError(null);
    setMergeIntoSuggestion(suggestion);
  };
  const startOptimization = () => {
    const startedAt = Date.now();
    setOptimizationStartedAt(startedAt);
    setOptimizationNow(startedAt);
    setOptimizationPaneOpen(true);
    setOptimizationError(null);
    setOperationError(null);
    optimizeTags.mutate();
  };
  const selectedTag = selectedTags.length === 1 ? selectedTags[0] : undefined;
  const renderOptimizationSuggestion = (suggestion: TagOptimizationSuggestion) => {
    const sortedSourceTags = sortByName(suggestion.source_tags);
    return (
      <article className="tag-optimization-suggestion" key={suggestion.id}>
        <div className="tag-suggestion-main">
          <div className="tag-suggestion-title">
            <strong>{suggestion.target_name}</strong>
            <span>
              {suggestion.affected_documents} document{suggestion.affected_documents === 1 ? "" : "s"} affected /{" "}
              {formatTagOptimizationConfidence(suggestion.confidence)} confidence
            </span>
          </div>
          <p>{suggestion.rationale}</p>
          <div className="tag-suggestion-tags" aria-label="Source tags">
            {sortedSourceTags.map((tag) => (
              <span key={tag.id}>
                {tag.name}
                <small>{tag.document_count}</small>
              </span>
            ))}
          </div>
        </div>
        <div className="tag-suggestion-actions">
          <button
            className="primary-button compact"
            type="button"
            data-disabled-reason="a tag merge is already running."
            data-tooltip={`Apply this suggestion by merging its source tags into ${suggestion.target_name}.`}
            disabled={mergeTags.isPending}
            onClick={() => approveSuggestion(suggestion)}
          >
            <Tags size={15} />
            Approve Merge
          </button>
          <button
            className="secondary-button compact"
            type="button"
            data-disabled-reason="a tag merge is already running."
            data-tooltip="Choose a different tag name for this merge suggestion."
            disabled={mergeTags.isPending}
            onClick={() => openSuggestionMergeInto(suggestion)}
          >
            <Merge size={15} />
            Merge Into...
          </button>
          <button
            className="secondary-button compact"
            type="button"
            data-disabled-reason="a tag merge is already running."
            data-tooltip="Dismiss this suggestion from the current optimization plan without changing tags."
            disabled={mergeTags.isPending}
            onClick={() => dismissSuggestion(suggestion.id)}
          >
            <X size={15} />
            Dismiss
          </button>
        </div>
      </article>
    );
  };
  const dismissRelationshipSuggestion = (suggestionId: string) => {
    setOptimizationResult((current) =>
      current
        ? {
            ...current,
            relationship_suggestions: (current.relationship_suggestions ?? []).filter((suggestion) => suggestion.id !== suggestionId),
          }
        : current,
    );
  };
  const dismissStatusSuggestion = (suggestionId: string) => {
    setOptimizationResult((current) =>
      current
        ? {
            ...current,
            status_suggestions: (current.status_suggestions ?? []).filter((suggestion) => suggestion.id !== suggestionId),
          }
        : current,
    );
  };
  const dismissPruningSuggestion = (suggestionId: string) => {
    setOptimizationResult((current) =>
      current
        ? {
            ...current,
            pruning_suggestions: (current.pruning_suggestions ?? []).filter((suggestion) => suggestion.id !== suggestionId),
          }
        : current,
    );
  };
  const dismissOrphanPruneSuggestion = (suggestionId: string) => {
    setOptimizationResult((current) =>
      current
        ? {
            ...current,
            orphan_prune_suggestions: (current.orphan_prune_suggestions ?? []).filter((suggestion) => suggestion.id !== suggestionId),
          }
        : current,
    );
  };
  const renderRelationshipSuggestion = (suggestion: TagRelationshipSuggestion) => (
    <article className="tag-optimization-suggestion" key={suggestion.id}>
      <div className="tag-suggestion-main">
        <div className="tag-suggestion-title">
          <strong>{formatRelationshipType(suggestion.relationship_type)}</strong>
          <span>{formatTagOptimizationConfidence(suggestion.confidence)} confidence</span>
        </div>
        <p>{suggestion.rationale}</p>
        <div className="tag-suggestion-tags" aria-label="Relationship tags">
          <span>
            {suggestion.source_tag.name}
            <small>{formatTagStatus(suggestion.source_tag.status)}</small>
          </span>
          <span>
            {suggestion.target_tag.name}
            <small>{formatTagStatus(suggestion.target_tag.status)}</small>
          </span>
        </div>
      </div>
      <div className="tag-suggestion-actions">
        <button
          className="primary-button compact"
          data-disabled-reason="a tag relationship is already being approved."
          data-tooltip="Approve this semantic relationship without merging the two tags."
          disabled={createTagRelationship.isPending}
          onClick={() => createTagRelationship.mutate(suggestion)}
          type="button"
        >
          <Orbit size={15} />
          Approve
        </button>
        <button
          className="secondary-button compact"
          data-disabled-reason="a tag relationship is already being approved."
          data-tooltip="Dismiss this relationship suggestion from the current plan."
          disabled={createTagRelationship.isPending}
          onClick={() => dismissRelationshipSuggestion(suggestion.id)}
          type="button"
        >
          <X size={15} />
          Dismiss
        </button>
      </div>
    </article>
  );
  const renderStatusSuggestion = (suggestion: TagStatusSuggestion) => (
    <article className="tag-optimization-suggestion" key={suggestion.id}>
      <div className="tag-suggestion-main">
        <div className="tag-suggestion-title">
          <strong>{suggestion.tag.name}</strong>
          <span>
            {formatTagStatus(suggestion.tag.status)} to {formatTagStatus(suggestion.suggested_status)} /{" "}
            {formatTagOptimizationConfidence(suggestion.confidence)} confidence
          </span>
        </div>
        <p>{suggestion.rationale}</p>
      </div>
      <div className="tag-suggestion-actions">
        <button
          className="primary-button compact"
          data-disabled-reason="a tag status update is already saving."
          data-tooltip={`Approve this governance status change to ${formatTagStatus(suggestion.suggested_status)}.`}
          disabled={updateTagGovernance.isPending}
          onClick={() => updateTagGovernance.mutate({ tagId: suggestion.tag.id, status: suggestion.suggested_status })}
          type="button"
        >
          <CheckCircle2 size={15} />
          Approve
        </button>
        <button
          className="secondary-button compact"
          data-disabled-reason="a tag status update is already saving."
          data-tooltip="Dismiss this status suggestion from the current plan."
          disabled={updateTagGovernance.isPending}
          onClick={() => dismissStatusSuggestion(suggestion.id)}
          type="button"
        >
          <X size={15} />
          Dismiss
        </button>
      </div>
    </article>
  );
  const renderPruningSuggestion = (suggestion: TagPruneSuggestion) => (
    <article className="tag-optimization-suggestion" key={suggestion.id}>
      <div className="tag-suggestion-main">
        <div className="tag-suggestion-title">
          <strong>{suggestion.tag.name}</strong>
          <span>
            {formatTagOptimizationConfidence(suggestion.confidence)} prune confidence / score {formatTagOptimizationConfidence(suggestion.overall_score)}
          </span>
        </div>
        <p>{suggestion.document_title}</p>
        <p>{suggestion.rationale}</p>
        <div className="tag-optimization-summary inline">
          <span>relevance {formatTagOptimizationConfidence(suggestion.relevance_score)}</span>
          <span>fit {formatTagOptimizationConfidence(suggestion.library_fit_score)}</span>
          <span>novelty {formatTagOptimizationConfidence(suggestion.novelty_score)}</span>
        </div>
      </div>
      <div className="tag-suggestion-actions">
        <button
          className="primary-button compact"
          data-disabled-reason="a tag assignment prune is already saving."
          data-tooltip="Remove this tag from the named document and record document history."
          disabled={pruneTagAssignment.isPending}
          onClick={() => pruneTagAssignment.mutate(suggestion)}
          type="button"
        >
          <Eraser size={15} />
          Prune
        </button>
        <button
          className="secondary-button compact"
          data-disabled-reason="a tag assignment prune is already saving."
          data-tooltip="Dismiss this pruning suggestion from the current plan."
          disabled={pruneTagAssignment.isPending}
          onClick={() => dismissPruningSuggestion(suggestion.id)}
          type="button"
        >
          <X size={15} />
          Dismiss
        </button>
      </div>
    </article>
  );
  const renderOrphanPruneSuggestion = (suggestion: TagOrphanPruneSuggestion) => (
    <article className="tag-optimization-suggestion" key={suggestion.id}>
      <div className="tag-suggestion-main">
        <div className="tag-suggestion-title">
          <strong>{suggestion.tag.name}</strong>
          <span>{formatTagOptimizationConfidence(suggestion.confidence)} prune confidence / 0 document links</span>
        </div>
        <p>{suggestion.rationale}</p>
        <div className="tag-optimization-summary inline">
          <span>{formatTagStatus(suggestion.tag.status)}</span>
          <span>orphaned tag</span>
        </div>
      </div>
      <div className="tag-suggestion-actions">
        <button
          className="primary-button compact"
          data-disabled-reason="an orphaned tag prune is already saving."
          data-tooltip="Delete this unused tag because it has no document links."
          disabled={pruneOrphanTag.isPending}
          onClick={() => pruneOrphanTag.mutate(suggestion)}
          type="button"
        >
          <Eraser size={15} />
          Prune Tag
        </button>
        <button
          className="secondary-button compact"
          data-disabled-reason="an orphaned tag prune is already saving."
          data-tooltip="Dismiss this orphaned-tag prune suggestion from the current plan."
          disabled={pruneOrphanTag.isPending}
          onClick={() => dismissOrphanPruneSuggestion(suggestion.id)}
          type="button"
        >
          <X size={15} />
          Dismiss
        </button>
      </div>
    </article>
  );

  return (
    <section className={`workbench tags-workbench${optimizationPaneOpen ? " has-optimization-pane" : ""}`}>
      <div className="tags-toolbar">
        <div className="tag-actions">
          <button
            className="secondary-button compact"
            type="button"
            data-disabled-reason="no tags are selected."
            data-tooltip="Clear the current tag selection without changing any tags."
            disabled={!selectedIds.length}
            onClick={clearTagSelection}
          >
            <X size={15} />
            Clear Selection
          </button>
          <button
            className="secondary-button compact"
            type="button"
            data-disabled-reason={renameTag.isPending ? "a tag rename is already running." : "select exactly one tag to rename."}
            data-tooltip="Open the rename dialog for the single selected tag."
            disabled={selectedIds.length !== 1 || renameTag.isPending}
            onClick={openRename}
          >
            <Edit3 size={15} />
            Rename
          </button>
          <button
            className="primary-button compact"
            type="button"
            data-disabled-reason={mergeTags.isPending ? "a tag merge is already running." : "select two or more tags to merge."}
            data-tooltip="Open the merge dialog for the selected tags."
            disabled={selectedIds.length < 2 || mergeTags.isPending}
            onClick={openMerge}
          >
            <Tags size={15} />
            Merge ({selectedIds.length})
          </button>
          <button
            className="secondary-button compact"
            type="button"
            data-disabled-reason="tag delete is reserved for a future implementation."
            data-tooltip="Delete selected tags after confirmation when tag deletion is implemented."
            disabled
          >
            <Trash2 size={15} />
            Delete
          </button>
          <button
            className="secondary-button compact"
            type="button"
            data-disabled-reason={optimizeTags.isPending ? "a tag optimization plan is already being generated." : "at least two tags must be in the optimization scope."}
            data-tooltip="Ask the selected model to propose reviewable tag merge suggestions for the selected or visible tag scope."
            disabled={optimizationScopeIds.length < 2 || optimizeTags.isPending}
            onClick={startOptimization}
          >
            <BrainCircuit className={optimizeTags.isPending ? "spin" : ""} size={15} />
            {optimizeTags.isPending ? "Optimizing" : "Optimize"}
          </button>
        </div>
        <label className="tag-search">
          <Search size={16} />
          <input
            data-tooltip="Type to filter the tag table by tag name."
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            placeholder="Search tags"
          />
        </label>
      </div>
      <div className="tags-layout">
        <div className="tags-main-column">
          <div className="tags-status-row">
            <span>{visibleTags.length} tags</span>
            <span>{selectedIds.length ? `${selectedIds.length} selected / ${selectedDocumentCount} document links` : notice || "No tags selected"}</span>
          </div>
          {notice ? <p className="tag-operation-notice">{notice}</p> : null}
          <div className="tags-table" role="table" aria-label="Tags">
            <div className="tags-table-row header" role="row">
              <span role="columnheader">
                <input type="checkbox" checked={allVisibleSelected} onChange={toggleVisibleTags} aria-label="Select visible tags" />
              </span>
              {(["name", "status", "documents"] as TagSortKey[]).map((key) => (
                <button
                  key={key}
                  aria-sort={sortKey === key ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}
                  data-tooltip={`Sort the tag table by ${tagSortLabel(key).toLocaleLowerCase()}; press again to reverse direction.`}
                  onClick={() => chooseSort(key)}
                  role="columnheader"
                  type="button"
                >
                  {tagSortLabel(key)}
                  <ArrowUpDown size={14} />
                </button>
              ))}
            </div>
            {visibleTags.map((tag) => {
              const selected = selectedSet.has(tag.id);
              return (
                <label key={tag.id} className={`tags-table-row${selected ? " selected" : ""}`} role="row">
                  <span role="cell">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={(event) => toggleTag(tag.id, event.currentTarget.checked, inputEventShiftKey(event))}
                    />
                  </span>
                  <strong role="cell">{tag.name}</strong>
                  <span role="cell">{formatTagStatus(tag.status)}</span>
                  <span role="cell">{tag.document_count}</span>
                </label>
              );
            })}
            {!visibleTags.length ? <div className="tags-table-empty">No matching tags</div> : null}
          </div>
        </div>
        {optimizationPaneOpen ? (
          <aside
            className="tag-optimization-panel"
            aria-busy={approveAllTagOptimizations.isPending || optimizeTags.isPending}
            aria-label="Tag optimization plan"
          >
            <div className="tag-optimization-head">
              <div className="tag-optimization-title">
                <span>Optimization Plan</span>
                <strong>
                  {optimizeTags.isPending
                    ? "Building plan"
                    : optimizationResult
                      ? `${governanceSuggestionCount} proposed action${governanceSuggestionCount === 1 ? "" : "s"}`
                      : "Ready to optimize"}
                </strong>
              </div>
              <div className="tag-optimization-head-actions">
                <button
                  className="primary-button compact"
                  type="button"
                  data-disabled-reason={
                    approveAllTagOptimizations.isPending
                      ? "all optimization actions are already being approved."
                      : "there are no optimization actions to approve."
                  }
                  data-tooltip="Approve every merge, relationship, status, and pruning suggestion currently in this optimization plan."
                  disabled={approveAllDisabled}
                  onClick={() => approveAllTagOptimizations.mutate()}
                >
                  <CheckCircle2 className={approveAllTagOptimizations.isPending ? "spin" : ""} size={15} />
                  {approveAllTagOptimizations.isPending ? "Approving" : `Approve All${governanceSuggestionCount ? ` (${governanceSuggestionCount})` : ""}`}
                </button>
                <button className="icon-button" type="button" data-tooltip="Close the tag optimization plan pane." onClick={() => setOptimizationPaneOpen(false)}>
                  <X size={16} />
                </button>
              </div>
            </div>
            {optimizeTags.isPending ? (
              <div className="tag-optimization-progress" role="status" aria-live="polite">
                <div className="tag-optimization-progress-copy">
                  <span>Building plan</span>
                  <strong>
                    Reviewing {optimizationScopeLabel} tags with {tagSuggestionsModel} - {formatDuration(optimizationElapsedSeconds) || "0s"}
                  </strong>
                </div>
                <div
                  className="tag-optimization-progress-track"
                  role="progressbar"
                  aria-label="Tag optimization plan generation in progress"
                  aria-valuetext={`Building plan for ${optimizationScopeLabel} tags`}
                >
                  <span />
                </div>
              </div>
            ) : null}
            {approveAllTagOptimizations.isPending ? (
              <div className="tag-optimization-progress" role="status" aria-live="polite">
                <div className="tag-optimization-progress-copy">
                  <span>Bulk apply</span>
                  <strong>
                    Applying {governanceSuggestionCount} action{governanceSuggestionCount === 1 ? "" : "s"}
                    {optimizationAffectedDocuments ? ` across ${optimizationAffectedDocuments} document reference${optimizationAffectedDocuments === 1 ? "" : "s"}` : ""}
                  </strong>
                </div>
                <div
                  className="tag-optimization-progress-track"
                  role="progressbar"
                  aria-label="Bulk optimization approval in progress"
                  aria-valuetext="Applying optimization actions"
                >
                  <span />
                </div>
              </div>
            ) : null}
            <div className="tag-optimization-summary">
              <span>{optimizationResult ? optimizationResult.model : tagSuggestionsModel}</span>
              <span>{optimizationResult ? `${optimizationResult.considered_tags} reviewed` : `${optimizationScopeLabel} tags`}</span>
              {optimizationResult?.health_summary?.candidate_tags ? <span>{optimizationResult.health_summary.candidate_tags} candidates</span> : null}
              {optimizationResult?.health_summary?.weak_assignments ? <span>{optimizationResult.health_summary.weak_assignments} weak assignments</span> : null}
              {governanceSuggestionCount ? <span>{optimizationAffectedDocuments} affected document references</span> : null}
            </div>
            {optimizationError ? <p className="form-error tag-optimization-error">{optimizationError}</p> : null}
            {operationError && !renameOpen && !mergeOpen && !mergeIntoSuggestion ? <p className="form-error tag-optimization-error">{operationError}</p> : null}
            {optimizeTags.isPending ? (
              <div className="tag-optimization-loading">
                <BrainCircuit className="spin" size={18} />
                <span>Drafting tag combination plan...</span>
              </div>
            ) : governanceSuggestionCount ? (
              <div className="tag-optimization-list">
                {optimizationResult?.suggestions.length ? (
                  <section className="tag-optimization-section">
                    <div className="tag-optimization-section-head">
                      <strong>Primary merges</strong>
                      <span>Strict duplicate, variant, and primitive-target candidates.</span>
                    </div>
                    {optimizationResult.suggestions.map(renderOptimizationSuggestion)}
                  </section>
                ) : null}
                {orphanMergeSuggestions.length || orphanPruneSuggestions.length ? (
                  <section className="tag-optimization-section">
                    <div className="tag-optimization-section-head">
                      <strong>Orphaned tags</strong>
                      <span>Zero-link tags should merge into useful used tags when there is a strong match, or be pruned entirely.</span>
                    </div>
                    {orphanMergeSuggestions.map(renderOptimizationSuggestion)}
                    {orphanPruneSuggestions.map(renderOrphanPruneSuggestion)}
                  </section>
                ) : null}
                {optimizationResult?.singleton_suggestions?.length ? (
                  <section className="tag-optimization-section singleton">
                    <div className="tag-optimization-section-head">
                      <strong>Single-document cleanup</strong>
                      <span>Looser count-1 candidates from prefixes, plurals, and close variants.</span>
                    </div>
                    {optimizationResult.singleton_suggestions.map(renderOptimizationSuggestion)}
                  </section>
                ) : null}
                {relationshipSuggestions.length ? (
                  <section className="tag-optimization-section">
                    <div className="tag-optimization-section-head">
                      <strong>Relationships</strong>
                      <span>Semantic covered-by and cluster links that teach the taxonomy without merging.</span>
                    </div>
                    {relationshipSuggestions.map(renderRelationshipSuggestion)}
                  </section>
                ) : null}
                {statusSuggestions.length ? (
                  <section className="tag-optimization-section">
                    <div className="tag-optimization-section-head">
                      <strong>Statuses</strong>
                      <span>Candidate promotion, retirement, or blocking suggestions for review.</span>
                    </div>
                    {statusSuggestions.map(renderStatusSuggestion)}
                  </section>
                ) : null}
                {pruningSuggestions.length ? (
                  <section className="tag-optimization-section">
                    <div className="tag-optimization-section-head">
                      <strong>Weak assignments</strong>
                      <span>Document-tag links scored weakly enough to prune individually.</span>
                    </div>
                    {pruningSuggestions.map(renderPruningSuggestion)}
                  </section>
                ) : null}
              </div>
            ) : optimizationError ? null : optimizationResult ? (
              <p className="tag-optimization-empty">No governance suggestions found for this scope.</p>
            ) : (
              <p className="tag-optimization-empty">Run Optimize to draft a tag governance plan for the current scope.</p>
            )}
          </aside>
        ) : null}
      </div>
      {renameOpen && selectedTag ? (
        <TagRenameDialog
          busy={renameTag.isPending}
          error={operationError}
          onClose={() => {
            setRenameOpen(false);
            setOperationError(null);
          }}
          onSubmit={(name) => renameTag.mutate({ tag: selectedTag, name })}
          tag={selectedTag}
        />
      ) : null}
      {mergeOpen ? (
        <TagMergeDialog
          busy={mergeTags.isPending}
          error={operationError}
          onClose={() => {
            setMergeOpen(false);
            setOperationError(null);
          }}
          onSubmit={(choice) => mergeTags.mutate(choice)}
          tags={selectedTags}
        />
      ) : null}
      {mergeIntoSuggestion ? (
        <TagSuggestionMergeIntoDialog
          busy={mergeTags.isPending}
          error={operationError}
          onClose={() => {
            setMergeIntoSuggestion(null);
            setOperationError(null);
          }}
          onSubmit={(name) => mergeTags.mutate({ source_tag_ids: mergeIntoSuggestion.source_tag_ids, target_name: name })}
          suggestion={mergeIntoSuggestion}
          tags={tags}
        />
      ) : null}
    </section>
  );
}

function refreshTagManagementData(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["tags"] });
  void queryClient.invalidateQueries({ queryKey: ["documents"] });
  void queryClient.invalidateQueries({ queryKey: ["document"] });
  void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
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
  const bibliographyEntries =
    bibliographyStyle === "apa"
      ? bibliographyText
          .split("\n")
          .map((entry) => decodeHtmlEntities(entry).trim())
          .filter(Boolean)
      : [];

  return (
    <section className="workbench project-workbench">
      <aside className="project-sidebar">
        <div className="inline-form">
          <input data-tooltip="Type a new project name." value={name} onChange={(event) => setName(event.target.value)} placeholder="New project" />
          <button
            className="primary-button"
            data-disabled-reason="a project name is required."
            data-tooltip="Create a new project run sheet with this name."
            disabled={!name}
            onClick={() => create.mutate()}
          >
            <Plus size={16} />
            Add
          </button>
        </div>
        <div className="project-list">
          {projects.map((project) => (
            <button
              key={project.id}
              className={project.id === selectedProjectId ? "selected" : ""}
              data-tooltip={`Open the ${project.name} project run sheet.`}
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
        </div>
        {current ? (
          <>
            <div className="project-add-row">
              <select data-tooltip="Choose a library document to add as a project resource." value={addDocumentId} onChange={(event) => setAddDocumentId(event.target.value)}>
                <option value="">Add a library document</option>
                {availableDocuments.map((document) => (
                  <option key={document.id} value={document.id}>
                    {document.title}
                  </option>
                ))}
              </select>
              <button
                className="secondary-button"
                data-disabled-reason={addItem.isPending ? "a project resource add request is already running." : "choose a library document first."}
                data-tooltip="Add the selected library document to this project run sheet."
                disabled={!addDocumentId || addItem.isPending}
                onClick={() => addItem.mutate()}
              >
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
            data-disabled-reason="generate a bibliography before copying it."
            data-tooltip="Copy the currently displayed bibliography text to the clipboard."
            disabled={!bibliographyText}
            onClick={() => {
              void copyToClipboard("bibliography", decodeHtmlEntities(bibliographyText));
            }}
          >
            {copiedKey === "bibliography" ? <CheckCircle2 size={16} /> : <Clipboard size={16} />}
            {copiedKey === "bibliography" ? "Copied" : "Copy"}
          </button>
        </div>
        <div className="bibliography-generate-actions">
          <button
            className="secondary-button"
            data-disabled-reason="select or create a project first."
            data-tooltip="Generate a bibliography from every source in the selected project run sheet."
            disabled={!current}
            onClick={() => void generateBibliography(false)}
          >
            <Clipboard size={16} />
            All sources
          </button>
          <button
            className="primary-button"
            data-disabled-reason="select or create a project first."
            data-tooltip="Generate a bibliography from only the sources marked Used in the selected project run sheet."
            disabled={!current}
            onClick={() => void generateBibliography(true)}
          >
            <CheckSquare size={16} />
            Used only
          </button>
        </div>
        <div className="bibliography-tabs">
          {(["apa", "bibtex", "ris", "csl_json"] as const).map((style) => (
            <button
              key={style}
              className={style === bibliographyStyle ? "selected" : ""}
              data-disabled-reason="generate a bibliography before switching export formats."
              data-tooltip={`Show the generated bibliography as ${style.replace("_", " ").toUpperCase()}.`}
              onClick={() => setBibliographyStyle(style)}
              disabled={!bibliography}
            >
              {style.replace("_", " ").toUpperCase()}
            </button>
          ))}
        </div>
        {bibliographyStyle === "apa" ? (
          <div className="bibliography bibliography-rich">
            {bibliographyEntries.length ? (
              bibliographyEntries.map((entry, index) => (
                <p key={`bibliography-entry-${index}`}>{renderInlineMarkdown(entry, `bibliography-entry-${index}`)}</p>
              ))
            ) : (
              <p className="markdown-empty">No bibliography generated yet.</p>
            )}
          </div>
        ) : (
          <pre className="bibliography bibliography-plain">{bibliographyText || "No bibliography generated yet."}</pre>
        )}
      </section>
    </section>
  );
}

function QueueView({ items, jobs }: { items: CitationCandidate[]; jobs: ImportJob[] }) {
  const queryClient = useQueryClient();
  const [queueActionMessage, setQueueActionMessage] = useState("");
  const cancelFeedback = useAsyncActionFeedbackMap();
  const rescueFeedback = useAsyncActionFeedbackMap();
  const processUploadsFeedback = useAsyncActionFeedback();
  const retryFailedFeedback = useAsyncActionFeedback();
  const clearQueueFeedback = useAsyncActionFeedback();
  const clearFailedFeedback = useAsyncActionFeedback();
  const refreshQueueData = () => {
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  };
  const describeQueueAction = (verb: string, result: { updated_count: number; skipped_running_count?: number; skipped_unretryable_count?: number }) => {
    const parts = [`${verb} ${result.updated_count}`];
    if (result.skipped_running_count) parts.push(`kept ${result.skipped_running_count} running`);
    if (result.skipped_unretryable_count) parts.push(`skipped ${result.skipped_unretryable_count} without documents`);
    return parts.join("; ");
  };
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
      setQueueActionMessage("Retry requested");
      refreshQueueData();
    },
    onError: (error, jobId) => {
      rescueFeedback.showError(jobId, actionFailureMessage("Could not requeue import job", error));
    },
  });
  const cancelJob = useMutation({
    mutationFn: (jobId: string) => api.cancelImportJob(jobId),
    onSuccess: (_job, jobId) => {
      cancelFeedback.showSuccess(jobId);
      setQueueActionMessage("Canceled 1");
      refreshQueueData();
    },
    onError: (error, jobId) => {
      cancelFeedback.showError(jobId, actionFailureMessage("Could not cancel import job", error));
    },
  });
  const queueJobs = orderedImportJobs(jobs.filter(isQueueImportJob));
  const stagedQueueJobs = queueJobs.filter((job) => job.status === "staged");
  const costPreviewQueueJobs = queueJobs.filter(isImportCostPreviewJob);
  const failedQueueJobs = queueJobs.filter((job) => job.status === "failed");
  const clearableQueueJobs = queueJobs.filter((job) => job.status !== "running");
  const processStagedUploads = useMutation({
    mutationFn: api.processStagedImportJobs,
    onSuccess: (result) => {
      processUploadsFeedback.showSuccess();
      setQueueActionMessage(describeQueueAction("Processing", result));
      refreshQueueData();
    },
    onError: (error) => {
      processUploadsFeedback.showError(actionFailureMessage("Could not process staged uploads", error));
    },
  });
  const retryFailedJobs = useMutation({
    mutationFn: api.retryFailedImportJobs,
    onSuccess: (result) => {
      retryFailedFeedback.showSuccess();
      setQueueActionMessage(describeQueueAction("Retried", result));
      refreshQueueData();
    },
    onError: (error) => {
      retryFailedFeedback.showError(actionFailureMessage("Could not retry failed imports", error));
    },
  });
  const clearQueue = useMutation({
    mutationFn: api.clearImportQueue,
    onSuccess: (result) => {
      clearQueueFeedback.showSuccess();
      setQueueActionMessage(describeQueueAction("Cleared", result));
      refreshQueueData();
    },
    onError: (error) => {
      clearQueueFeedback.showError(actionFailureMessage("Could not clear import queue", error));
    },
  });
  const clearFailedJobs = useMutation({
    mutationFn: api.clearFailedImportJobs,
    onSuccess: (result) => {
      clearFailedFeedback.showSuccess();
      setQueueActionMessage(describeQueueAction("Cleared failed", result));
      refreshQueueData();
    },
    onError: (error) => {
      clearFailedFeedback.showError(actionFailureMessage("Could not clear failed imports", error));
    },
  });
  const bulkActionBusy =
    processStagedUploads.isPending ||
    retryFailedJobs.isPending ||
    clearQueue.isPending ||
    clearFailedJobs.isPending ||
    rescueJob.isPending ||
    cancelJob.isPending;
  const queueStatusText = queueActionMessage
    || (queueJobs.length
      ? `${queueJobs.length} active or waiting; ${importQueueEstimateLabel(costPreviewQueueJobs)}`
      : "No import jobs waiting");

  return (
    <section className="workbench queue-workbench">
      <section className="queue-panel">
        <div className="panel-title-row">
          <div>
            <h2>Import Queue</h2>
            <span>{queueStatusText}</span>
          </div>
          <div className="queue-title-actions">
            <AsyncActionSlot busy={processStagedUploads.isPending} feedback={processUploadsFeedback.feedback} label="Process uploads in progress">
              <button
                className={asyncFeedbackClass("primary-button compact", processUploadsFeedback.feedback, processStagedUploads.isPending)}
                data-disabled-reason={bulkActionBusy ? "another queue action is already running." : "there are no staged uploads ready to process."}
                data-tooltip="Start all staged uploads through the import processing pipeline."
                disabled={!stagedQueueJobs.length || bulkActionBusy}
                onClick={() => processStagedUploads.mutate()}
                type="button"
              >
                <Play className={processStagedUploads.isPending ? "spin" : ""} size={15} />
                Process Uploads
              </button>
            </AsyncActionSlot>
            <AsyncActionSlot busy={retryFailedJobs.isPending} feedback={retryFailedFeedback.feedback} label="Retry failed imports in progress">
              <button
                className={asyncFeedbackClass("secondary-button compact", retryFailedFeedback.feedback, retryFailedJobs.isPending)}
                data-disabled-reason={bulkActionBusy ? "another queue action is already running." : "there are no failed import jobs to retry."}
                data-tooltip="Retry every failed import job that still has a document record."
                disabled={!failedQueueJobs.length || bulkActionBusy}
                onClick={() => retryFailedJobs.mutate()}
                type="button"
              >
                <RefreshCw className={retryFailedJobs.isPending ? "spin" : ""} size={15} />
                Retry Failed
              </button>
            </AsyncActionSlot>
            <AsyncActionSlot busy={clearQueue.isPending} feedback={clearQueueFeedback.feedback} label="Clear import queue in progress">
              <button
                className={asyncFeedbackClass("secondary-button compact", clearQueueFeedback.feedback, clearQueue.isPending)}
                data-disabled-reason={bulkActionBusy ? "another queue action is already running." : "there are no clearable staged, queued, failed, or restored import jobs."}
                data-tooltip="Move all clearable staged, queued, failed, or restored import jobs to the cleared terminal state."
                disabled={!clearableQueueJobs.length || bulkActionBusy}
                onClick={() => clearQueue.mutate()}
                type="button"
              >
                <Eraser size={15} />
                Clear
              </button>
            </AsyncActionSlot>
            <AsyncActionSlot busy={clearFailedJobs.isPending} feedback={clearFailedFeedback.feedback} label="Clear failed imports in progress">
              <button
                className={asyncFeedbackClass("secondary-button compact", clearFailedFeedback.feedback, clearFailedJobs.isPending)}
                data-disabled-reason={bulkActionBusy ? "another queue action is already running." : "there are no failed import jobs to clear."}
                data-tooltip="Move all failed import jobs to the cleared terminal state."
                disabled={!failedQueueJobs.length || bulkActionBusy}
                onClick={() => clearFailedJobs.mutate()}
                type="button"
              >
                <X size={15} />
                Clear Failed
              </button>
            </AsyncActionSlot>
            <Inbox size={20} />
          </div>
        </div>
        <div className="queue-job-list">
          {queueJobs.map((job) => {
            const cancelDisabled = !canCancelImportJob(job) || bulkActionBusy;
            const cancelFeedbackForJob = cancelFeedback.feedbackFor(job.id);
            const retryFeedback = rescueFeedback.feedbackFor(job.id);
            const retryDisabled = !canRetryImportJob(job) || bulkActionBusy;
            return (
              <ImportJobRow
                key={job.id}
                job={job}
                cancelBusy={cancelJob.isPending}
                cancelDisabled={cancelDisabled}
                cancelFeedback={cancelFeedbackForJob}
                cancelTitle={importJobCancelTitle(job)}
                onCancel={() => cancelJob.mutate(job.id)}
                onRetry={() => rescueJob.mutate(job.id)}
                retryBusy={rescueJob.isPending}
                retryDisabled={retryDisabled}
                retryFeedback={retryFeedback}
                retryTitle={importJobRetryTitle(job)}
                showCancelSlot
                showRetrySlot
              />
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
                    data-disabled-reason="a citation review update is already saving."
                    data-tooltip="Accept this citation candidate, apply it to the document, mark the citation verified, and record document history."
                    disabled={updateCandidate.isPending}
                    onClick={() => updateCandidate.mutate({ id: item.id, status: "accepted", apply: true })}
                  >
                    <CheckCircle2 size={16} />
                    Accept
                  </button>
                  <button
                    className="secondary-button"
                    data-disabled-reason="a citation review update is already saving."
                    data-tooltip="Reject this citation candidate and remove it from active review without changing the document."
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
          <input data-tooltip="Type the note title." value={draft.title} onChange={(event) => setDraftValue("title", event.target.value)} placeholder="Note title" />
          <button
            className="primary-button"
            data-disabled-reason={createNote.isPending ? "a note create request is already running." : "both note title and body are required."}
            data-tooltip="Create this note or reminder with the selected document, domain, project, and reminder attachments."
            disabled={!draft.title?.trim() || !draft.body?.trim() || createNote.isPending}
            type="submit"
          >
            <Plus size={16} />
            Add
          </button>
        </div>
        <textarea data-tooltip="Type the note body; document-linked note text contributes to document search." value={draft.body} onChange={(event) => setDraftValue("body", event.target.value)} placeholder="Note body" />
        <div className="note-link-grid">
          <label>
            Kind
            <select data-tooltip="Choose whether this entry is a note, reminder, question, or idea." value={draft.kind || "note"} onChange={(event) => setDraftValue("kind", event.target.value)}>
              <option value="note">Note</option>
              <option value="reminder">Reminder</option>
              <option value="question">Question</option>
              <option value="idea">Idea</option>
            </select>
          </label>
          <label>
            Document
            <select data-tooltip="Optionally attach this note to a document." value={draft.document_id || ""} onChange={(event) => setDraftValue("document_id", event.target.value || null)}>
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
            <select data-tooltip="Optionally attach this note to a domain." value={draft.domain_id || ""} onChange={(event) => setDraftValue("domain_id", event.target.value || null)}>
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
            <select data-tooltip="Optionally attach this note to a project." value={draft.project_id || ""} onChange={(event) => setDraftValue("project_id", event.target.value || null)}>
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
              data-tooltip="Optionally set the reminder date and time for this note."
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
              <button className="icon-button" data-tooltip={`Delete the note titled ${note.title}.`} onClick={() => deleteNote.mutate(note.id)}>
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
  useEscapeLayer(visible, () => setVisible(false), ESCAPE_PRIORITY_TOOLTIP);

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
          data-escape-layer="tooltip"
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

type AppTooltipState = {
  key: number;
  left: number;
  placement: "above" | "below";
  ready: boolean;
  text: string;
  top: number;
};

function AppTooltipProvider({ children }: { children: ReactNode }) {
  const tooltipRef = useRef<HTMLSpanElement | null>(null);
  const anchorRef = useRef<HTMLElement | null>(null);
  const activeTextRef = useRef("");
  const delayTimerRef = useRef<number | null>(null);
  const tooltipKeyRef = useRef(0);
  const [tooltip, setTooltip] = useState<AppTooltipState | null>(null);

  const clearDelayTimer = useCallback(() => {
    if (delayTimerRef.current !== null) {
      window.clearTimeout(delayTimerRef.current);
      delayTimerRef.current = null;
    }
  }, []);

  const hideTooltip = useCallback(() => {
    clearDelayTimer();
    anchorRef.current = null;
    activeTextRef.current = "";
    setTooltip(null);
  }, [clearDelayTimer]);

  const updatePosition = useCallback(() => {
    const anchor = anchorRef.current;
    const tooltipElement = tooltipRef.current;
    if (!anchor || !tooltipElement || !anchor.isConnected) {
      hideTooltip();
      return;
    }

    const viewportMargin = 12;
    const gap = 8;
    const anchorRect = anchor.getBoundingClientRect();
    const tooltipRect = tooltipElement.getBoundingClientRect();
    const tooltipWidth = Math.min(tooltipRect.width, window.innerWidth - viewportMargin * 2);
    const desiredLeft = anchorRect.left + anchorRect.width / 2 - tooltipWidth / 2;
    const left = Math.min(
      Math.max(desiredLeft, viewportMargin),
      Math.max(viewportMargin, window.innerWidth - tooltipWidth - viewportMargin),
    );
    const aboveTop = anchorRect.top - tooltipRect.height - gap;
    const belowTop = anchorRect.bottom + gap;
    const fitsAbove = aboveTop >= viewportMargin;
    const fitsBelow = belowTop + tooltipRect.height <= window.innerHeight - viewportMargin;
    const placement = fitsAbove || !fitsBelow ? "above" : "below";
    const rawTop = placement === "above" ? aboveTop : belowTop;
    const maxTop = Math.max(viewportMargin, window.innerHeight - tooltipRect.height - viewportMargin);
    const top = Math.min(Math.max(rawTop, viewportMargin), maxTop);

    setTooltip((current) => (current ? { ...current, left, placement, ready: true, top } : current));
  }, [hideTooltip]);

  const scheduleTooltip = useCallback(
    (anchor: HTMLElement, text: string) => {
      if (anchorRef.current === anchor && activeTextRef.current === text) return;
      clearDelayTimer();
      anchorRef.current = anchor;
      activeTextRef.current = text;
      setTooltip(null);
      delayTimerRef.current = window.setTimeout(() => {
        if (anchorRef.current !== anchor || activeTextRef.current !== text || !anchor.isConnected) return;
        setTooltip({
          key: ++tooltipKeyRef.current,
          left: 0,
          placement: "above",
          ready: false,
          text,
          top: 0,
        });
      }, APP_TOOLTIP_DELAY_MS);
    },
    [clearDelayTimer],
  );

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      const anchor = tooltipCandidateFromPoint(event.clientX, event.clientY);
      if (!anchor) {
        hideTooltip();
        return;
      }
      const text = tooltipTextForElement(anchor);
      if (!text) {
        hideTooltip();
        return;
      }
      scheduleTooltip(anchor, text);
    };
    const handleFocusIn = (event: FocusEvent) => {
      const anchor = tooltipCandidateFromElement(event.target as Element | null);
      if (!anchor) return;
      const text = tooltipTextForElement(anchor);
      if (text) scheduleTooltip(anchor, text);
    };
    const handleFocusOut = () => hideTooltip();

    window.addEventListener("pointermove", handlePointerMove, true);
    window.addEventListener("pointerdown", hideTooltip, true);
    window.addEventListener("blur", hideTooltip);
    window.addEventListener("scroll", hideTooltip, true);
    document.addEventListener("focusin", handleFocusIn, true);
    document.addEventListener("focusout", handleFocusOut, true);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove, true);
      window.removeEventListener("pointerdown", hideTooltip, true);
      window.removeEventListener("blur", hideTooltip);
      window.removeEventListener("scroll", hideTooltip, true);
      document.removeEventListener("focusin", handleFocusIn, true);
      document.removeEventListener("focusout", handleFocusOut, true);
      clearDelayTimer();
    };
  }, [clearDelayTimer, hideTooltip, scheduleTooltip]);

  useEffect(() => {
    if (!tooltip) return undefined;
    const frame = window.requestAnimationFrame(updatePosition);
    window.addEventListener("resize", updatePosition);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", updatePosition);
    };
  }, [tooltip?.key, updatePosition]);

  useEscapeLayer(Boolean(tooltip), hideTooltip, ESCAPE_PRIORITY_TOOLTIP);

  return (
    <>
      {children}
      {tooltip ? (
        <span
          className="app-tooltip info-popover-tooltip"
          data-escape-layer="tooltip"
          data-placement={tooltip.placement}
          data-ready={tooltip.ready ? "true" : "false"}
          ref={tooltipRef}
          role="tooltip"
          style={{ left: tooltip.left, top: tooltip.top }}
        >
          {tooltip.text}
        </span>
      ) : null}
    </>
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
  useEscapeLayer(open, () => setOpen(false), ESCAPE_PRIORITY_MENU);

  return (
    <div
      className="model-select"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
      <button
        aria-expanded={open}
        aria-haspopup="listbox"
        className="model-select-trigger"
        data-tooltip={`Open the model dropdown. Current selection: ${modelDisplayName(value)}.`}
        type="button"
        onClick={() => setOpen((current) => !current)}
      >
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
                      data-tooltip={`Use ${modelDisplayName(option)} for this model preference.`}
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
                  data-tooltip={`Use ${modelDisplayName(option)} for this model preference.`}
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

const BUDGET_CHART_COLORS = ["#2563eb", "#0f9f8d", "#b87503", "#7c3aed", "#ba2f36", "#64748b", "#22c55e"];

function positiveBudgetValue(value?: number | null) {
  return Number.isFinite(value) ? Math.max(0, value || 0) : 0;
}

function formatBudgetShare(value: number, total: number) {
  if (!total || value <= 0) return "0%";
  const percent = (value / total) * 100;
  if (percent > 0 && percent < 1) return "<1%";
  return `${percent < 10 ? percent.toFixed(1) : percent.toFixed(0)}%`;
}

function budgetPieGradient(segments: BudgetChartSegment[]) {
  const total = segments.reduce((sum, segment) => sum + positiveBudgetValue(segment.value), 0);
  if (!total) return "conic-gradient(var(--line) 0 100%)";
  let cursor = 0;
  const stops = segments.map((segment) => {
    const start = cursor;
    cursor += (positiveBudgetValue(segment.value) / total) * 100;
    return `${segment.color} ${start}% ${cursor}%`;
  });
  return `conic-gradient(${stops.join(", ")})`;
}

function budgetSegments(
  rows: OpenAIUsageGroup[],
  valueFor: (row: OpenAIUsageGroup) => number,
  labelFor: (row: OpenAIUsageGroup) => string,
  displayFor: (value: number) => string,
) {
  const sorted = rows
    .map((row, index) => ({
      key: row.group_key || row.model || row.task_key || row.document_id || `segment-${index}`,
      label: labelFor(row),
      value: positiveBudgetValue(valueFor(row)),
    }))
    .filter((segment) => segment.value > 0)
    .sort((left, right) => right.value - left.value);
  const visible = sorted.slice(0, 5);
  const otherValue = sorted.slice(5).reduce((sum, segment) => sum + segment.value, 0);
  const baseSegments = otherValue > 0 ? [...visible, { key: "other", label: "Other", value: otherValue }] : visible;
  const total = baseSegments.reduce((sum, segment) => sum + segment.value, 0);
  return baseSegments.map((segment, index) => ({
    ...segment,
    color: BUDGET_CHART_COLORS[index % BUDGET_CHART_COLORS.length],
    displayValue: displayFor(segment.value),
    shareLabel: formatBudgetShare(segment.value, total),
  }));
}

function budgetTrendLabel(row: OpenAIUsageGroup, period: OpenAIUsagePeriod) {
  const timestamp = row.calendar_start ? Date.parse(row.calendar_start) : NaN;
  if (!Number.isFinite(timestamp)) return row.group_key || "Unknown";
  const date = new Date(timestamp);
  if (period === "last_day") return date.toLocaleTimeString([], { hour: "numeric" });
  return date.toLocaleDateString([], { day: "numeric", month: "short" });
}

function budgetTrendPoints(rows: OpenAIUsageGroup[], period: OpenAIUsagePeriod) {
  return rows
    .map((row, index) => {
      const timestamp = row.calendar_start ? Date.parse(row.calendar_start) : NaN;
      return {
        key: row.group_key || row.calendar_start || `trend-${index}`,
        label: budgetTrendLabel(row, period),
        sortValue: Number.isFinite(timestamp) ? timestamp : index,
        value: positiveBudgetValue(row.estimated_cost_usd),
      };
    })
    .sort((left, right) => left.sortValue - right.sortValue);
}

function budgetTrendSubtitle(period: OpenAIUsagePeriod) {
  if (period === "last_day") return "Hourly estimated cost";
  return "Daily estimated cost";
}

function budgetRecentCost(row: { estimated_cost_usd?: number | null }) {
  return row.estimated_cost_usd === undefined || row.estimated_cost_usd === null ? "Unpriced" : formatUsd(row.estimated_cost_usd);
}

function budgetRecentLabel(row: { page_number?: number | null; task_key: string }) {
  const task = row.task_key || "unknown";
  return row.page_number ? `${task.replaceAll("_", " ")} p.${row.page_number}` : task.replaceAll("_", " ");
}

function BudgetPiePanel({
  emptyLabel,
  segments,
  subtitle,
  title,
  totalLabel,
}: {
  emptyLabel: string;
  segments: BudgetChartSegment[];
  subtitle: string;
  title: string;
  totalLabel: string;
}) {
  return (
    <section className="budget-chart-panel">
      <div className="budget-chart-head">
        <div>
          <h3>{title}</h3>
          <span>{subtitle}</span>
        </div>
        <strong>{totalLabel}</strong>
      </div>
      <div className="budget-pie-wrap">
        <div className="budget-pie" style={{ background: budgetPieGradient(segments) }}>
          <span>{totalLabel}</span>
        </div>
        <div className="budget-chart-legend">
          {segments.length ? (
            segments.map((segment) => (
              <div className="budget-chart-legend-row" key={segment.key}>
                <i style={{ background: segment.color }} />
                <span>{segment.label}</span>
                <strong>{segment.displayValue}</strong>
                <em>{segment.shareLabel}</em>
              </div>
            ))
          ) : (
            <span className="budget-chart-empty">{emptyLabel}</span>
          )}
        </div>
      </div>
    </section>
  );
}

function BudgetTrendChart({ period, rows }: { period: OpenAIUsagePeriod; rows: OpenAIUsageGroup[] }) {
  const points = budgetTrendPoints(rows, period);
  const maxValue = Math.max(0, ...points.map((point) => point.value));
  const latestPoint = points[points.length - 1];
  const peakPoint = points.reduce<(typeof points)[number] | undefined>(
    (selected, point) => (!selected || point.value > selected.value ? point : selected),
    undefined,
  );
  const chartWidth = 640;
  const chartHeight = 188;
  const left = 18;
  const right = 622;
  const top = 18;
  const bottom = 150;
  const innerWidth = right - left;
  const innerHeight = bottom - top;
  const coordinates = points.map((point, index) => {
    const x = points.length <= 1 ? chartWidth / 2 : left + (index / (points.length - 1)) * innerWidth;
    const y = maxValue > 0 ? bottom - (point.value / maxValue) * innerHeight : bottom;
    return { ...point, x, y };
  });
  const linePoints = coordinates.map((point) => `${point.x},${point.y}`).join(" ");
  const areaPath = coordinates.length
    ? `M ${coordinates[0].x} ${bottom} L ${coordinates.map((point) => `${point.x} ${point.y}`).join(" L ")} L ${coordinates[coordinates.length - 1].x} ${bottom} Z`
    : "";
  const firstLabel = points[0]?.label || "";
  const lastLabel = latestPoint?.label || "";
  const peakLabel = peakPoint ? `${formatUsd(peakPoint.value)} peak` : "No peak";

  return (
    <section className="budget-chart-panel budget-trend-panel">
      <div className="budget-chart-head">
        <div>
          <h3>Cost Trend</h3>
          <span>{budgetTrendSubtitle(period)}</span>
        </div>
        <strong>{formatUsd(latestPoint?.value ?? 0)}</strong>
      </div>
      {maxValue > 0 ? (
        <div className="budget-trend-body">
          <svg className="budget-trend-svg" role="img" aria-label={`${budgetTrendSubtitle(period)} trend line`} viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="none">
            {[0, 0.5, 1].map((tick) => {
              const y = bottom - tick * innerHeight;
              return <line className="budget-trend-grid-line" key={tick} x1={left} x2={right} y1={y} y2={y} />;
            })}
            <path className="budget-trend-area" d={areaPath} />
            {coordinates.length > 1 ? <polyline className="budget-trend-line" points={linePoints} /> : null}
            {coordinates.length === 1 ? <circle className="budget-trend-point" cx={coordinates[0].x} cy={coordinates[0].y} r="4" /> : null}
            {coordinates.length > 1 && coordinates.length <= 24
              ? coordinates.map((point) => <circle className="budget-trend-point" key={point.key} cx={point.x} cy={point.y} r="3" />)
              : null}
          </svg>
          <div className="budget-trend-axis">
            <span>{firstLabel}</span>
            <strong>{peakLabel}</strong>
            <span>{lastLabel}</span>
          </div>
        </div>
      ) : (
        <div className="budget-trend-empty">
          <span>No priced cost recorded</span>
        </div>
      )}
    </section>
  );
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
  const trendRows = period === "last_day" ? usage.data?.by_calendar_hour || [] : usage.data?.by_calendar_day || [];
  const recentRows = usage.data?.recent || [];
  const costByModelSegments = budgetSegments(
    usage.data?.by_model || [],
    (row) => row.estimated_cost_usd,
    (row) => budgetRowLabel(row, "model"),
    (value) => formatUsd(value),
  );
  const tokensByTaskSegments = budgetSegments(
    usage.data?.by_task || [],
    (row) => row.total_tokens,
    (row) => budgetRowLabel(row, "task"),
    (value) => `${formatMetric(value)} tokens`,
  );

  return (
    <section className="workbench budget-view">
      <div className="budget-panel">
        <div className="budget-command-surface">
          <div className="panel-title-row">
            <div>
              <h2>Budget & Costs</h2>
              <span>{summary ? `${formatMetric(summary.request_count)} recorded calls` : usage.isFetching ? "Loading usage" : "No recorded calls"}</span>
            </div>
            <CircleDollarSign size={20} />
          </div>
          <div className="budget-controls">
            <label>
              Period
              <select data-tooltip="Choose the time window used for Budget & Costs usage totals and rollups." value={period} onChange={(event) => setPeriod(event.target.value as OpenAIUsagePeriod)}>
                {USAGE_PERIOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Metric
              <select data-tooltip="Choose whether Budget & Costs tables show tokens, estimated cost, or both." value={metricMode} onChange={(event) => setMetricMode(event.target.value as BudgetMetricMode)}>
                <option value="tokens_cost">Tokens + cost</option>
                <option value="tokens">Tokens</option>
                <option value="cost">Cost</option>
              </select>
            </label>
            <label>
              Group
              <select data-tooltip="Choose how Budget & Costs usage rows are grouped." value={groupMode} onChange={(event) => setGroupMode(event.target.value as BudgetGroupMode)}>
                <option value="model">By model</option>
                <option value="task">By task</option>
                <option value="document">By document</option>
                <option value="day">By calendar day</option>
                <option value="hour">By calendar hour</option>
              </select>
            </label>
          </div>
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
        <div className="budget-chart-grid">
          <BudgetTrendChart period={period} rows={trendRows} />
          <BudgetPiePanel
            emptyLabel="No priced model spend recorded."
            segments={costByModelSegments}
            subtitle="Estimated cost by model"
            title="Cost By Model"
            totalLabel={formatUsd(summary?.estimated_cost_usd ?? 0)}
          />
          <BudgetPiePanel
            emptyLabel="No token usage recorded."
            segments={tokensByTaskSegments}
            subtitle="Total tokens by task"
            title="Tokens By Task"
            totalLabel={formatMetric(summary?.total_tokens)}
          />
        </div>
        <div className="budget-lower-grid">
          <section className="budget-detail-panel">
            <div className="budget-section-head">
              <div>
                <h3>{budgetGroupHeader(groupMode)} Rollup</h3>
                <span>{rows.length ? `${formatMetric(rows.length)} rows in selected period` : "No matching usage"}</span>
              </div>
              <Gauge size={18} />
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
          </section>
          <section className="budget-recent-panel">
            <div className="budget-section-head">
              <div>
                <h3>Recent Calls</h3>
                <span>{recentRows.length ? "Latest ledger entries" : "No recent calls"}</span>
              </div>
              <List size={18} />
            </div>
            <div className="budget-recent-list">
              {recentRows.length ? (
                recentRows.slice(0, 7).map((row) => (
                  <div className="budget-recent-row" key={row.id}>
                    <div>
                      <strong>{budgetRecentLabel(row)}</strong>
                      <span>{row.model || "unknown model"}</span>
                    </div>
                    <StatusPill value={row.status} tone={row.status === "failed" ? "warn" : "good"} />
                    <em>{budgetRecentCost(row)}</em>
                  </div>
                ))
              ) : (
                <div className="empty-inline">
                  <Info size={16} />
                  <span>No recent AI usage recorded.</span>
                </div>
              )}
            </div>
          </section>
        </div>
        <div className="budget-footnote">
          <span>{usage.data?.pricing.updated_at ? `Pricing ${usage.data.pricing.updated_at}` : "Pricing"}</span>
          {usage.data?.pricing.source_url ? (
            <a data-tooltip="Open the OpenAI pricing source used for these local estimates in a new tab." href={usage.data.pricing.source_url} rel="noreferrer" target="_blank">
              OpenAI
              <ExternalLink size={12} />
            </a>
          ) : null}
          {usage.data?.pricing.source_urls?.Google ? (
            <a data-tooltip="Open the Google pricing source used for these local estimates in a new tab." href={usage.data.pricing.source_urls.Google} rel="noreferrer" target="_blank">
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
  backupRuns,
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
  onDirtyChange,
  onRegisterSave,
  query,
}: {
  backupRuns: BackupRun[];
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
  onDirtyChange?: (dirty: boolean) => void;
  onRegisterSave?: (handler: SettingsSaveHandler | null) => void;
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
  const [documentCacheSizeMb, setDocumentCacheSizeMb] = useState(preferences?.document_cache_size_mb || 1024);
  const [libraryAlternatingRows, setLibraryAlternatingRows] = useState(preferences?.library_alternating_rows ?? true);
  const [downloadNamingTemplate, setDownloadNamingTemplate] = useState(preferences?.download_naming_template || "$title ($year)");
  const [citationConvention, setCitationConvention] = useState(preferences?.citation_convention || CITATION_CONVENTION_APA_7);
  const [gcsBucket, setGcsBucket] = useState(preferences?.gcs_bucket || "");
  const [analysisModels, setAnalysisModels] = useState<Record<string, string>>(preferences?.analysis_models || {});
  const [selectedCapabilityKeys, setSelectedCapabilityKeys] = useState<string[]>([]);
  const [selectedBackupUri, setSelectedBackupUri] = useState("");
  const serviceAccountInputRef = useRef<HTMLInputElement | null>(null);
  const completedBackupArtifactIdsRef = useRef<Set<string>>(new Set());
  const completedBackupArtifactIdsInitializedRef = useRef(false);
  const queryClient = useQueryClient();
  const createRunFeedback = useAsyncActionFeedback();
  const savePreferencesFeedback = useAsyncActionFeedback();
  const serviceAccountUploadFeedback = useAsyncActionFeedback();
  const backupFeedback = useAsyncActionFeedback();
  const restoreFeedback = useAsyncActionFeedback({ errorMs: 9000 });
  const activeBackupRun = backupRuns.find((run) => run.status === "queued" || run.status === "running");
  const gcsBackupArtifacts = useQuery({
    queryKey: ["gcs-backups"],
    queryFn: api.gcsBackups,
    enabled: Boolean(preferences?.gcs_bucket),
    refetchInterval: 15000,
    retry: false,
  });
  const backupEstimate = useQuery({
    queryKey: ["backup-estimate"],
    queryFn: api.backupEstimate,
    enabled: Boolean(preferences),
    refetchInterval: activeBackupRun ? 4000 : 30000,
    retry: false,
  });
  const documentCacheStatus = useQuery({
    queryKey: ["document-cache-status"],
    queryFn: api.documentCacheStatus,
    enabled: Boolean(preferences),
    refetchInterval: 10000,
  });

  useEffect(() => {
    if (preferences) {
      setImportWorkerConcurrency(preferences.import_worker_concurrency);
      setAccentColorDay(preferences.accent_color_day);
      setAccentColorNight(preferences.accent_color_night);
      setDocumentCacheSizeMb(preferences.document_cache_size_mb);
      setLibraryAlternatingRows(preferences.library_alternating_rows);
      setDownloadNamingTemplate(preferences.download_naming_template);
      setCitationConvention(preferences.citation_convention || CITATION_CONVENTION_APA_7);
      setGcsBucket(preferences.gcs_bucket);
      setAnalysisModels(preferences.analysis_models);
    }
  }, [preferences]);

  useEffect(() => {
    setSelectedCapabilityKeys((current) => (current.length ? current : capabilities.map((capability) => capability.key)));
  }, [capabilities]);

  useEffect(() => {
    const artifacts = gcsBackupArtifacts.data || [];
    if (!artifacts.length && selectedBackupUri) setSelectedBackupUri("");
    if (!selectedBackupUri && artifacts.length) setSelectedBackupUri(artifacts[0].gcs_uri);
    if (selectedBackupUri && artifacts.length && !artifacts.some((artifact) => artifact.gcs_uri === selectedBackupUri)) {
      setSelectedBackupUri(artifacts[0].gcs_uri);
    }
  }, [gcsBackupArtifacts.data, selectedBackupUri]);

  useEffect(() => {
    const completedBackupIds = backupRuns
      .filter((run) => run.kind === "backup" && run.status === "complete" && run.gcs_uri)
      .map((run) => run.id);
    const seen = completedBackupArtifactIdsRef.current;
    const hasNewCompletedBackup = completedBackupIds.some((id) => !seen.has(id));
    completedBackupIds.forEach((id) => seen.add(id));
    if (!completedBackupArtifactIdsInitializedRef.current) {
      completedBackupArtifactIdsInitializedRef.current = true;
      return;
    }
    if (hasNewCompletedBackup) {
      void queryClient.invalidateQueries({ queryKey: ["gcs-backups"] });
      void queryClient.invalidateQueries({ queryKey: ["backup-estimate"] });
    }
  }, [backupRuns, queryClient]);

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
        download_naming_template: downloadNamingTemplate,
        citation_convention: citationConvention,
        gcs_bucket: gcsBucket,
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
  const saveAllPreferences = useCallback(async () => {
    try {
      await savePreferences.mutateAsync();
      return true;
    } catch {
      return false;
    }
  }, [savePreferences]);
  const uploadServiceAccount = useMutation({
    mutationFn: (file: File) => api.uploadGoogleServiceAccount(file),
    onSuccess: (updatedPreferences) => {
      serviceAccountUploadFeedback.showSuccess();
      queryClient.setQueryData(["preferences"], updatedPreferences);
      void queryClient.invalidateQueries({ queryKey: ["preferences"] });
      if (serviceAccountInputRef.current) serviceAccountInputRef.current.value = "";
    },
    onError: (error) => {
      serviceAccountUploadFeedback.showError(actionFailureMessage("Could not upload service account", error));
      if (serviceAccountInputRef.current) serviceAccountInputRef.current.value = "";
    },
  });
  const startBackup = useMutation({
    mutationFn: api.startDatabaseBackup,
    onSuccess: () => {
      backupFeedback.showSuccess();
      void queryClient.invalidateQueries({ queryKey: ["backup-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["backup-estimate"] });
      void queryClient.invalidateQueries({ queryKey: ["gcs-backups"] });
    },
    onError: (error) => {
      backupFeedback.showError(actionFailureMessage("Could not start backup", error));
    },
  });
  const startRestore = useMutation({
    mutationFn: () => api.startDatabaseRestore(selectedBackupUri),
    onSuccess: () => {
      restoreFeedback.showSuccess();
      void queryClient.invalidateQueries({ queryKey: ["backup-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["backup-estimate"] });
      void queryClient.invalidateQueries({ queryKey: ["gcs-backups"] });
    },
    onError: (error) => {
      restoreFeedback.showError(actionFailureMessage("Could not start restore", error));
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
        preferences.download_naming_template !== downloadNamingTemplate ||
        preferences.citation_convention !== citationConvention ||
        preferences.gcs_bucket !== gcsBucket ||
        (Boolean(gcsBucket.trim()) && !preferences.gcs_bucket_saved) ||
        !sameStringMap(preferences.analysis_models, analysisModels)),
  );
  useEffect(() => {
    onDirtyChange?.(preferenceDirty);
  }, [onDirtyChange, preferenceDirty]);

  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

  useEffect(() => {
    onRegisterSave?.(preferenceDirty ? saveAllPreferences : null);
    return () => onRegisterSave?.(null);
  }, [onRegisterSave, preferenceDirty, saveAllPreferences]);

  const importCostWarning = importWorkerConcurrency > warningThreshold;
  const currentDocumentCacheSizeMb = documentCacheStatus.data?.current_size_mb;
  const currentDocumentCacheSizeLabel =
    typeof currentDocumentCacheSizeMb === "number" ? `${formatMetric(currentDocumentCacheSizeMb)} MB` : "... MB";
  const savePreferencesDisabled = !preferences || !preferenceDirty || savePreferences.isPending;
  const serviceAccountName =
    preferences?.google_service_account_name || "None, please upload a service account JSON";
  const serviceAccountStatus =
    preferences?.google_service_account_source === "uploaded" ? "Uploaded" : "Missing";
  const backupArtifacts = gcsBackupArtifacts.data || [];
  const latestBackupRun = backupRuns[0];
  const backupHistoryRuns = backupRuns.slice(0, 10);
  const latestVerifiedBackupRun = backupRuns.find((run) => run.kind === "backup" && run.status === "complete" && run.gcs_uri);
  const verifiedBackupComplete = Boolean(latestVerifiedBackupRun);
  const verifiedBackupFilename = verifiedBackupComplete ? latestVerifiedBackupRun?.filename || "Complete" : "Waiting";
  const verifiedBackupSize = verifiedBackupComplete ? formatFileSize(latestVerifiedBackupRun?.size_bytes) : "";
  const backupArtifactTotalBytes = backupArtifacts.reduce((total, artifact) => total + Math.max(0, artifact.size_bytes || 0), 0);
  const backupArtifactTotalSize = formatFileSize(backupArtifactTotalBytes) || "0 B";
  const backupArtifactCountLabel = gcsBackupArtifacts.isFetching && !backupArtifacts.length
    ? "Calculating"
    : backupArtifacts.length
      ? `${formatMetric(backupArtifacts.length)} ${backupArtifacts.length === 1 ? "backup" : "backups"}`
      : preferences?.gcs_bucket
        ? "No backups"
        : "No bucket";
  const backupDisabled = !preferences?.gcs_bucket || Boolean(activeBackupRun) || startBackup.isPending;
  const restoreDisabled = Boolean(activeBackupRun) || startRestore.isPending || !selectedBackupUri;
  const savePreferencesDisabledReason = !preferences
    ? "preferences are still loading."
    : savePreferences.isPending
      ? "Save All is already writing preferences."
      : !preferenceDirty
        ? "there are no unsaved preference changes."
        : "";
  const createRunDisabledReason = createRun.isPending
    ? "a Concordance Run request is already starting."
    : !scopeReady
      ? "the selected Concordance scope needs a document, search, saved search, domain, or project."
      : !selectedCapabilityKeys.length
        ? "at least one Concordance capability must be selected."
        : "";
  const backupDisabledReason = startBackup.isPending
    ? "a database backup request is already starting."
    : activeBackupRun
      ? "a backup or restore is already running."
      : !preferences?.gcs_bucket
        ? "a GCS bucket must be saved before browser backups can start."
        : "";
  const restoreDisabledReason = startRestore.isPending
    ? "a database restore request is already starting."
    : activeBackupRun
      ? "a backup or restore is already running."
      : !selectedBackupUri
        ? "a GCS backup must be selected."
        : "";
  const handleServiceAccountUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) uploadServiceAccount.mutate(file);
  };
  const confirmDatabaseRestore = () => {
    if (!selectedBackupUri) return;
    const artifact = backupArtifacts.find((item) => item.gcs_uri === selectedBackupUri);
    const restoreLabel = artifact ? backupArtifactLabel(artifact) : selectedBackupUri;
    const ok = window.confirm(
      `Restore the database from ${restoreLabel}?\n\nMedusa will first create and verify a fresh safety backup. The selected restore will only run after that safety backup succeeds.`,
    );
    if (ok) startRestore.mutate();
  };
  const renderSaveAllButton = (placement: "top" | "bottom") => (
    <AsyncActionSlot feedback={savePreferencesFeedback.feedback}>
      <button
        aria-label={`Save all preferences from the ${placement} of Settings`}
        className={asyncFeedbackClass("primary-button settings-save-all", savePreferencesFeedback.feedback)}
        data-disabled-reason={savePreferencesDisabledReason}
        data-tooltip={`Save all Settings preferences from the ${placement} Save All control, including storage, display, cache, runtime, accent, citation convention, download naming, and model selections.`}
        disabled={savePreferencesDisabled}
        onClick={() => void saveAllPreferences()}
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
      <div className="storage-settings-panel">
        <div className="panel-title-row">
          <div>
            <h2>Cloud Storage</h2>
            <span>{preferences?.gcs_bucket_saved ? "Saved bucket" : "Current default"}</span>
          </div>
          <Cloud size={20} />
        </div>
        <div className="storage-settings-grid">
          <div className="preference-control">
            <label htmlFor="gcs-bucket">
              <span>GCS bucket</span>
              <strong>{gcsBucket.trim() || "Local fallback"}</strong>
            </label>
            <input
              autoComplete="off"
              data-tooltip="Type the GCS bucket name Medusa should use for future originals, assets, backups, and restores after Save All."
              id="gcs-bucket"
              onChange={(event) => setGcsBucket(event.target.value)}
              placeholder="your-gcs-bucket"
              type="text"
              value={gcsBucket}
            />
            <p>{preferences?.gcs_bucket_saved ? "Saved for future storage operations." : "Save All stores this default."}</p>
          </div>
          <div className="preference-control">
            <label htmlFor="google-service-account-name">
              <span>Service account name</span>
              <strong>{serviceAccountStatus}</strong>
            </label>
            <input
              data-tooltip="Read the currently uploaded Google service account identity or the missing-credential prompt."
              id="google-service-account-name"
              readOnly
              type="text"
              value={serviceAccountName}
            />
            {preferences?.google_service_account_project_id ? (
              <p>Project: {preferences.google_service_account_project_id}</p>
            ) : (
              <p>Upload a JSON key to stop relying on pass-through Google credentials.</p>
            )}
            <AsyncActionSlot feedback={serviceAccountUploadFeedback.feedback}>
              <button
                className={asyncFeedbackClass("secondary-button", serviceAccountUploadFeedback.feedback, uploadServiceAccount.isPending)}
                data-disabled-reason="a service-account JSON upload is already running."
                data-tooltip="Open the file picker to upload a Google service-account JSON key for GCS, Google Vision, and Gemini/Vertex calls."
                disabled={uploadServiceAccount.isPending}
                onClick={() => serviceAccountInputRef.current?.click()}
                type="button"
              >
                <UploadCloud className={uploadServiceAccount.isPending ? "spin" : ""} size={16} />
                {uploadServiceAccount.isPending ? "Uploading" : "Upload JSON"}
              </button>
            </AsyncActionSlot>
            <input
              ref={serviceAccountInputRef}
              accept="application/json,.json"
              className="hidden-file-input"
              disabled={uploadServiceAccount.isPending}
              onChange={handleServiceAccountUpload}
              type="file"
            />
          </div>
        </div>
      </div>
      <div className="preferences-panel">
        <div className="panel-title-row">
          <div>
            <h2>Preferences</h2>
            <span>Display and processing</span>
          </div>
          <SlidersHorizontal size={20} />
        </div>
        <div className="preference-control">
          <label htmlFor="import-worker-concurrency">
            <span>Import workers</span>
          </label>
          <input
            data-tooltip="Set how many import jobs the worker should process concurrently."
            id="import-worker-concurrency"
            min={1}
            onChange={(event) => setImportWorkerConcurrency(Math.max(1, Number(event.target.value) || 1))}
            type="number"
            value={importWorkerConcurrency}
          />
          <p>(Default: 4) Higher values can fan out many OpenAI calls at once, but may incur cost more quickly.</p>
          {importCostWarning ? (
            <p className="preference-warning">Higher concurrency can incur a large OpenAI cost over a short amount of time.</p>
          ) : null}
        </div>
        <div className="preference-control">
          <label htmlFor="document-cache-size">
            <span>Document Cache Size</span>
          </label>
          <input
            data-tooltip="Set the maximum local processing-cache budget in MB for recently completed document PDFs."
            id="document-cache-size"
            min={0}
            onChange={(event) => setDocumentCacheSizeMb(Math.max(0, Number(event.target.value) || 0))}
            type="number"
            value={documentCacheSizeMb}
          />
          <p>(Default: 1024) Local storage before cache rules cause pruning. Current size: {currentDocumentCacheSizeLabel}</p>
        </div>
        <div className="preference-control">
          <label htmlFor="download-naming-template">
            <span>Download Naming</span>
          </label>
          <input
            autoComplete="off"
            data-tooltip="Edit the filename template used when downloading original PDFs."
            id="download-naming-template"
            onChange={(event) => setDownloadNamingTemplate(event.target.value)}
            placeholder="$title ($year)"
            type="text"
            value={downloadNamingTemplate}
          />
          <div className="template-token-row" aria-label="Download naming tokens">
            <code>$title</code>
            <code>$year</code>
            <code>$authors</code>
            <code>$author</code>
            <code>$pages</code>
          </div>
        </div>
        <fieldset className="citation-convention-control">
          <legend>Citation convention</legend>
          <label className="radio-row">
            <input
              checked={citationConvention === CITATION_CONVENTION_APA_7}
              data-tooltip="Use APA seventh edition formatting for generated reference-list and in-text citation output."
              name="citation-convention"
              onChange={(event) => setCitationConvention(event.target.value)}
              type="radio"
              value={CITATION_CONVENTION_APA_7}
            />
            <span>APA (7th Ed.)</span>
          </label>
        </fieldset>
        <label className="checkbox-row preference-checkbox">
          <input
            data-tooltip="Toggle alternating row shading in the Library document list."
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
            <input data-tooltip="Pick the day-mode accent color." type="color" value={accentColorDay} onChange={(event) => setAccentColorDay(event.target.value)} />
          </label>
          <label>
            <span>Night accent</span>
            <span className="accent-swatch" style={{ background: accentColorNight }} />
            <input data-tooltip="Pick the night-mode accent color." type="color" value={accentColorNight} onChange={(event) => setAccentColorNight(event.target.value)} />
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
      <div className="concordance-panel">
        <div className="panel-title-row">
          <div>
            <h2>Concordance Runs</h2>
            <span>{activeJobs} active jobs</span>
          </div>
          <RefreshCw size={20} />
        </div>
        <div className="scope-grid">
          <label>
            Scope
            <select data-tooltip="Choose which library scope the new Concordance Run will upgrade." value={scopeType} onChange={(event) => setScopeType(event.target.value as typeof scopeType)}>
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
              <select data-tooltip="Choose the domain scope for the Concordance Run." value={domainId} onChange={(event) => setDomainId(event.target.value)}>
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
              <select data-tooltip="Choose the project scope for the Concordance Run." value={projectId} onChange={(event) => setProjectId(event.target.value)}>
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
              <select data-tooltip="Choose the saved-search scope for the Concordance Run." value={savedSearchId} onChange={(event) => setSavedSearchId(event.target.value)}>
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
          <input data-tooltip="Force selected Concordance capabilities to rerun even when documents already record current versions." type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
          <span>Force current versions</span>
        </label>
        <div className="capability-picker">
          {capabilities.map((capability) => (
            <label key={capability.key}>
              <input
                data-tooltip={`Toggle the ${capability.label} capability for the next Concordance Run.`}
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
        <div className="concordance-run-actions">
          <AsyncActionSlot busy={createRun.isPending} feedback={createRunFeedback.feedback} label="Concordance Run request in progress">
            <button
              className={asyncFeedbackClass("primary-button", createRunFeedback.feedback, createRun.isPending)}
              data-disabled-reason={createRunDisabledReason}
              data-tooltip="Start a durable Concordance Run for the selected scope and selected capabilities."
              disabled={createRun.isPending || !scopeReady || !selectedCapabilityKeys.length}
              onClick={() => createRun.mutate()}
              type="button"
            >
              <RefreshCw className={createRun.isPending ? "spin" : ""} size={16} />
              {createRun.isPending ? "Starting" : "Start run"}
            </button>
          </AsyncActionSlot>
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
      <div className="database-backup-panel">
        <div className="panel-title-row">
          <div>
            <h2>Database Backup & Restore</h2>
            <span>{activeBackupRun ? `${backupPhaseLabel(activeBackupRun.phase)} - ${activeBackupRun.progress}%` : "Full PostgreSQL backups in GCS"}</span>
          </div>
          <Archive size={20} />
        </div>
        <div className="backup-restore-grid">
          <div className="backup-action-block">
            <div>
              <strong>Backup Database</strong>
              <span>{preferences?.gcs_bucket ? `gs://${preferences.gcs_bucket}` : "Save a GCS bucket first"}</span>
            </div>
            <AsyncActionSlot busy={startBackup.isPending} feedback={backupFeedback.feedback} label="Database backup request in progress">
              <button
                className={asyncFeedbackClass("primary-button", backupFeedback.feedback, startBackup.isPending)}
                data-disabled-reason={backupDisabledReason}
                data-tooltip="Start a full PostgreSQL database backup, compress it, upload it to the configured GCS bucket, and verify the checksum."
                disabled={backupDisabled}
                onClick={() => startBackup.mutate()}
                type="button"
              >
                <Archive className={startBackup.isPending ? "spin" : ""} size={16} />
                {startBackup.isPending ? "Starting" : "Backup Database"}
              </button>
            </AsyncActionSlot>
            <p className="backup-size-estimate">{backupEstimateLabel(backupEstimate.data, backupEstimate.isFetching)}</p>
          </div>
          <div className="restore-action-block">
            <div className="restore-action-heading">
              <strong>Restore Database</strong>
              <span>{backupArtifacts.length ? `${backupArtifactCountLabel} in GCS` : preferences?.gcs_bucket ? "No GCS backups found" : "Save a GCS bucket first"}</span>
            </div>
            <div className="restore-source-grid">
              <label>
                GCS backup
                <select
                  data-disabled-reason={startRestore.isPending ? "a database restore request is already starting." : "no GCS backup artifacts are available."}
                  data-tooltip="Choose the GCS backup artifact to restore from."
                  disabled={!backupArtifacts.length || startRestore.isPending}
                  onChange={(event) => setSelectedBackupUri(event.target.value)}
                  value={selectedBackupUri}
                >
                  {backupArtifacts.length ? (
                    backupArtifacts.map((artifact) => (
                      <option key={artifact.gcs_uri} value={artifact.gcs_uri}>
                        {backupArtifactLabel(artifact)}
                      </option>
                    ))
                  ) : (
                    <option value="">No GCS backups found</option>
                  )}
                </select>
              </label>
              <AsyncActionSlot busy={startRestore.isPending} feedback={restoreFeedback.feedback} label="Database restore request in progress">
                <button
                  className={asyncFeedbackClass("secondary-button", restoreFeedback.feedback, startRestore.isPending)}
                  data-disabled-reason={restoreDisabledReason}
                  data-tooltip="Restore the database from the selected GCS backup after Medusa first creates and verifies a fresh safety backup."
                  disabled={restoreDisabled}
                  onClick={confirmDatabaseRestore}
                  type="button"
                >
                  <RotateCcw className={startRestore.isPending ? "spin" : ""} size={16} />
                  {startRestore.isPending ? "Starting" : "Restore Database"}
                </button>
              </AsyncActionSlot>
            </div>
          </div>
        </div>
        <div className="backup-status-grid">
          <div>
            <span>Latest run</span>
            <strong>{latestBackupRun ? `${latestBackupRun.kind} - ${backupPhaseLabel(latestBackupRun.phase)}` : "None"}</strong>
          </div>
          <div>
            <span>Status</span>
            <strong>{latestBackupRun ? latestBackupRun.status.replaceAll("_", " ") : "Idle"}</strong>
          </div>
          <div>
            <span>Verified backup</span>
            <div className="verified-backup-value">
              <strong>{verifiedBackupFilename}</strong>
              {verifiedBackupSize ? <small>{verifiedBackupSize}</small> : null}
            </div>
          </div>
          <div>
            <span>GCS backups</span>
            <div className="verified-backup-value">
              <strong>{backupArtifactCountLabel}</strong>
              <small>{backupArtifactTotalSize} total</small>
            </div>
          </div>
        </div>
        <div className="backup-history">
          <div className="backup-history-head">
            <strong>Recent history</strong>
            <span>{backupRuns.length ? `${backupHistoryRuns.length} shown from ${backupRuns.length} tracked` : "No backup runs tracked"}</span>
          </div>
          <div className="backup-history-list">
            <div className="backup-history-row header">
              <span>Run</span>
              <span>Status</span>
              <span>When</span>
              <span>Size</span>
            </div>
            {backupHistoryRuns.length ? (
              backupHistoryRuns.map((run) => (
                <div className="backup-history-row" key={run.id}>
                  <span className="backup-history-main">
                    <strong>{backupRunLabel(run)}</strong>
                    <small title={backupRunDetail(run)}>{backupRunDetail(run)}</small>
                  </span>
                  <StatusPill value={run.status} tone={run.status === "failed" ? "warn" : run.status === "complete" ? "good" : "blue"} />
                  <span>{backupRunTimestamp(run) || backupPhaseLabel(run.phase)}</span>
                  <span>{formatFileSize(run.size_bytes) || `${run.progress}%`}</span>
                </div>
              ))
            ) : (
              <div className="backup-history-row empty">
                <span>No backup or restore runs yet</span>
                <span />
                <span />
                <span />
              </div>
            )}
          </div>
        </div>
        {gcsBackupArtifacts.error ? <p className="preference-warning">{actionFailureMessage("Could not list GCS backups", gcsBackupArtifacts.error)}</p> : null}
        <div className="legacy-export-actions">
          <a
            data-tooltip="Download an authenticated legacy metadata JSON export that omits secrets, password hashes, and session tokens."
            href="/api/exports/metadata"
            download
          >
            <Download size={15} />
            Metadata JSON
          </a>
          <a
            data-tooltip="Download an authenticated storage manifest JSON listing original files and derived asset URIs."
            href="/api/exports/storage-manifest"
            download
          >
            <Download size={15} />
            Asset manifest
          </a>
        </div>
      </div>
      <footer className="settings-save-row bottom">{renderSaveAllButton("bottom")}</footer>
    </section>
  );
}

export default function App() {
  const initialRoute = routeFromCurrentLocation();
  const [activeView, setActiveView] = useState<View>(() => initialRoute.view);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<DocumentFilters>(() => emptyFilters());
  const [selectedId, setSelectedId] = useState<string | undefined>(() => initialRoute.documentId);
  const [theme, setTheme] = useState<"day" | "night">(() => (localStorage.getItem("medusa-theme") as "day" | "night") || "day");
  const [backgroundJobs, setBackgroundJobs] = useState<BackgroundJob[]>([]);
  const settingsSaveHandlerRef = useRef<SettingsSaveHandler | null>(null);
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
  const backupRuns = useQuery({
    queryKey: ["backup-runs"],
    queryFn: api.backupRuns,
    enabled: Boolean(me.data),
    refetchInterval: 4000,
  });
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
  const stashes = useQuery({ queryKey: ["doi-stashes"], queryFn: api.doiStashes, enabled: Boolean(me.data), refetchInterval: 4000 });
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => queryClient.clear(),
  });

  useEffect(() => {
    document.title = runtimeLocation.data?.title || MEDUSA_APP_NAME;
  }, [runtimeLocation.data?.title]);

  useEffect(() => {
    const route = routeFromCurrentLocation();
    if (route.documentId) {
      syncBrowserUrlForDocument(route.documentId, "replace");
      return;
    }
    syncBrowserUrlForView(activeView, "replace");
  }, []);

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

  const requestActiveViewChange = useCallback(
    async (view: View, historyMode: BrowserHistoryMode = "push") => {
      if (view === activeView) {
        if (historyMode !== "none") syncBrowserUrlForView(view, historyMode);
        return true;
      }
      if (activeView === "settings" && settingsDirty) {
        const shouldSave = window.confirm(
          "You have unsaved Settings changes. Save before leaving this page?\n\nOK saves first. Cancel leaves without saving.",
        );
        if (shouldSave) {
          const saved = settingsSaveHandlerRef.current ? await settingsSaveHandlerRef.current() : false;
          if (!saved) return false;
        }
      }
      setActiveView(view);
      if (historyMode !== "none") syncBrowserUrlForView(view, historyMode);
      return true;
    },
    [activeView, settingsDirty],
  );
  const requestDocumentFocus = useCallback(
    async (documentId: string, historyMode: BrowserHistoryMode = "push") => {
      if (activeView !== "library") {
        const changed = await requestActiveViewChange("library", "none");
        if (!changed) return false;
      }
      setSelectedId(documentId);
      if (historyMode !== "none") syncBrowserUrlForDocument(documentId, historyMode);
      return true;
    },
    [activeView, requestActiveViewChange],
  );
  const registerSettingsSave = useCallback((handler: SettingsSaveHandler | null) => {
    settingsSaveHandlerRef.current = handler;
  }, []);

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
      void requestActiveViewChange("budget");
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [requestActiveViewChange]);

  useEffect(() => {
    const handlePopState = () => {
      const route = routeFromCurrentLocation();
      const routeChange = route.documentId
        ? requestDocumentFocus(route.documentId, "none")
        : requestActiveViewChange(route.view, "none");
      void routeChange.then((changed) => {
        if (!changed) syncBrowserUrlForView(activeView, "replace");
      });
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [activeView, requestActiveViewChange, requestDocumentFocus]);

  if (me.isLoading) return <div className="loading-screen">Medusa</div>;
  if (me.error || !me.data) {
    return (
      <AppTooltipProvider>
        <Login />
      </AppTooltipProvider>
    );
  }

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
    tags: tags.data?.length ?? 0,
    queue: (jobs.data || []).filter(isQueueImportJob).length + (review.data || []).length,
    notes: notes.data?.length ?? 0,
    import: dashboard.data?.active_import_jobs ?? 0,
    stashes: stashes.data?.length ?? 0,
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
  const activeBackupBackgroundJobs = (backupRuns.data || [])
    .map(backgroundJobFromBackupRun)
    .filter((job) => job.status === "queued" || job.status === "running")
    .slice(0, 3);
  const visibleBackgroundJobs = [...activeBackupBackgroundJobs, ...backgroundJobs, ...activeServerBackgroundJobs].sort(
    (left, right) =>
      Number(isTerminalBackgroundStatus(left.status)) - Number(isTerminalBackgroundStatus(right.status)) ||
      right.createdAt - left.createdAt,
  );
  return (
    <AppTooltipProvider>
      <div className="app-shell" style={shellStyle}>
      <Header
        backgroundJobs={visibleBackgroundJobs}
        dashboard={dashboard.data}
        onOpenQueue={() => void requestActiveViewChange("queue")}
        query={query}
        setQuery={setQuery}
        theme={theme}
        setTheme={setTheme}
        onLogout={() => logout.mutate()}
      />
      <main className="content">
        <section className="content-top">
          <WorkspaceNav activeView={activeView} counts={navCounts} setActiveView={(view) => void requestActiveViewChange(view)} />
        </section>
        {activeView === "library" ? (
          <LibraryView
            documents={documents.data || []}
            document={selectedDocument.data}
            selectedId={selectedId}
            setSelectedId={(id, options) => {
              if (options?.updateUrl === false) {
                setSelectedId(id);
                return;
              }
              void requestDocumentFocus(id);
            }}
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
        {activeView === "domains" ? <DomainsView documents={documents.data || []} domains={domains.data || []} /> : null}
        {activeView === "import" ? (
          <ImportView domains={domains.data || []} jobs={jobs.data || []} projects={projects.data || []} tags={tags.data || []} />
        ) : null}
        {activeView === "projects" ? <ProjectsView documents={documents.data || []} projects={projects.data || []} /> : null}
        {activeView === "tags" ? <TagsView tags={tags.data || []} preferences={preferences.data} /> : null}
        {activeView === "queue" ? <QueueView items={review.data || []} jobs={jobs.data || []} /> : null}
        {activeView === "stashes" ? <StashesView stashes={stashes.data || []} /> : null}
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
            backupRuns={backupRuns.data || []}
            projects={projects.data || []}
            query={query}
            runs={concordanceRuns.data || []}
            savedSearches={savedSearches.data || []}
            selectedDocument={selectedDocument.data}
            startConcordanceRun={startConcordanceRun}
            onDirtyChange={setSettingsDirty}
            onRegisterSave={registerSettingsSave}
          />
        ) : null}
      </main>
      </div>
    </AppTooltipProvider>
  );
}

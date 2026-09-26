import { humanize } from "./format";

export const UPLOAD_DOC_TYPES: { value: string; label: string; group: "court_filing" | "internal" }[] = [
  { value: "writ_petition", label: "Writ petition", group: "court_filing" },
  { value: "affidavit_in_opposition", label: "Affidavit-in-opposition", group: "court_filing" },
  { value: "reply", label: "Reply", group: "court_filing" },
  { value: "rejoinder", label: "Rejoinder", group: "court_filing" },
  { value: "ia", label: "Interlocutory application (IA)", group: "court_filing" },
  { value: "annexure", label: "Annexure", group: "court_filing" },
  { value: "compliance_report", label: "Compliance report", group: "court_filing" },
  { value: "parawise_comments", label: "Parawise comments", group: "internal" },
  { value: "instructions_to_counsel", label: "Instructions to counsel", group: "internal" },
  { value: "other", label: "Other", group: "internal" },
];

const DOC_TYPE_LABELS: Record<string, string> = {
  order: "Order",
  judgment: "Judgment",
  causelist_pdf: "Cause list",
  ...Object.fromEntries(UPLOAD_DOC_TYPES.map((d) => [d.value, d.label])),
};

export const docTypeLabel = (v: string) => DOC_TYPE_LABELS[v] ?? humanize(v);

export const VISIBILITY: { value: string; label: string; short: string }[] = [
  { value: "case_scope", label: "Everyone with access to the case", short: "Case access" },
  { value: "counsel_shared", label: "Shared with counsel", short: "Shared with counsel" },
  { value: "private_to_office", label: "Private to my office", short: "Private to office" },
];

export const visibilityLabel = (v: string) => VISIBILITY.find((x) => x.value === v)?.short ?? humanize(v);

const SCAN: Record<string, string> = {
  pending: "Virus scan pending",
  clean: "Scanned, clean",
  infected: "Blocked: virus found",
  failed: "Virus scan failed",
  not_applicable: "",
};
export const scanLabel = (v: string) => SCAN[v] ?? humanize(v);

const SOURCETRACE: Record<string, string> = {
  ingested: "Available to Case Assistant",
  pending: "Sending to SourceTrace",
  failed: "SourceTrace ingestion failed",
  not_applicable: "Not sent to SourceTrace",
};
export const sourceTraceLabel = (v: string) => SOURCETRACE[v] ?? humanize(v);

const EVENTS: Record<string, string> = {
  listed: "Listed in the cause list",
  listed_supplementary: "Listed in a supplementary list",
  not_listed_as_expected: "Not listed on the expected date",
  hearing_date_changed: "Hearing date changed",
  status_changed: "Status changed",
  order_received: "Order received",
  case_created: "Case first recorded",
  case_refreshed: "Court record refreshed",
  case_merged: "Merged with another record",
  case_linked: "Linked case found",
  recommendation_made: "Recommended to a department",
  recommendation_dismissed: "Recommendation dismissed",
  case_claimed: "Claimed",
  ownership_transfer_requested: "Transfer requested",
  ownership_transferred: "Ownership transferred",
  ownership_released: "Ownership released",
  watcher_added: "Watcher added",
  document_uploaded: "Document uploaded",
  next_date_extracted: "Next date read from order",
  alert_raised: "Alert raised",
  source_failed: "Data source failure",
};
export const eventLabel = (v: string) => EVENTS[v] ?? humanize(v);

const ALERT_KINDS: Record<string, string> = {
  hearing: "Hearing",
  next_date: "Next date",
  compliance: "Compliance",
  order_received: "New order",
  unclaimed_followup: "Unclaimed follow-up",
  data_health: "Data health",
};
export const alertKindLabel = (v: string) => ALERT_KINDS[v] ?? humanize(v);
export const ALERT_KIND_OPTIONS = Object.entries(ALERT_KINDS).map(([value, label]) => ({ value, label }));

const LINKS: Record<string, string> = {
  main_matter: "Main matter",
  connected: "Connected matter",
  ia_in: "Interlocutory application",
  appeal_of: "Appeal",
  contempt_of: "Contempt",
  with: "Listed with",
};
export const linkLabel = (v: string) => LINKS[v] ?? humanize(v);

const NEXT_DATE_SOURCE: Record<string, string> = {
  causelist: "Cause list",
  current_status: "Court status",
  order_specific: "Date in order",
  order_period: "Period in order",
  manual: "Entered manually",
};
export const nextDateSourceLabel = (v: string) => NEXT_DATE_SOURCE[v] ?? humanize(v);

const SIGNALS: Record<string, string> = {
  counsel_code: "Code",
  name_pattern: "Name pattern",
  keyword: "Keyword",
  watchlist: "Watchlist",
  link_history: "Linked",
};
export const signalLabel = (v: string) => SIGNALS[v] ?? humanize(v);

const LIST_TYPES: Record<string, string> = {
  daily: "Daily",
  supplementary: "Supplementary",
  lawazima: "Lawazima",
  vacation: "Vacation",
  other: "Other",
};
export const listTypeLabel = (v: string) => LIST_TYPES[v] ?? humanize(v);

const SOURCES: Record<string, string> = {
  napix: "NAPIX",
  napix_details: "NAPIX details",
  pdf_parse: "PDF parse",
  ghc_website: "GHC website",
  local_dir: "Local folder",
  cnr_history: "Case history",
  show_business: "Business",
  current_status: "Court status",
  causelist: "Cause list",
};
export const sourceLabel = (v: string) => SOURCES[v] ?? humanize(v);

export const OFFICE_KINDS: Record<string, string> = {
  department: "Department",
  directorate: "Directorate",
  section: "Section",
  state_office: "State office",
  counsel_office: "Counsel office",
  central_cell: "Central cell",
};

export const JOBS: { value: string; label: string; needsDate?: boolean }[] = [
  { value: "daily_cycle", label: "Daily cause-list cycle", needsDate: true },
  { value: "status_refresh", label: "Current status refresh" },
  { value: "full_refresh", label: "Full case refresh" },
  { value: "master_sync", label: "NAPIX master sync" },
  { value: "discovery", label: "Department discovery" },
  { value: "rescore", label: "Re-score pending cases" },
  { value: "alerts", label: "Raise alerts" },
];

export const REQUEST_KINDS: { value: string; label: string }[] = [
  { value: "records", label: "Records (petition, notice, annexures)" },
  { value: "report", label: "Report / parawise comments" },
  { value: "instructions", label: "Instructions to standing counsel" },
  { value: "views", label: "Views of a referral department" },
  { value: "signature", label: "Signature on affidavit" },
  { value: "implementation", label: "Implementation of a court order" },
  { value: "brief", label: "Brief from standing counsel" },
  { value: "other", label: "Other" },
];
export const requestKindLabel = (v: string) => REQUEST_KINDS.find((k) => k.value === v)?.label.split(" (")[0] ?? humanize(v);

export const NOTE_KINDS: { value: string; label: string }[] = [
  { value: "general", label: "General" },
  { value: "instruction", label: "Instruction" },
  { value: "opinion", label: "Opinion" },
  { value: "hearing_note", label: "Hearing note" },
  { value: "compliance", label: "Compliance" },
  { value: "decision", label: "Decision" },
];
const NOTE_KIND_EXTRA: Record<string, string> = { handover: "Hand-over", system: "System", assistant: "From Case Assistant" };
export const noteKindLabel = (v: string) => NOTE_KINDS.find((k) => k.value === v)?.label ?? NOTE_KIND_EXTRA[v] ?? humanize(v);

const CUSTODY_REASONS: Record<string, string> = {
  claim: "Claimed",
  allot: "Allotted",
  transfer: "Transferred",
  request_sent: "Request sent",
  request_answered: "Request answered",
  request_withdrawn: "Request withdrawn",
  handover: "Handed over",
  release: "Released",
};
export const custodyReasonLabel = (v: string) => CUSTODY_REASONS[v] ?? humanize(v);

const STAGES: Record<string, string> = {
  notice_received: "Notice received",
  records_received: "Records received",
  response_mode_decided: "Response mode decided",
  inputs_awaited: "Inputs awaited",
  inputs_received: "Inputs received",
  referral_views_awaited: "Referral views awaited",
  instructions_sent: "Instructions sent",
  affidavit_filed: "Affidavit filed",
  order_under_examination: "Order under examination",
  compliance_in_progress: "Compliance in progress",
  complied: "Complied",
  appeal_review_under_consideration: "Appeal / review under consideration",
  appeal_review_instructed: "Appeal / review instructed",
  appeal_review_filed: "Appeal / review filed",
  contempt_notice_received: "Contempt notice received",
  vakalatnama_sent: "Vakalatnama sent",
  appearance_entered: "Appearance entered",
};
export const stageLabel = (v: string | null | undefined) => (v ? (STAGES[v] ?? humanize(v)) : "-");

const REQUEST_STATUS: Record<string, string> = { open: "Open", answered: "Answered", withdrawn: "Withdrawn" };
export const requestStatusLabel = (v: string) => REQUEST_STATUS[v] ?? humanize(v);

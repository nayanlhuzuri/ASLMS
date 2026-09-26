import type { components } from "./api-types";

type S = components["schemas"];

export type Me = S["MeOut"];
export type Office = S["OfficeOut"];
export type OwnerRef = S["OwnerRef"];
export type CaseCard = S["CaseCard"];
export type CaseDetail = S["CaseDetail"];
export type Custody = S["CustodyOut"];
export type CustodyLeg = S["CustodyLegOut"];
export type EventOut = S["EventOut"];
export type Hearing = S["HearingOut"];
export type Listing = S["ListingOut"];
export type ListingRef = S["ListingRef"];
export type LinkOut = S["LinkOut"];
export type Order = S["OrderOut"];
export type ScoreOut = S["ScoreOut"];
export type Signal = S["SignalOut"];
export type Ownership = S["OwnershipOut"];
export type DocumentOut = S["DocumentOut"];
export type NextDate = S["NextDateOut"];
export type Recommendation = S["RecommendationOut"];
export type Transfer = S["TransferOut"];
export type SearchOut = S["SearchOut"];
export type CauseList = S["CauseListOut"];
export type CauseListDate = S["CauseListDateOut"];
export type Entry = S["EntryOut"];
export type Alert = S["AlertOut"];
export type CalendarItem = S["CalendarItem"];
export type Notification = S["NotificationOut"];
export type User = S["UserOut"];
export type UserIn = S["UserIn"];
export type UserPatch = S["UserPatch"];
export type CounselCode = S["CounselCodeOut"];
export type UnmappedCode = S["UnmappedCodeOut"];
export type Pattern = S["PatternOut"];
export type Keyword = S["KeywordOut"];
export type Watch = S["WatchOut"];
export type CaseType = S["CaseTypeOut"];
export type Audit = S["AuditOut"];
export type Preference = S["PreferenceOut"];
export type PreferenceIn = S["PreferenceIn"];
export type Ok = S["Ok"];
export type DashboardSummary = S["DashboardOut"];
export type DataHealth = S["DataHealthOut"];
export type Failure = S["FailureOut"];
export type ReportTable = S["ReportOut"];
export type AppConfig = S["ConfigOut"];
export type RequestOut = S["RequestOut"];
export type RequestMessage = S["RequestMessageOut"];
export type StageOut = S["StageOut"];
export type StageSet = S["StageSetOut"];
export type Note = S["NoteOut"];
export type NoteAttachment = S["NoteAttachmentOut"];
export type Conversation = S["ConversationOut"];
export type AssistantMessage = S["AssistantMessageOut"];

export interface Page<T> {
  total: number;
  page: number;
  size: number;
  items: T[];
}

/** `SearchOut.live` is an untyped object in the contract; shape from the backend search service. */
export interface LiveSearch {
  napix?: string;
  found?: number;
  stored?: number;
  error?: string;
}

/** GET /assistant/status (untyped in the contract). */
export interface AssistantStatus {
  connected: boolean;
  service?: string;
  detail?: string;
}

/** An assistant citation (untyped objects in the contract); rendered defensively. */
export interface Citation {
  title?: string;
  reference?: string;
  document_id?: string;
  url?: string;
}

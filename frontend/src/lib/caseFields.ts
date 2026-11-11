/**
 * The labels of the case Details tab (design portal-names-and-labels, decisions 17-19): one plain label for every key
 * the overview can send, following the NAPIX specifications and the coverage table (`docs/schema/napix_coverage.md`
 * §C). Where a field's meaning is not documented the label is the field's own words written out (open question 2,
 * answered with the recommended labels). Keys holding a UUID, and `is_tracked` (a flag no service writes), are hidden
 * by name. `caseFields.test.ts` holds this map against the keys the backend exports (`enumCodes.json`).
 */
import { labelFor } from "./displayLabels";
import { T } from "./messages";

export const CASE_FIELD_LABELS: Readonly<Record<string, string>> = {
  // identity
  cnr: "CNR",
  court: "Court",
  est_code: "Establishment Code",
  court_est_name: "Court Establishment",
  case_type_text: "Case Type",
  reg_no: "Registration Number",
  reg_year: "Registration Year",
  case_no_text: "Case Number",
  filing_case_type_text: "Filing Case Type",
  filing_no: "Filing Number",
  filing_year: "Filing Year",
  filing_no_text: "Filing Case Number",
  filing_date: "Date of Filing",
  registration_date: "Date of Registration",
  date_first_list: "First Hearing Date",
  // status
  status: "Status",
  disposal_date: "Date of Decision",
  disposal_nature: "Nature of Disposal",
  disposal_type: "Disposal Type",
  short_order: "Short Order",
  date_filing_disp: "Filing Disposal Date",
  reason_for_rej: "Reason for Rejection",
  date_judgement_pronounced: "Judgment Pronounced On",
  date_judgement_reserved: "Judgment Reserved On",
  goshwara_no: "Goshwara Number",
  next_hearing_date: "Next Date in the Court's Record",
  next_purpose: "Purpose or Stage",
  last_hearing_date: "Last Hearing Date",
  // classification
  napix_bench_id: "Bench ID",
  bench_name: "Bench Name",
  bench_type_code: "Bench Type Code",
  coram: "Coram",
  coram_designation: "Judge's Designation",
  judicial_branch: "Judicial Branch",
  category: "Category",
  category_code: "Category Code",
  sub_category: "Sub-category",
  sitting_bench: "Sitting Bench",
  judges: "Judges",
  // place
  state_name_as_listed: "State",
  district_name_as_listed: "District",
  filing_state_code: "Case State Code",
  filing_district_code: "Case District Code",
  fir_no: "FIR Number",
  fir_year: "FIR Year",
  police_station: "Police Station",
  police_st_code: "Police Station Code",
  uniform_code: "National Police Station Code",
  main_matter_text: "Main Case Number",
  // parties as printed
  petitioner_summary: "Petitioner",
  respondent_summary: "Respondent",
  pet_advocate: "Petitioner's Advocate",
  res_advocate: "Respondent's Advocate",
  // acts
  act_name_as_listed: "Act",
  national_act_code: "National Act Code",
  section: "Section",
  // lower courts (`case_no_text` as above)
  level: "Court Level",
  court_name: "Court",
  decision_date: "Date of Decision",
  // applications (`status` and `filing_date` as above)
  ia_number: "IA Number",
  party_name: "Party",
  // objections
  seq: "No.",
  objection: "Objection",
  scrutiny_date: "Scrutiny Date",
  compliance_by_date: "Comply By",
  receipt_date: "Date Received",
  // court transfers
  transfer_date: "Date of Transfer",
  from_court_text: "From Court",
  to_court_text: "To Court",
  // writ information
  appellate_case_number: "Appellate Case Number",
  appellate_authority: "Appellate Authority",
  // the portal's own
  is_provisional: "Provisional (No CNR Yet)",
  first_seen_source: "First Seen From",
  last_full_refresh_at: "Court Details Last Fetched",
  last_status_refresh_at: "Status Last Checked",
  dossier_stale: "Court Details Need Refreshing",
  closed_at: "Recorded As Disposed",
  created_at: "Added to ASLMS",
  updated_at: "Last Changed",
};

/** Keys never shown: internal ids, and `is_tracked` (always false since migration 0001; noise). */
export const HIDDEN_FIELDS: ReadonlySet<string> = new Set([
  "id",
  "case_type_id",
  "filing_case_type_id",
  "bench_id",
  "state_id",
  "district_id",
  "merged_into_case_id",
  "created_by",
  "updated_by",
  "is_tracked",
]);

/** The label of a Details key. */
export function caseFieldLabel(key: string): string {
  return labelFor(CASE_FIELD_LABELS, key);
}

/** The blocks whose `status` is an application's P / D rather than the case status. */
export type FieldBlock = "case" | "applications" | "lower_courts";

/** A coded value named in words (decision 19): the case status, where the case was first seen, the court level and
 * an application's P / D; any other value is returned unchanged. */
export function caseFieldValue(key: string, value: unknown, block: FieldBlock = "case"): unknown {
  if (typeof value !== "string" || value === "") return value;
  if (key === "status") return labelFor(block === "applications" ? T.case.applicationStatuses : T.case.statuses, value);
  if (key === "first_seen_source") return labelFor(T.case.firstSeenSources, value);
  if (key === "level") return labelFor(T.case.lowerCourtLevels, value);
  return value;
}

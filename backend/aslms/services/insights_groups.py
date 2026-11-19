"""The groupings of State Insights (design `state-insights`, decisions 14 to 16): the subject groups and the kinds of
case (`insight_groups`), the court's categories in subject groups (`insight_subject_categories`) and the case types in
kinds of case (`insight_case_type_groups`).

- **Who edits:** the Super Administrator only, through the reserved function `admin.insights_groups`.
- **What:** add a group, rename it, reorder it, deactivate a group that is not reserved, and move categories and case
  types between groups (a batch Save, one audit row per changed line). A deactivated group's categories read as Not
  Grouped and its case types as Other until they are moved (Deviation 4 of the design note).
- **When:** at once; the mapping is joined at query time, so no rebuild is needed.
- **The seed** (`seed`) carries the same lists as migration 0039 (`SEED_*`; `tests/unit/test_insights_seed_lists.py`
  holds the two equal) and inserts only what is missing. The draft subject groups are those of
  `docs/design/state-insights-subject-groups.md`; the kinds of case those of decision 16.
- **The seed case-type lines** (`place_seed_case_types`, design `state-insights-review-advisories`, decision 5) are
  also placed by the `insights-refresh` and `insights-rebuild` jobs, so a case type the court masters sync creates
  after `init` takes its seed line without a person; an existing line is never changed.
- **The write answers** (decision 6) are the lines the lists show, with their real counts (`group_line`, the lines of
  `set_categories` and `set_case_types`); `sort_order` is a whole number from 0 to `SORT_ORDER_MAX`."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from aslms.domain.cases import Case, CaseStatus
from aslms.domain.courts import CaseType, Court
from aslms.domain.insights import (
    GROUP_KINDS,
    InsightCaseFact,
    InsightCaseTypeGroup,
    InsightGroup,
    InsightSubjectCategory,
)
from aslms.domain.org import User
from aslms.domain.reference import Permission
from aslms.services import access, list_search, list_sort
from aslms.services.access import Member
from aslms.services.audit import Actor, write_audit

COURT_REF_CODE = "GHC"

SEED_SUBJECT_GROUPS: tuple[tuple[str, str], ...] = (
    ("service_state", "Service: State Government Employees"),
    ("service_teachers", "Service: Teachers of Provincialised Schools"),
    ("service_public_bodies", "Service: Local Bodies, Undertakings, Universities and Defence"),
    ("education", "Education and Academic Matters"),
    ("land_revenue", "Land and Revenue"),
    ("foreigners", "Foreigners Tribunal and Citizenship"),
    ("tax", "Tax and Duties"),
    ("contracts_licences", "Contracts, Settlements and Licences"),
    ("local_bodies_elections", "Panchayat, Municipal, Elections and Co-operatives"),
    ("labour", "Labour and Industrial"),
    ("criminal", "Criminal Matters and Bail"),
    ("civil", "Civil Appeals, Revisions and Suits"),
    ("rights_public_interest", "Rights, Detention and Public Interest"),
    ("contempt", "Contempt (Original Subject Not Yet Known)"),
    ("other", "Other Writ and Procedural Matters"),
)
SEED_CATEGORIES: tuple[tuple[int, str, str], ...] = (
    (
        10001,
        "Ad hoc appointment with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10002,
        "Regularisation of ad hoc appointment with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10003,
        "Selection and appointment with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10004,
        "Appointment in retired teachers quota with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10005,
        "Appointment on compassionate ground on Educational Matter with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10006,
        "Appointment of family members of victim of extremist violence with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10007,
        "Regular appointment of honorary teacher with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10008,
        "Salary and allowances with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (10009, "Seniority with respect to Service of Teachers of Provincialized Schools.", "service_teachers"),
    (10010, "Promotion with respect to Service of Teachers of Provincialized Schools.", "service_teachers"),
    (10011, "Transfer with respect to Service of Teachers of Provincialized Schools.", "service_teachers"),
    (10012, "Suspension with respect to Service of Teachers of Provincialized Schools.", "service_teachers"),
    (
        10013,
        "Disciplinary and enquiry proceedings with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10014,
        "Minor punishment with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10015,
        "Major punishment with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10016,
        "Date of birth with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10017,
        "Retirement benefits with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10018,
        "Orders passed by the Director with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10019,
        "Orders passed by any other educational authority with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (
        10020,
        "Other service matters with respect to Service of Teachers of Provincialized Schools.",
        "service_teachers",
    ),
    (10021, "Ad hoc appointment with respect to State Govt Employees.", "service_state"),
    (10022, "Regularisation of ad hoc appointment with respect to State Govt Employees.", "service_state"),
    (10023, "Selection and appointment with respect to State Govt Employees.", "service_state"),
    (10024, "Appointment on compassionate ground on non-educational matter.", "service_state"),
    (10025, "Appointment of family members of victim extremists violence", "service_state"),
    (10026, "Salary and allowancest with respect to State Govt Employees.", "service_state"),
    (10027, "Seniority with respect to State Govt Employees.", "service_state"),
    (10028, "Promotion with respect to State Govt Employees.", "service_state"),
    (10029, "Reservation of vacancies with respect to State Govt Employees.", "service_state"),
    (10030, "Transfer with respect to State Govt Employees.", "service_state"),
    (10031, "Suspension with respect to State Govt Employees.", "service_state"),
    (10032, "Disciplinary and enquiry proceedings with respect to State Govt Employees.", "service_state"),
    (10033, "Minor punishment with respect to State Govt Employees.", "service_state"),
    (10034, "Major punishment with respect to State Govt Employees.", "service_state"),
    (10035, "Compulsory retirement with respect to State Govt Employees.", "service_state"),
    (
        10036,
        "Order of the Appellate or Reisional authority with respect to State Govt Employees.",
        "service_state",
    ),
    (
        10037,
        "Order of the Administrative or service Tribunal with respect to State Govt Employees.",
        "service_state",
    ),
    (10038, "Date of birth with respect to State Govt Employees.", "service_state"),
    (10039, "Retirement benefits with respect to State Govt Employees.", "service_state"),
    (10040, "Other service matters with respect to State Govt Employees.", "service_state"),
    (
        10041,
        "Ad hoc appointment with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and",
        "service_public_bodies",
    ),
    (
        10042,
        "Regularisation of ad hoc appointment with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and",
        "service_public_bodies",
    ),
    (
        10043,
        "Selection and appointment with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universiti",
        "service_public_bodies",
    ),
    (
        10044,
        "Appointment on compassionate ground with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and",
        "service_public_bodies",
    ),
    (
        10046,
        "Salary and allowances with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities a",
        "service_public_bodies",
    ),
    (
        10047,
        "Seniority with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and Instituti",
        "service_public_bodies",
    ),
    (
        10048,
        "Promotion with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and Instituti",
        "service_public_bodies",
    ),
    (
        10049,
        "Reservation of vacancies with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universitie",
        "service_public_bodies",
    ),
    (
        10050,
        "Transfer with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and Institutio",
        "service_public_bodies",
    ),
    (
        10051,
        "Suspension with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and Institut",
        "service_public_bodies",
    ),
    (
        10052,
        "Disciplinary and enquiry proceedings with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and",
        "service_public_bodies",
    ),
    (
        10053,
        "Minor punishment with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and In",
        "service_public_bodies",
    ),
    (
        10054,
        "Major punishment with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and In",
        "service_public_bodies",
    ),
    (
        10055,
        "Compulsory retirement with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities a",
        "service_public_bodies",
    ),
    (
        10057,
        "Order of the Appellate or Revisional authority with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory",
        "service_public_bodies",
    ),
    (
        10058,
        "Date of birth with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and Insti",
        "service_public_bodies",
    ),
    (
        10059,
        "Retirement benefits with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and",
        "service_public_bodies",
    ),
    (
        10060,
        "Other service matters with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities a",
        "service_public_bodies",
    ),
    (
        10063,
        "Selection and appointment relating to service of Defence Personal and Armed Forces.",
        "service_public_bodies",
    ),
    (
        10066,
        "Salary and allowances relating to service of Defence Personal and Armed Forces.",
        "service_public_bodies",
    ),
    (10068, "Promotion relating to service of Defence Personal and Armed Forces.", "service_public_bodies"),
    (
        10074,
        "Major punishment relating to service of Defence Personal and Armed Forces.",
        "service_public_bodies",
    ),
    (
        10079,
        "Retirement benefits relating to service of Defence Personal and Armed Forces.",
        "service_public_bodies",
    ),
    (
        10080,
        "Other service matters relating to service of Defence Personal and Armed Forces.",
        "service_public_bodies",
    ),
    (10081, "Admissions in MBBS or BDS Course in Medical and Dental College", "education"),
    (10082, "Admissions in Post Graduate Degree and Diploma courses in Medical College", "education"),
    (10083, "Admissions in Engineering Colleges.", "education"),
    (10084, "Admissions in other Institutions.", "education"),
    (10085, "With-holding and cancellation of results.", "education"),
    (10086, "Evaluation and totalling of marks in Examination.", "education"),
    (10087, "Mal-practice at the time of Examination.", "education"),
    (10088, "Examination Centre.", "education"),
    (10089, "Expulsion of students from academic Institutions.", "education"),
    (10090, "Other academic disputes.", "education"),
    (10091, "Governing Body of aided Colleges.", "education"),
    (10092, "Governing Body of other Colleges.", "education"),
    (10093, "Managing Committee of aided Schools", "education"),
    (10094, "Managing Committee of other Schools.", "education"),
    (10095, "Permission for and Recognition of Schools and Colleges", "education"),
    (10096, "Provincialisation of Schools", "service_teachers"),
    (10097, "Grants in Aid to Schools", "education"),
    (10098, "Provincialisation of staff of schools", "service_teachers"),
    (10099, "Orders passed by authorities in relation to Mangmnt of Schools & Colleges", "education"),
    (10100, "Other disputes relating to Management of academic Institutions", "education"),
    (10101, "Sales Tax", "tax"),
    (10103, "Income Tax", "tax"),
    (10104, "Central Excise", "tax"),
    (10105, "Motor Vehicle Tax", "tax"),
    (10107, "Gift Tax", "tax"),
    (10109, "Purchase Tax", "tax"),
    (10110, "Municipal Tax", "tax"),
    (10111, "Custom Duty", "tax"),
    (10114, "Octroi", "tax"),
    (10115, "Licence Fee", "tax"),
    (10116, "Penalty", "tax"),
    (10117, "Confiscation", "tax"),
    (10118, "Seizure", "tax"),
    (10119, "Check Gate", "tax"),
    (10120, "Other Tax matters.", "tax"),
    (10121, "Industrial Disputes Act, 1947.", "labour"),
    (10122, "Trade Union Act, 1926.", "labour"),
    (10123, "Workmen Compensation Act, 1923.", "labour"),
    (10124, "Employees State Insurance Act, 1948.", "labour"),
    (10125, "Factories Act, 1948.", "labour"),
    (10126, "Employmees Provident Funds and Misc. Provision act, 19", "labour"),
    (10127, "Payment of Gratuity Act, 1962.", "labour"),
    (10128, "Payment of Bonus Act, 1965.", "labour"),
    (10129, "Payment of Wages Act, 1936.", "labour"),
    (10131, "Contract Labour (Regulation Payment) Act, 1970.", "labour"),
    (10132, "Other Labour and Industrial Cases.", "labour"),
    (10140, "Settlement of Fishery by the State Govt.", "contracts_licences"),
    (10141, "Settlement of Fishery by the Assam Fisheries Development Corporation", "contracts_licences"),
    (10142, "Settlement of Country Liquor Shop.", "contracts_licences"),
    (10143, "Settlement of Foreign Liquor Shop.", "contracts_licences"),
    (10144, "Settlement of Markets.", "contracts_licences"),
    (10145, "Settlement of Sand Mahal.", "contracts_licences"),
    (10146, "Settlement of Quarry.", "contracts_licences"),
    (10147, "Settlement of Forest Produce.", "contracts_licences"),
    (
        10148,
        "Other settlements relating to settlements made by the State Govt and Other Authorities..",
        "contracts_licences",
    ),
    (10149, "Orders passed by the Assam Board of Revenue in appeal.", "land_revenue"),
    (10150, "Orders passed by the Government in appeals.", "land_revenue"),
    (10151, "Acquisition of land.", "land_revenue"),
    (10152, "Requisition of land.", "land_revenue"),
    (10153, "Settlement of land.", "land_revenue"),
    (10154, "Eviction from land.", "land_revenue"),
    (10155, "Orders passed under the Urban Land (Ceiling Regulation Act,1976)", "land_revenue"),
    (10156, "Orders for demolition of unauthorised construction on land", "land_revenue"),
    (10157, "Sale of land by member of Schedule Tribe.", "land_revenue"),
    (10158, "Issue of patta in respect of land.", "land_revenue"),
    (10159, "Orders passed by the Board of Revenue in land matters.", "land_revenue"),
    (10160, "Other land matters relating to Land Matters.", "land_revenue"),
    (10162, "Recovery of other dues under the Public Demand Recovery Act", "land_revenue"),
    (10163, "Electricity Disputes.", "contracts_licences"),
    (10164, "Requisition of vehicles.", "contracts_licences"),
    (10165, "Payment of bills in respect of requisitioned vehicles.", "contracts_licences"),
    (10166, "Permit of vehicles.", "contracts_licences"),
    (10167, "Payment of road tax.", "contracts_licences"),
    (10168, "No confidence motion passed by Panchayat.", "local_bodies_elections"),
    (10169, "Other cases under the Panchayat Acts.", "local_bodies_elections"),
    (10170, "Election of Municipal Boards/Corporation.", "local_bodies_elections"),
    (10171, "Election of members of Panchayat.", "local_bodies_elections"),
    (10172, "Election of office bearers of Co-Operative Societies.", "local_bodies_elections"),
    (10173, "Annual General Meeting of Co-Operative Societies.", "local_bodies_elections"),
    (
        10174,
        "Orders passed by the authorities under the Co-Operative Societies Act",
        "local_bodies_elections",
    ),
    (10175, "Orders under the Essential Commodities Act.", "contracts_licences"),
    (10176, "Oders of Foreigners Tribunal/Illegal Migrant(D) Tribunal", "foreigners"),
    (10177, "Transit passes for Forest Produce.", "contracts_licences"),
    (10178, "Telephone Disputes.", "other"),
    (10179, "Disputes against the Railways.", "other"),
    (10180, "Award of contracts by the State or its instrumentalities", "contracts_licences"),
    (10181, "Subsidy Matters.", "contracts_licences"),
    (10182, "Dissolution of Autonomous Council Local Bodies", "local_bodies_elections"),
    (10183, "Compensations relating to Land Matters.", "land_revenue"),
    (10184, "License and Permissions.", "contracts_licences"),
    (10185, "Electoral Roll & Voters List.", "local_bodies_elections"),
    (10186, "Army & Police Action.", "rights_public_interest"),
    (10187, "Eviction from House.", "land_revenue"),
    (10188, "Challenge to Orders passed by dist. & state govt. authority", "other"),
    (10189, "Other Civil Rules relating to other Writ Petitions.", "other"),
    (
        10190,
        "Habeas Corpus - Non-production of a person before the Magistrate after arrest",
        "rights_public_interest",
    ),
    (10191, "Detention under the Prevention Detention Law.", "rights_public_interest"),
    (10192, "Death after detention in custody.", "rights_public_interest"),
    (10193, "Other Habeas Corpus petitions.", "rights_public_interest"),
    (10194, "Public Interest Litigations.", "rights_public_interest"),
    (10195, "Compensation for custodial violence, torture etc.", "rights_public_interest"),
    (10200, "Contempt Petition (Civil).", "contempt"),
    (10201, "Contempt Petition (Criminal)", "contempt"),
    (10202, "Comtempt Petition (Sub Moto)", "contempt"),
    (10203, "Company Petitions", "civil"),
    (10205, "Testamentary cases.", "civil"),
    (
        10206,
        "Election Petitions relating to election of members of Legislative assembly",
        "local_bodies_elections",
    ),
    (10207, "Election Petitions relating to election of members of Lok Sabha", "local_bodies_elections"),
    (10209, "Execution cases in succession matters etc.", "civil"),
    (10220, "Family Court Appeals.", "civil"),
    (10221, "Appeals under order 43 Rule 1 CPC relating to temporar injunction", "civil"),
    (10222, "Other appeals under Order 43 Rule 1 CPC in temporary", "civil"),
    (10223, "Appeals from motor accident claims tribunal.", "civil"),
    (10224, "Appeal from Railway Claims Tribunal", "civil"),
    (10225, "Appeals under the Workmen Compensation Act, 1923.", "labour"),
    (10226, "Appeals under the Local Rent Control Acts.", "civil"),
    (10227, "Appeals under the Employees State Insurance Act, 1948.", "labour"),
    (10228, "Appeals against Original Decrees.", "civil"),
    (10229, "Other First Appeals.", "civil"),
    (10230, "Second Appeals arising out of suits for title and/or injunction", "civil"),
    (10231, "Second Appeals arising out of suits for specific enforcement of contract", "civil"),
    (10232, "Second Appeals arising out of suits in respect of service matters", "civil"),
    (10233, "Second appeals arising out of suits in respect other matters", "civil"),
    (10234, "Second Appeals against orders MA(S)", "civil"),
    (10236, "Appeals under the Companies Act, 1956.", "civil"),
    (10237, "Writ Appeals under the Gauhati High Court Rules.", "other"),
    (10238, "Contempt Appeal", "contempt"),
    (10240, "Civil Revision against orders passed by Civil Court in suits", "civil"),
    (10241, "Civil Revision against appellate decree under the Local Rent Control Act", "civil"),
    (
        10242,
        "Civil Revision against orders in cases filed under section 6 of the specific Relief Act",
        "civil",
    ),
    (10243, "Civil Revision against orders passed in execution case", "civil"),
    (10244, "Civil Revision under Article 227 of the Constitution.", "civil"),
    (10245, "Civil Revisions for transfer of suit under Section 24 of the CPC", "civil"),
    (10246, "Other Civil Revisions.", "civil"),
    (10247, "Arbitration Cases", "civil"),
    (10250, "Appeals against conviction for offences under IPC.", "criminal"),
    (10251, "Appeals against acquittal.", "criminal"),
    (10252, "Appeals against conviction under the NDPS Act.", "criminal"),
    (10253, "Appeals against conviction under other Acts.", "criminal"),
    (10255, "Criminal Appeals (Jail)", "criminal"),
    (10259, "Criminal reference (Hills)", "criminal"),
    (10260, "Criminal Revisions against acquittal.", "criminal"),
    (10261, "Criminal Revisions against orders passed in trial cases", "criminal"),
    (10262, "Criminal Revisions in respect of orders passed in cases", "criminal"),
    (10263, "Criminal Revisions for quashing of criminal proceeding", "criminal"),
    (10265, "Other Criminal revisions", "criminal"),
    (10266, "Bail Application", "criminal"),
    (10267, "Anticipatory bail Application", "criminal"),
    (10268, "Other Criminal mis. Cases under Section 482", "criminal"),
    (10269, "Applications for transfer Of Criminal cases", "criminal"),
    (10271, "Reference under section 256(1) of the Income-Tax Act 1961", "tax"),
    (10281, "References under the Agricultural Income-tax Act to the High Court", "tax"),
    (10285, "Confirmation Of Death sentence", "criminal"),
    (10295, "Review Applications In Civil Rule", "other"),
    (10296, "Review Application in First Appeal", "other"),
    (10297, "Review Application in Second Appeal", "other"),
    (10298, "Review Application in Civil Revision", "other"),
    (10299, "Other Review Applications", "other"),
    (10300, "Revision Petition u/s 81 of the Assam Value Added Tax Act2003.", "tax"),
    (10301, "Interlocutory Application (Civil)", "other"),
    (10302, "Interlocutory Application (Criminal)", "other"),
    (10303, "Restoration of a case dismissed for default.", "civil"),
    (10304, "Review.", "other"),
    (10305, "RERA APPEAL matter", "civil"),
    (10306, "Commercial Appellate Division Cases", "civil"),
    (10307, "Hill Appeal", "civil"),
    (10308, "CS(OS)", "civil"),
    (10309, "Appeals preferred under Section 42 of the Prevention of Money-Laundering Act, 2002", "criminal"),
    (10310, "Citizenship, NRC, push back/deportation and other ancillary matters", "foreigners"),
    (10311, "Cases preferred for Cancellation of Bail granted by the learned Trial Court", "criminal"),
    (99999, "COVID Related Matters", "other"),
)

SEED_FAMILY_GROUPS: tuple[tuple[str, str], ...] = (
    ("writ", "Writ Petition"),
    ("writ_criminal", "Writ Petition (Criminal) and Habeas Corpus"),
    ("pil", "Public Interest Litigation"),
    ("contempt", "Contempt"),
    ("writ_appeal", "Writ Appeal"),
    ("motor_accident_appeal", "Motor Accident Appeal"),
    ("civil_appeal", "Civil Appeal"),
    ("criminal_appeal", "Criminal Appeal"),
    ("bail", "Bail"),
    ("criminal_petition", "Criminal Petition (Section 482)"),
    ("revision", "Revision"),
    ("review", "Review"),
    ("transfer", "Transfer"),
    ("arbitration", "Arbitration"),
    ("tax", "Tax and Customs"),
    ("election", "Election"),
    ("company", "Company"),
    ("testamentary", "Testamentary and Succession"),
    ("ia", "Interlocutory Application"),
    ("other", "Other"),
)
RESERVED_GROUPS: tuple[tuple[str, str], ...] = (
    ("family", "contempt"),
    ("family", "ia"),
    ("family", "other"),
    ("subject", "contempt"),
)
SEED_CASE_TYPES: tuple[tuple[int, str], ...] = (
    (49, "bail"),
    (59, "other"),
    (65, "civil_appeal"),
    (93, "pil"),
    (96, "civil_appeal"),
    (97, "civil_appeal"),
    (98, "civil_appeal"),
    (99, "civil_appeal"),
    (100, "civil_appeal"),
    (102, "revision"),
    (103, "review"),
    (111, "writ"),
    (112, "writ_appeal"),
    (114, "company"),
    (117, "company"),
    (121, "civil_appeal"),
    (123, "testamentary"),
    (124, "testamentary"),
    (127, "civil_appeal"),
    (133, "motor_accident_appeal"),
    (134, "election"),
    (138, "arbitration"),
    (139, "arbitration"),
    (142, "contempt"),
    (144, "civil_appeal"),
    (148, "tax"),
    (151, "tax"),
    (159, "other"),
    (166, "criminal_appeal"),
    (167, "criminal_appeal"),
    (168, "revision"),
    (170, "criminal_petition"),
    (171, "bail"),
    (173, "writ_criminal"),
    (174, "contempt"),
    (177, "transfer"),
    (190, "criminal_appeal"),
    (204, "transfer"),
    (208, "criminal_appeal"),
    (209, "criminal_petition"),
    (211, "other"),
    (213, "tax"),
    (214, "testamentary"),
    (216, "revision"),
    (217, "revision"),
    (218, "ia"),
    (220, "ia"),
    (221, "ia"),
    (222, "pil"),
    (225, "writ"),
    (228, "contempt"),
    (229, "contempt"),
    (231, "civil_appeal"),
    (232, "civil_appeal"),
    (233, "civil_appeal"),
    (234, "criminal_appeal"),
    (235, "bail"),
)


class GroupsError(ValueError):
    """A refused groupings change: `code` is machine-readable (`code_taken`, `label_taken`, `reserved_group`,
    `bad_group`, `bad_code`, `bad_label`, `bad_kind`, `bad_sort_order`, `not_found`), `http_status` 400, 404 or
    409."""

    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
LABEL_MAX = 120
DESCRIPTION_MAX = 1000
SORT_ORDER_MAX = 10_000
CATEGORY_SORTS = {"code": "asc", "label": "asc", "group": "asc", "cases": "desc", "pending": "desc"}
CASE_TYPE_SORTS = {"code": "asc", "name": "asc", "group": "asc", "cases": "desc", "pending": "desc"}
NOT_GROUPED = "not_grouped"


def require_groups_admin(session: Session, user: User | Member) -> None:
    """Decision 14: the reserved function `admin.insights_groups`, held by the Super Administrator alone."""
    access.require(session, user, Permission.ADMIN_INSIGHTS_GROUPS)


def _kind(kind: str | None) -> str:
    if kind not in GROUP_KINDS:
        raise GroupsError("bad_kind", "kind is subject or family")
    return str(kind)


def _now() -> datetime:
    return datetime.now(UTC)


def group_summary(row: InsightGroup) -> dict[str, Any]:
    return {
        "kind": row.kind,
        "code": row.code,
        "label": row.label,
        "description": row.description,
        "sort_order": row.sort_order,
        "is_reserved": row.is_reserved,
        "is_active": row.is_active,
    }


def _sort_order(value: Any) -> int:
    """Decision 6 of state-insights-review-advisories: a whole number from 0 to `SORT_ORDER_MAX` (400
    `bad_sort_order`), so a value past the integer range is refused here and never reaches PostgreSQL."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= SORT_ORDER_MAX:
        raise GroupsError("bad_sort_order", f"sort_order is a whole number from 0 to {SORT_ORDER_MAX}")
    return int(value)


def _label(label: str | None) -> str:
    s = " ".join((label or "").split())
    if not s or len(s) > LABEL_MAX:
        raise GroupsError("bad_label", f"a label is 1 to {LABEL_MAX} characters")
    return s


def _label_taken(session: Session, kind: str, label: str, but: uuid.UUID | None = None) -> bool:
    stmt = select(InsightGroup.id).where(
        InsightGroup.kind == kind, func.lower(InsightGroup.label) == label.lower()
    )
    if but is not None:
        stmt = stmt.where(InsightGroup.id != but)
    return session.scalar(stmt.limit(1)) is not None


def group_by_code(session: Session, kind: str, code: str) -> InsightGroup | None:
    return session.scalar(select(InsightGroup).where(InsightGroup.kind == kind, InsightGroup.code == code))


def _member_counts(session: Session, kind: str) -> dict[uuid.UUID, int]:
    if kind == "subject":
        rows = session.execute(
            select(
                InsightSubjectCategory.group_id,
                func.count(func.distinct(InsightSubjectCategory.category_code)),
            )
            .where(InsightSubjectCategory.group_id.is_not(None))
            .group_by(InsightSubjectCategory.group_id)
        ).all()
    else:
        rows = session.execute(
            select(InsightCaseTypeGroup.group_id, func.count()).group_by(InsightCaseTypeGroup.group_id)
        ).all()
    return {gid: int(n) for gid, n in rows}


def _case_counts_by_category(session: Session) -> dict[int, tuple[int, int]]:
    """Live cases and pending (pending or unknown) by the court's category code of the fact rows."""
    rows = session.execute(
        select(
            InsightCaseFact.category_code,
            func.count(),
            func.count().filter(Case.status.in_([CaseStatus.PENDING, CaseStatus.UNKNOWN])),
        )
        .join(Case, Case.id == InsightCaseFact.case_id)
        .where(Case.merged_into_case_id.is_(None), InsightCaseFact.category_code.is_not(None))
        .group_by(InsightCaseFact.category_code)
    ).all()
    return {int(c): (int(n), int(p)) for c, n, p in rows}


def _case_counts_by_type(session: Session) -> dict[uuid.UUID, tuple[int, int]]:
    rows = session.execute(
        select(
            Case.case_type_id,
            func.count(),
            func.count().filter(Case.status.in_([CaseStatus.PENDING, CaseStatus.UNKNOWN])),
        )
        .where(Case.merged_into_case_id.is_(None), Case.case_type_id.is_not(None))
        .group_by(Case.case_type_id)
    ).all()
    return {t: (int(n), int(p)) for t, n, p in rows}


def _group_counts(session: Session, kind: str) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, list[int]]]:
    """(members, [cases, pending]) by group id for one kind: the counting of the list and of every group write."""
    members = _member_counts(session, kind)
    cases: dict[uuid.UUID, list[int]] = {}
    if kind == "subject":
        by_code = _case_counts_by_category(session)
        for gid, code in session.execute(
            select(InsightSubjectCategory.group_id, InsightSubjectCategory.category_code)
            .where(InsightSubjectCategory.group_id.is_not(None))
            .distinct()
        ).all():
            n, p = by_code.get(int(code), (0, 0))
            acc = cases.setdefault(gid, [0, 0])
            acc[0] += n
            acc[1] += p
    else:
        by_type = _case_counts_by_type(session)
        for gid, type_id in session.execute(
            select(InsightCaseTypeGroup.group_id, InsightCaseTypeGroup.case_type_id)
        ).all():
            n, p = by_type.get(type_id, (0, 0))
            acc = cases.setdefault(gid, [0, 0])
            acc[0] += n
            acc[1] += p
    return members, cases


def _line(
    g: InsightGroup, members: dict[uuid.UUID, int], cases: dict[uuid.UUID, list[int]]
) -> dict[str, Any]:
    n, p = cases.get(g.id, [0, 0])
    return {"id": g.id, **group_summary(g), "members": members.get(g.id, 0), "cases": n, "pending": p}


def group_line(session: Session, row: InsightGroup) -> dict[str, Any]:
    """One group's item of `GET /admin/insights/groups`, counted as the list counts it (decision 6 of
    state-insights-review-advisories): the answer of `POST` and `PATCH`."""
    members, cases = _group_counts(session, row.kind)
    return _line(row, members, cases)


def list_groups(session: Session, user: User | Member, kind: str) -> list[dict[str, Any]]:
    """`GET /admin/insights/groups?kind=`: the groups of one kind in their order, each with the number of categories
    or case types it holds and its live cases and pending cases (inactive groups included, marked)."""
    require_groups_admin(session, user)
    kind = _kind(kind)
    members, cases = _group_counts(session, kind)
    rows = session.scalars(
        select(InsightGroup)
        .where(InsightGroup.kind == kind)
        .order_by(InsightGroup.sort_order, InsightGroup.code)
    ).all()
    return [_line(g, members, cases) for g in rows]


def create_group(
    session: Session,
    actor: Actor,
    user: User | Member,
    *,
    kind: str,
    code: str,
    label: str,
    sort_order: int | None = None,
    description: str | None = None,
) -> InsightGroup:
    """A new group (never reserved). 409 `code_taken` / `label_taken`; audited `insights.group_created`."""
    require_groups_admin(session, user)
    kind = _kind(kind)
    code = (code or "").strip()
    if not CODE_RE.match(code):
        raise GroupsError(
            "bad_code", "a code is 2 to 40 lower-case letters, digits or _ and starts with a letter"
        )
    label = _label(label)
    if group_by_code(session, kind, code) is not None:
        raise GroupsError("code_taken", f"the code {code} is taken", 409)
    if _label_taken(session, kind, label):
        raise GroupsError("label_taken", f"the label {label!r} is taken", 409)
    if sort_order is None:
        highest = int(
            session.scalar(
                select(func.coalesce(func.max(InsightGroup.sort_order), 0)).where(InsightGroup.kind == kind)
            )
            or 0
        )
        sort_order = min(highest + 10, SORT_ORDER_MAX)
    else:
        sort_order = _sort_order(sort_order)
    row = InsightGroup(
        kind=kind,
        code=code,
        label=label,
        description=((description or "").strip() or None) and description.strip()[:DESCRIPTION_MAX],
        sort_order=int(sort_order),
        is_reserved=False,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(row)
    session.flush()
    write_audit(session, actor, "insights.group_created", "insight_group", row.id, after=group_summary(row))
    return row


UNSET: Any = object()


def update_group(
    session: Session,
    actor: Actor,
    user: User | Member,
    row: InsightGroup,
    *,
    label: Any = UNSET,
    sort_order: Any = UNSET,
    is_active: Any = UNSET,
    description: Any = UNSET,
) -> InsightGroup:
    """Rename, reorder, (de)activate (decision 14). A reserved group cannot be deactivated (409 `reserved_group`);
    kind, code and the reserved mark never change (also refused by the trigger). A change that changes nothing writes
    nothing; otherwise one `insights.group_updated` row with before and after."""
    require_groups_admin(session, user)
    before = group_summary(row)
    if label is not UNSET and label is not None:
        new_label = _label(label)
        if new_label != row.label:
            if _label_taken(session, row.kind, new_label, but=row.id):
                raise GroupsError("label_taken", f"the label {new_label!r} is taken", 409)
            row.label = new_label
    if sort_order is not UNSET and sort_order is not None and _sort_order(sort_order) != row.sort_order:
        row.sort_order = int(sort_order)
    if description is not UNSET:
        text_ = (description or "").strip()[:DESCRIPTION_MAX] or None
        if text_ != row.description:
            row.description = text_
    if is_active is not UNSET and is_active is not None and bool(is_active) != row.is_active:
        if row.is_reserved and not is_active:
            raise GroupsError("reserved_group", f"{row.code} is reserved and cannot be deactivated", 409)
        row.is_active = bool(is_active)
        row.deactivated_at = None if row.is_active else _now()
    after = group_summary(row)
    if after == before:
        return row
    row.updated_by = actor.user_id
    session.flush()
    write_audit(session, actor, "insights.group_updated", "insight_group", row.id, before=before, after=after)
    return row


def _group_for_change(
    session: Session, kind: str, code: str | None, *, allow_none: bool
) -> InsightGroup | None:
    if code is None or code == "":
        if allow_none:
            return None
        code = "other"
    g = group_by_code(session, kind, code)
    if g is None or not g.is_active:
        raise GroupsError("bad_group", f"no active {kind} group {code!r}")
    return g


def set_categories(
    session: Session, actor: Actor, user: User | Member, changes: list[tuple[int, str | None]]
) -> list[dict[str, Any]]:
    """A batch Save of categories (decision 14): each `(code, group code or None for Not Grouped)` applies to every
    court's row of that category; one `insights.category_grouped` audit row per changed line, none for an unchanged
    one. Takes effect at once (the grouping is joined at query time). Returns each changed code's line as
    `list_categories` shows it, with its live cases and pending."""
    require_groups_admin(session, user)
    changed: list[dict[str, Any]] = []
    groups = {
        g.id: g.code for g in session.scalars(select(InsightGroup).where(InsightGroup.kind == "subject"))
    }
    for code, group_code in changes:
        rows = session.scalars(
            select(InsightSubjectCategory)
            .where(InsightSubjectCategory.category_code == int(code))
            .order_by(InsightSubjectCategory.id)
        ).all()
        if not rows:
            raise GroupsError("not_found", f"no category {code}", 404)
        target = _group_for_change(session, "subject", group_code, allow_none=True)
        target_id = target.id if target is not None else None
        before = sorted({groups.get(r.group_id) for r in rows if r.group_id is not None})
        if all(r.group_id == target_id for r in rows):
            continue
        for r in rows:
            r.group_id = target_id
            r.updated_by = actor.user_id
        session.flush()
        after = target.code if target is not None else None
        write_audit(
            session,
            actor,
            "insights.category_grouped",
            "insight_subject_category",
            rows[0].id,
            before={"code": int(code), "group": before[0] if len(before) == 1 else (before or None)},
            after={"code": int(code), "group": after},
        )
        changed.append({"code": int(code), "label": rows[0].label, "group": after})
    if changed:
        counts = _case_counts_by_category(session)
        for line in changed:
            line["cases"], line["pending"] = counts.get(line["code"], (0, 0))
    return changed


def set_case_types(
    session: Session, actor: Actor, user: User | Member, changes: list[tuple[uuid.UUID, str | None]]
) -> list[dict[str, Any]]:
    """A batch Save of case types: each `(case_type_id, family group code; None = other)`; one
    `insights.case_type_grouped` audit row per changed line. Returns each changed type's line as `list_case_types`
    shows it, with its live cases and pending."""
    require_groups_admin(session, user)
    changed: list[dict[str, Any]] = []
    for type_id, group_code in changes:
        ct = session.get(CaseType, type_id)
        if ct is None:
            raise GroupsError("not_found", f"no case type {type_id}", 404)
        target = _group_for_change(session, "family", group_code, allow_none=False)
        row = session.scalar(select(InsightCaseTypeGroup).where(InsightCaseTypeGroup.case_type_id == ct.id))
        before_group = session.get(InsightGroup, row.group_id).code if row is not None else "other"
        if row is not None and row.group_id == target.id:
            continue
        if row is None:
            # a case type without a row reads as Other; the row records the choice either way
            row = InsightCaseTypeGroup(
                case_type_id=ct.id, group_id=target.id, created_by=actor.user_id, updated_by=actor.user_id
            )
            session.add(row)
        else:
            row.group_id = target.id
            row.updated_by = actor.user_id
        session.flush()
        write_audit(
            session,
            actor,
            "insights.case_type_grouped",
            "insight_case_type_group",
            row.id,
            before={"case_type_code": ct.case_type_code, "group": before_group},
            after={"case_type_code": ct.case_type_code, "group": target.code},
        )
        changed.append(
            {
                "id": ct.id,
                "code": ct.case_type_code,
                "name": ct.short_name or ct.type_name,
                "full_name": ct.full_name or ct.type_name,
                "group": target.code,
            }
        )
    if changed:
        counts = _case_counts_by_type(session)
        for line in changed:
            line["cases"], line["pending"] = counts.get(line["id"], (0, 0))
    return changed


def list_categories(
    session: Session,
    user: User | Member,
    *,
    q: str | None = None,
    group: str | None = None,
    sort: str | None = None,
) -> list[dict[str, Any]]:
    """`GET /admin/insights/categories`: one line per category code (the courts' rows folded), its group (None = Not
    Grouped), live cases and pending; `q` over the code and label, `group` a group code or `not_grouped`, `sort` one of
    `CATEGORY_SORTS` (400 `bad_sort`)."""
    require_groups_admin(session, user)
    lq = list_search.parse(q)
    picked = list_sort.parse_keys(CATEGORY_SORTS, sort, None)
    codes = {
        g.id: g.code for g in session.scalars(select(InsightGroup).where(InsightGroup.kind == "subject"))
    }
    counts = _case_counts_by_category(session)
    lines: dict[int, dict[str, Any]] = {}
    for r in session.scalars(
        select(InsightSubjectCategory).order_by(
            InsightSubjectCategory.category_code, InsightSubjectCategory.id
        )
    ).all():
        line = lines.setdefault(
            r.category_code,
            {
                "code": r.category_code,
                "label": r.label,
                "group": codes.get(r.group_id) if r.group_id else None,
            },
        )
        if line["group"] is None and r.group_id is not None:
            line["group"] = codes.get(r.group_id)
    out = []
    for code, line in lines.items():
        n, p = counts.get(code, (0, 0))
        item = {**line, "cases": n, "pending": p}
        if group == NOT_GROUPED and item["group"] is not None:
            continue
        if group and group != NOT_GROUPED and item["group"] != group:
            continue
        if not list_search.matches(lq, [str(code), item["label"]]):
            continue
        out.append(item)
    return _sorted(out, picked, "code")


def list_case_types(
    session: Session,
    user: User | Member,
    *,
    q: str | None = None,
    group: str | None = None,
    sort: str | None = None,
) -> list[dict[str, Any]]:
    """`GET /admin/insights/case-types`: every case type of the courts, its kind (`other` without a row), live cases
    and pending; `q` over the code and names, `group` a family code, `sort` one of `CASE_TYPE_SORTS`."""
    require_groups_admin(session, user)
    lq = list_search.parse(q)
    picked = list_sort.parse_keys(CASE_TYPE_SORTS, sort, None)
    groups = {
        g.id: g.code for g in session.scalars(select(InsightGroup).where(InsightGroup.kind == "family"))
    }
    mapped = dict(
        session.execute(select(InsightCaseTypeGroup.case_type_id, InsightCaseTypeGroup.group_id)).all()
    )
    counts = _case_counts_by_type(session)
    out = []
    for ct in session.scalars(select(CaseType).order_by(CaseType.case_type_code, CaseType.id)).all():
        gid = mapped.get(ct.id)
        code = groups.get(gid) if gid is not None else "other"
        n, p = counts.get(ct.id, (0, 0))
        item = {
            "id": ct.id,
            "code": ct.case_type_code,
            "name": ct.short_name or ct.type_name,
            "full_name": ct.full_name or ct.type_name,
            "group": code,
            "cases": n,
            "pending": p,
        }
        if group and item["group"] != group:
            continue
        if not list_search.matches(lq, [str(ct.case_type_code), item["name"], item["full_name"]]):
            continue
        out.append(item)
    return _sorted(out, picked, "code")


def _sorted(
    items: list[dict[str, Any]], picked: tuple[str, str] | None, default: str
) -> list[dict[str, Any]]:
    key, direction = picked or (default, "asc")
    present = [i for i in items if i.get(key) is not None]
    blank = [i for i in items if i.get(key) is None]

    def k(i: dict[str, Any]):
        v = i[key]
        return (v.lower() if isinstance(v, str) else v, i["code"])

    present.sort(key=k, reverse=direction == "desc")
    return present + blank


# ------------------------------------------------------------------------------------------------ the seed


def seed(session: Session, report) -> None:
    """The groups, the categories of every court with `ref_code = 'GHC'` and the case-type lines of those courts'
    `case_types` rows (the same lists as migration 0039); inserts only what is missing, never changes a row a person
    edited. No audit row (reference data, the 0016 precedent). On a database older than migration 0039 (no
    `insight_groups` table yet) it does nothing."""
    if not sa_inspect(session.connection()).has_table("insight_groups"):
        report.notes.append("insight groups not seeded: migration 0039 not applied")
        return
    reserved = set(RESERVED_GROUPS)
    have = {(g.kind, g.code): g for g in session.scalars(select(InsightGroup))}
    for kind, groups in (("family", SEED_FAMILY_GROUPS), ("subject", SEED_SUBJECT_GROUPS)):
        for order, (code, label) in enumerate(groups, start=1):
            if (kind, code) in have:
                continue
            row = InsightGroup(
                kind=kind, code=code, label=label, sort_order=order * 10, is_reserved=(kind, code) in reserved
            )
            session.add(row)
            have[(kind, code)] = row
            report.add("insight_groups")
    session.flush()
    courts = session.scalars(select(Court).where(Court.ref_code == COURT_REF_CODE)).all()
    for court in courts:
        held = set(
            session.scalars(
                select(InsightSubjectCategory.category_code).where(
                    InsightSubjectCategory.court_id == court.id
                )
            ).all()
        )
        for code, label, group in SEED_CATEGORIES:
            if code in held:
                continue
            session.add(
                InsightSubjectCategory(
                    court_id=court.id, category_code=code, label=label, group_id=have[("subject", group)].id
                )
            )
            report.add("insight_subject_categories")
    session.flush()
    placed = place_seed_case_types(session)
    if placed:
        report.add("insight_case_type_groups", placed)


def _seed_case_types_missing(session: Session) -> list[tuple[CaseType, InsightGroup]]:
    """The `case_types` rows of the courts with `ref_code = 'GHC'` whose code is in `SEED_CASE_TYPES` and which have
    no `insight_case_type_groups` row, each with the family group of its seed line (a type whose group is not held is
    left out)."""
    seeded = dict(SEED_CASE_TYPES)
    groups = {g.code: g for g in session.scalars(select(InsightGroup).where(InsightGroup.kind == "family"))}
    courts = select(Court.id).where(Court.ref_code == COURT_REF_CODE)
    rows = session.scalars(
        select(CaseType)
        .where(
            CaseType.court_id.in_(courts),
            CaseType.case_type_code.in_(list(seeded)),
            ~exists().where(InsightCaseTypeGroup.case_type_id == CaseType.id),
        )
        .order_by(CaseType.case_type_code, CaseType.id)
    ).all()
    return [(ct, groups[seeded[ct.case_type_code]]) for ct in rows if seeded[ct.case_type_code] in groups]


def count_seed_case_types_missing(session: Session) -> int:
    """How many seed case-type lines `place_seed_case_types` would place now (the dry run and `groups check`)."""
    return len(_seed_case_types_missing(session))


def seed_case_types_missing(session: Session) -> list[tuple[int, str, str]]:
    """(case_type_code, name, seed group code) of every line `place_seed_case_types` would place (`groups check`)."""
    return [
        (ct.case_type_code, ct.short_name or ct.type_name, g.code)
        for ct, g in _seed_case_types_missing(session)
    ]


def place_seed_case_types(session: Session) -> int:
    """Decision 5 of state-insights-review-advisories: the seed line of every seeded case type of the Gauhati High
    Court that has none, so a type the court masters sync created after `init` is no longer read as Other. It never
    changes an existing line (a Super Administrator's choice, even Other, is always a row). Reference data, the same
    lines the migration and the seed write: no audit row. Returns the number placed."""
    missing = _seed_case_types_missing(session)
    if not missing:
        return 0
    placed = session.scalars(
        pg_insert(InsightCaseTypeGroup)
        .values([{"case_type_id": ct.id, "group_id": g.id} for ct, g in missing])
        .on_conflict_do_nothing(index_elements=["case_type_id"])
        .returning(InsightCaseTypeGroup.id)
    ).all()
    session.flush()
    return len(placed)

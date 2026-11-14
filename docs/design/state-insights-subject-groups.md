# Draft: the court's subject categories in subject groups (State Insights, decision 5)

Draft for the owner's review, made by the architect on 14 Nov 2026 from the dev database (read-only query of the
distinct `cases.category` values of live cases). The court prints each category as `<code> - <label> ( <n> )`; the
five-digit code is the key. Migration and seed load this list into `insight_subject_categories` (design
`docs/design/state-insights.md`, Data); the Super Administrator can change any line later on Administration →
Insights Groups, each change audited. A category the court adds later arrives in no group ("Not Grouped") until
someone places it. A contempt case whose original writ is read from its orders takes that writ's subject (decision 15).

235 categories with a code; 3,273 cases (2,924 pending) have no category or a malformed one
and are shown as "No Category", never guessed.

## The groups

| # | Code | Group | Categories | Cases | Pending |
|---|---|---|---|---|---|
| 1 | `service_state` | Service: State Government Employees | 20 | 5,187 | 2,600 |
| 2 | `service_teachers` | Service: Teachers of Provincialised Schools | 22 | 4,491 | 2,248 |
| 3 | `service_public_bodies` | Service: Local Bodies, Undertakings, Universities and Defence | 24 | 2,519 | 1,367 |
| 4 | `education` | Education and Academic Matters | 18 | 508 | 232 |
| 5 | `land_revenue` | Land and Revenue | 15 | 3,079 | 1,400 |
| 6 | `foreigners` | Foreigners Tribunal and Citizenship | 2 | 4,234 | 3,484 |
| 7 | `tax` | Tax and Duties | 18 | 1,174 | 526 |
| 8 | `contracts_licences` | Contracts, Settlements and Licences | 19 | 3,167 | 825 |
| 9 | `local_bodies_elections` | Panchayat, Municipal, Elections and Co-operatives | 11 | 595 | 163 |
| 10 | `labour` | Labour and Industrial | 13 | 383 | 221 |
| 11 | `criminal` | Criminal Matters and Bail | 18 | 23,986 | 6,594 |
| 12 | `civil` | Civil Appeals, Revisions and Suits | 30 | 9,089 | 6,047 |
| 13 | `rights_public_interest` | Rights, Detention and Public Interest | 7 | 410 | 195 |
| 14 | `contempt` | Contempt (Original Subject Not Yet Known) | 4 | 2,996 | 1,575 |
| 15 | `other` | Other Writ and Procedural Matters | 14 | 18,850 | 6,798 |

Merging the three service groups into one "Service Matters" would give 13 groups; the draft keeps them apart because
they are a quarter of the State's pending writs and answer to different departments.

## Every category

### Service: State Government Employees (`service_state`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10021 | Ad hoc appointment with respect to State Govt Employees. | 2 | 2 |
| 10022 | Regularisation of ad hoc appointment with respect to State Govt Employees. | 197 | 114 |
| 10023 | Selection and appointment with respect to State Govt Employees. | 850 | 433 |
| 10024 | Appointment on compassionate ground on non-educational matter. | 489 | 171 |
| 10025 | Appointment of family members of victim extremists violence | 4 | 2 |
| 10026 | Salary and allowancest with respect to State Govt Employees. | 427 | 227 |
| 10027 | Seniority with respect to State Govt Employees. | 79 | 36 |
| 10028 | Promotion with respect to State Govt Employees. | 495 | 224 |
| 10029 | Reservation of vacancies with respect to State Govt Employees. | 4 | 2 |
| 10030 | Transfer with respect to State Govt Employees. | 175 | 54 |
| 10031 | Suspension with respect to State Govt Employees. | 221 | 84 |
| 10032 | Disciplinary and enquiry proceedings with respect to State Govt Employees. | 179 | 90 |
| 10033 | Minor punishment with respect to State Govt Employees. | 39 | 21 |
| 10034 | Major punishment with respect to State Govt Employees. | 368 | 216 |
| 10035 | Compulsory retirement with respect to State Govt Employees. | 9 | 7 |
| 10036 | Order of the Appellate or Reisional authority with respect to State Govt Employees. | 6 | 0 |
| 10037 | Order of the Administrative or service Tribunal with respect to State Govt Employees. | 8 | 2 |
| 10038 | Date of birth with respect to State Govt Employees. | 22 | 11 |
| 10039 | Retirement benefits with respect to State Govt Employees. | 867 | 473 |
| 10040 | Other service matters with respect to State Govt Employees. | 746 | 431 |

### Service: Teachers of Provincialised Schools (`service_teachers`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10001 | Ad hoc appointment with respect to Service of Teachers of Provincialized Schools. | 6 | 2 |
| 10002 | Regularisation of ad hoc appointment with respect to Service of Teachers of Provincialized Schools. | 166 | 107 |
| 10003 | Selection and appointment with respect to Service of Teachers of Provincialized Schools. | 619 | 286 |
| 10004 | Appointment in retired teachers quota with respect to Service of Teachers of Provincialized Schools. | 3 | 1 |
| 10005 | Appointment on compassionate ground on Educational Matter with respect to Service of Teachers of Provincialized Schools. | 416 | 103 |
| 10006 | Appointment of family members of victim of extremist violence with respect to Service of Teachers of Provincialized Schools. | 1 | 0 |
| 10007 | Regular appointment of honorary teacher with respect to Service of Teachers of Provincialized Schools. | 19 | 9 |
| 10008 | Salary and allowances with respect to Service of Teachers of Provincialized Schools. | 743 | 410 |
| 10009 | Seniority with respect to Service of Teachers of Provincialized Schools. | 69 | 32 |
| 10010 | Promotion with respect to Service of Teachers of Provincialized Schools. | 257 | 110 |
| 10011 | Transfer with respect to Service of Teachers of Provincialized Schools. | 138 | 32 |
| 10012 | Suspension with respect to Service of Teachers of Provincialized Schools. | 88 | 39 |
| 10013 | Disciplinary and enquiry proceedings with respect to Service of Teachers of Provincialized Schools. | 78 | 50 |
| 10014 | Minor punishment with respect to Service of Teachers of Provincialized Schools. | 10 | 7 |
| 10015 | Major punishment with respect to Service of Teachers of Provincialized Schools. | 56 | 38 |
| 10016 | Date of birth with respect to Service of Teachers of Provincialized Schools. | 25 | 12 |
| 10017 | Retirement benefits with respect to Service of Teachers of Provincialized Schools. | 496 | 306 |
| 10018 | Orders passed by the Director with respect to Service of Teachers of Provincialized Schools. | 129 | 47 |
| 10019 | Orders passed by any other educational authority with respect to Service of Teachers of Provincialized Schools. | 105 | 54 |
| 10020 | Other service matters with respect to Service of Teachers of Provincialized Schools. | 618 | 358 |
| 10096 | Provincialisation of Schools | 38 | 15 |
| 10098 | Provincialisation of staff of schools | 411 | 230 |

### Service: Local Bodies, Undertakings, Universities and Defence (`service_public_bodies`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10041 | Ad hoc appointment with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and | 4 | 3 |
| 10042 | Regularisation of ad hoc appointment with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and | 43 | 32 |
| 10043 | Selection and appointment with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universiti | 472 | 175 |
| 10044 | Appointment on compassionate ground with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and | 39 | 18 |
| 10046 | Salary and allowances with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities a | 227 | 156 |
| 10047 | Seniority with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and Instituti | 18 | 13 |
| 10048 | Promotion with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and Instituti | 96 | 49 |
| 10049 | Reservation of vacancies with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universitie | 7 | 2 |
| 10050 | Transfer with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and Institutio | 119 | 26 |
| 10051 | Suspension with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and Institut | 43 | 26 |
| 10052 | Disciplinary and enquiry proceedings with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and | 92 | 57 |
| 10053 | Minor punishment with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and In | 38 | 27 |
| 10054 | Major punishment with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and In | 300 | 190 |
| 10055 | Compulsory retirement with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities a | 24 | 15 |
| 10057 | Order of the Appellate or Revisional authority with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory | 257 | 143 |
| 10058 | Date of birth with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and Insti | 3 | 0 |
| 10059 | Retirement benefits with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities and | 314 | 192 |
| 10060 | Other service matters with respect to Service of Local Bodies, Banks, State & Central Public Sector Undertaking, Statutory Bodies and Universities a | 407 | 235 |
| 10063 | Selection and appointment relating to service of Defence Personal and Armed Forces. | 2 | 1 |
| 10066 | Salary and allowances relating to service of Defence Personal and Armed Forces. | 1 | 1 |
| 10068 | Promotion relating to service of Defence Personal and Armed Forces. | 1 | 1 |
| 10074 | Major punishment relating to service of Defence Personal and Armed Forces. | 5 | 2 |
| 10079 | Retirement benefits relating to service of Defence Personal and Armed Forces. | 2 | 1 |
| 10080 | Other service matters relating to service of Defence Personal and Armed Forces. | 5 | 2 |

### Education and Academic Matters (`education`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10081 | Admissions in MBBS or BDS Course in Medical and Dental College | 27 | 13 |
| 10082 | Admissions in Post Graduate Degree and Diploma courses in Medical College | 9 | 3 |
| 10083 | Admissions in Engineering Colleges. | 2 | 0 |
| 10084 | Admissions in other Institutions. | 13 | 10 |
| 10085 | With-holding and cancellation of results. | 7 | 3 |
| 10086 | Evaluation and totalling of marks in Examination. | 13 | 3 |
| 10087 | Mal-practice at the time of Examination. | 2 | 1 |
| 10088 | Examination Centre. | 6 | 0 |
| 10089 | Expulsion of students from academic Institutions. | 9 | 2 |
| 10090 | Other academic disputes. | 198 | 85 |
| 10091 | Governing Body of aided Colleges. | 4 | 3 |
| 10092 | Governing Body of other Colleges. | 2 | 0 |
| 10093 | Managing Committee of aided Schools | 12 | 8 |
| 10094 | Managing Committee of other Schools. | 18 | 4 |
| 10095 | Permission for and Recognition of Schools and Colleges | 18 | 9 |
| 10097 | Grants in Aid to Schools | 10 | 4 |
| 10099 | Orders passed by authorities in relation to Mangmnt of Schools & Colleges | 53 | 27 |
| 10100 | Other disputes relating to Management of academic Institutions | 105 | 57 |

### Land and Revenue (`land_revenue`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10149 | Orders passed by the Assam Board of Revenue in appeal. | 32 | 19 |
| 10150 | Orders passed by the Government in appeals. | 4 | 1 |
| 10151 | Acquisition of land. | 295 | 150 |
| 10152 | Requisition of land. | 27 | 15 |
| 10153 | Settlement of land. | 280 | 130 |
| 10154 | Eviction from land. | 723 | 299 |
| 10155 | Orders passed under the Urban Land (Ceiling Regulation Act,1976) | 1 | 0 |
| 10156 | Orders for demolition of unauthorised construction on land | 82 | 46 |
| 10157 | Sale of land by member of Schedule Tribe. | 4 | 2 |
| 10158 | Issue of patta in respect of land. | 40 | 19 |
| 10159 | Orders passed by the Board of Revenue in land matters. | 41 | 30 |
| 10160 | Other land matters relating to Land Matters. | 941 | 423 |
| 10162 | Recovery of other dues under the Public Demand Recovery Act | 148 | 34 |
| 10183 | Compensations relating to Land Matters. | 414 | 209 |
| 10187 | Eviction from House. | 47 | 23 |

### Foreigners Tribunal and Citizenship (`foreigners`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10176 | Oders of Foreigners Tribunal/Illegal Migrant(D) Tribunal | 4,228 | 3,484 |
| 10310 | Citizenship, NRC, push back/deportation and other ancillary matters | 6 | 0 |

### Tax and Duties (`tax`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10101 | Sales Tax | 364 | 184 |
| 10103 | Income Tax | 98 | 62 |
| 10104 | Central Excise | 52 | 21 |
| 10105 | Motor Vehicle Tax | 3 | 0 |
| 10107 | Gift Tax | 1 | 0 |
| 10109 | Purchase Tax | 1 | 1 |
| 10110 | Municipal Tax | 2 | 0 |
| 10111 | Custom Duty | 6 | 2 |
| 10114 | Octroi | 29 | 24 |
| 10115 | Licence Fee | 5 | 1 |
| 10116 | Penalty | 28 | 12 |
| 10117 | Confiscation | 8 | 2 |
| 10118 | Seizure | 45 | 7 |
| 10119 | Check Gate | 1 | 1 |
| 10120 | Other Tax matters. | 522 | 207 |
| 10271 | Reference under section 256(1) of the Income-Tax Act 1961 | 1 | 1 |
| 10281 | References under the Agricultural Income-tax Act to the High Court | 2 | 0 |
| 10300 | Revision Petition u/s 81 of the Assam Value Added Tax Act2003. | 6 | 1 |

### Contracts, Settlements and Licences (`contracts_licences`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10140 | Settlement of Fishery by the State Govt. | 103 | 25 |
| 10141 | Settlement of Fishery by the Assam Fisheries Development Corporation | 55 | 13 |
| 10142 | Settlement of Country Liquor Shop. | 5 | 1 |
| 10143 | Settlement of Foreign Liquor Shop. | 63 | 20 |
| 10144 | Settlement of Markets. | 142 | 29 |
| 10145 | Settlement of Sand Mahal. | 31 | 9 |
| 10146 | Settlement of Quarry. | 31 | 10 |
| 10147 | Settlement of Forest Produce. | 20 | 2 |
| 10148 | Other settlements relating to settlements made by the State Govt and Other Authorities.. | 451 | 109 |
| 10163 | Electricity Disputes. | 122 | 49 |
| 10164 | Requisition of vehicles. | 19 | 4 |
| 10165 | Payment of bills in respect of requisitioned vehicles. | 112 | 14 |
| 10166 | Permit of vehicles. | 3 | 1 |
| 10167 | Payment of road tax. | 1 | 1 |
| 10175 | Orders under the Essential Commodities Act. | 22 | 4 |
| 10177 | Transit passes for Forest Produce. | 3 | 1 |
| 10180 | Award of contracts by the State or its instrumentalities | 1,560 | 360 |
| 10181 | Subsidy Matters. | 113 | 96 |
| 10184 | License and Permissions. | 311 | 77 |

### Panchayat, Municipal, Elections and Co-operatives (`local_bodies_elections`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10168 | No confidence motion passed by Panchayat. | 18 | 2 |
| 10169 | Other cases under the Panchayat Acts. | 204 | 59 |
| 10170 | Election of Municipal Boards/Corporation. | 15 | 6 |
| 10171 | Election of members of Panchayat. | 97 | 36 |
| 10172 | Election of office bearers of Co-Operative Societies. | 28 | 13 |
| 10173 | Annual General Meeting of Co-Operative Societies. | 35 | 13 |
| 10174 | Orders passed by the authorities under the Co-Operative Societies Act | 71 | 29 |
| 10182 | Dissolution of Autonomous Council Local Bodies | 3 | 1 |
| 10185 | Electoral Roll & Voters List. | 121 | 2 |
| 10206 | Election Petitions relating to election of members of Legislative assembly | 2 | 1 |
| 10207 | Election Petitions relating to election of members of Lok Sabha | 1 | 1 |

### Labour and Industrial (`labour`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10121 | Industrial Disputes Act, 1947. | 65 | 32 |
| 10122 | Trade Union Act, 1926. | 5 | 2 |
| 10123 | Workmen Compensation Act, 1923. | 8 | 4 |
| 10124 | Employees State Insurance Act, 1948. | 18 | 7 |
| 10125 | Factories Act, 1948. | 2 | 2 |
| 10126 | Employmees Provident Funds and Misc. Provision act, 19 | 25 | 6 |
| 10127 | Payment of Gratuity Act, 1962. | 10 | 6 |
| 10128 | Payment of Bonus Act, 1965. | 4 | 2 |
| 10129 | Payment of Wages Act, 1936. | 17 | 8 |
| 10131 | Contract Labour (Regulation Payment) Act, 1970. | 4 | 3 |
| 10132 | Other Labour and Industrial Cases. | 65 | 25 |
| 10225 | Appeals under the Workmen Compensation Act, 1923. | 145 | 112 |
| 10227 | Appeals under the Employees State Insurance Act, 1948. | 15 | 12 |

### Criminal Matters and Bail (`criminal`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10250 | Appeals against conviction for offences under IPC. | 1,601 | 1,267 |
| 10251 | Appeals against acquittal. | 370 | 284 |
| 10252 | Appeals against conviction under the NDPS Act. | 84 | 62 |
| 10253 | Appeals against conviction under other Acts. | 378 | 318 |
| 10255 | Criminal Appeals (Jail) | 391 | 284 |
| 10259 | Criminal reference (Hills) | 2 | 2 |
| 10260 | Criminal Revisions against acquittal. | 10 | 8 |
| 10261 | Criminal Revisions against orders passed in trial cases | 1,637 | 1,009 |
| 10262 | Criminal Revisions in respect of orders passed in cases | 251 | 155 |
| 10263 | Criminal Revisions for quashing of criminal proceeding | 4,596 | 2,365 |
| 10265 | Other Criminal revisions | 31 | 22 |
| 10266 | Bail Application | 8,080 | 339 |
| 10267 | Anticipatory bail Application | 6,384 | 385 |
| 10268 | Other Criminal mis. Cases under Section 482 | 9 | 4 |
| 10269 | Applications for transfer Of Criminal cases | 134 | 78 |
| 10285 | Confirmation Of Death sentence | 10 | 1 |
| 10309 | Appeals preferred under Section 42 of the Prevention of Money-Laundering Act, 2002 | 1 | 0 |
| 10311 | Cases preferred for Cancellation of Bail granted by the learned Trial Court | 17 | 11 |

### Civil Appeals, Revisions and Suits (`civil`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10203 | Company Petitions | 3 | 2 |
| 10205 | Testamentary cases. | 3 | 2 |
| 10209 | Execution cases in succession matters etc. | 1 | 1 |
| 10220 | Family Court Appeals. | 276 | 193 |
| 10221 | Appeals under order 43 Rule 1 CPC relating to temporar injunction | 81 | 44 |
| 10222 | Other appeals under Order 43 Rule 1 CPC in temporary | 167 | 104 |
| 10223 | Appeals from motor accident claims tribunal. | 3,111 | 2,325 |
| 10224 | Appeal from Railway Claims Tribunal | 332 | 266 |
| 10226 | Appeals under the Local Rent Control Acts. | 1 | 0 |
| 10228 | Appeals against Original Decrees. | 360 | 306 |
| 10229 | Other First Appeals. | 260 | 162 |
| 10230 | Second Appeals arising out of suits for title and/or injunction | 1,442 | 1,165 |
| 10231 | Second Appeals arising out of suits for specific enforcement of contract | 8 | 6 |
| 10232 | Second Appeals arising out of suits in respect of service matters | 4 | 3 |
| 10233 | Second appeals arising out of suits in respect other matters | 20 | 14 |
| 10234 | Second Appeals against orders MA(S) | 8 | 7 |
| 10236 | Appeals under the Companies Act, 1956. | 2 | 0 |
| 10240 | Civil Revision against orders passed by Civil Court in suits | 70 | 37 |
| 10241 | Civil Revision against appellate decree under the Local Rent Control Act | 9 | 1 |
| 10242 | Civil Revision against orders in cases filed under section 6 of the specific Relief Act | 1 | 0 |
| 10243 | Civil Revision against orders passed in execution case | 407 | 228 |
| 10244 | Civil Revision under Article 227 of the Constitution. | 1,839 | 782 |
| 10245 | Civil Revisions for transfer of suit under Section 24 of the CPC | 365 | 206 |
| 10246 | Other Civil Revisions. | 71 | 57 |
| 10247 | Arbitration Cases | 185 | 104 |
| 10303 | Restoration of a case dismissed for default. | 44 | 15 |
| 10305 | RERA APPEAL matter | 16 | 15 |
| 10306 | Commercial Appellate Division Cases | 1 | 0 |
| 10307 | Hill Appeal | 1 | 1 |
| 10308 | CS(OS) | 1 | 1 |

### Rights, Detention and Public Interest (`rights_public_interest`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10186 | Army & Police Action. | 40 | 20 |
| 10190 | Habeas Corpus - Non-production of a person before the Magistrate after arrest | 8 | 0 |
| 10191 | Detention under the Prevention Detention Law. | 11 | 2 |
| 10192 | Death after detention in custody. | 17 | 9 |
| 10193 | Other Habeas Corpus petitions. | 79 | 29 |
| 10194 | Public Interest Litigations. | 253 | 135 |
| 10195 | Compensation for custodial violence, torture etc. | 2 | 0 |

### Contempt (Original Subject Not Yet Known) (`contempt`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10200 | Contempt Petition (Civil). | 2,982 | 1,567 |
| 10201 | Contempt Petition (Criminal) | 5 | 4 |
| 10202 | Comtempt Petition (Sub Moto) | 8 | 4 |
| 10238 | Contempt Appeal | 1 | 0 |

### Other Writ and Procedural Matters (`other`)

| Code | Court's category | Cases | Pending |
|---|---|---|---|
| 10178 | Telephone Disputes. | 2 | 0 |
| 10179 | Disputes against the Railways. | 39 | 13 |
| 10188 | Challenge to Orders passed by dist. & state govt. authority | 59 | 30 |
| 10189 | Other Civil Rules relating to other Writ Petitions. | 2,915 | 1,175 |
| 10237 | Writ Appeals under the Gauhati High Court Rules. | 1,339 | 532 |
| 10295 | Review Applications In Civil Rule | 494 | 168 |
| 10296 | Review Application in First Appeal | 50 | 28 |
| 10297 | Review Application in Second Appeal | 18 | 12 |
| 10298 | Review Application in Civil Revision | 35 | 15 |
| 10299 | Other Review Applications | 63 | 23 |
| 10301 | Interlocutory Application (Civil) | 10,818 | 3,868 |
| 10302 | Interlocutory Application (Criminal) | 3,004 | 929 |
| 10304 | Review. | 13 | 5 |
| 99999 | COVID Related Matters | 1 | 0 |

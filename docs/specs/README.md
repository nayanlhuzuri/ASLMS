# NAPIX API resources

The court data of ASLMS comes from the NAPIX gateway (eCourts APIs of the e-Committee). This folder keeps every
reference file for those APIs. How the APIs actually behave, verified by live calls, is in
[`docs/napix_integration_notes.md`](../napix_integration_notes.md); it overrides the specifications where they differ.

| Folder or file | What it holds |
|---|---|
| [`napix/hc/`](napix/hc/) | Gateway stubs of the 22 **High Court** APIs (received as "High Court Case Status API") |
| [`napix/dc/`](napix/dc/) | Gateway stubs of the 26 **District Court** APIs (received as "District Court Case Status API", 3 Nov 2026) |
| [`pdf/`](pdf/) | The e-Committee specifications (High Court v1.0, eCourts District Court v1.3) and the NAPIX subscriber manual |
| [`samples/`](samples/) | Decrypted answers saved from live calls (no credentials) |
| [`napix_field_inventory.md`](napix_field_inventory.md) | Every NAPIX field and its home in the database |
| [`../postman/`](../postman/) | The Postman collection |

The stubs describe the request envelope only (`dept_id`, `request_str`, `request_token`, `version`), not the fields of
the answer. The fields come from the PDF specifications and must be confirmed by a live call before any code uses them.
The High Court and District Court APIs each have their own allowance of 1,000 calls an hour (owner, 3 Nov 2026).

## High Court APIs

| API | Stub | Use in ASLMS |
|---|---|---|
| `hc-act-details-api` | [hc-act-details-api_1.0.0.json](hc/hc-act-details-api_1.0.0.json) | not tried |
| `hc-act-master-api` | [hc-act-master-api_1.0.0.json](hc/hc-act-master-api_1.0.0.json) | in use |
| `hc-advocate-bar-reg-api` | [hc-advocate-bar-reg-api_1.0.0.json](hc/hc-advocate-bar-reg-api_1.0.0.json) | not tried |
| `hc-advocate-name-api` | [hc-advocate-name-api_1.0.0.json](hc/hc-advocate-name-api_1.0.0.json) | in use |
| `hc-bench-master-api` | [hc-bench-master-api_1.0.0.json](hc/hc-bench-master-api_1.0.0.json) | in use |
| `hc-case-search-api` | [hc-case-search-api_1.0.0.json](hc/hc-case-search-api_1.0.0.json) | in use |
| `hc-case-type-master-api` | [hc-case-type-master-api_1.0.0.json](hc/hc-case-type-master-api_1.0.0.json) | in use |
| `hc-causelist-bench-api` | [hc-causelist-bench-api_1.0.0.json](hc/hc-causelist-bench-api_1.0.0.json) | in use |
| `hc-causelist-details-api` | [hc-causelist-details-api_1.0.0.json](hc/hc-causelist-details-api_1.0.0.json) | in use |
| `hc-caveat-details-api` | [hc-caveat-details-api_1.0.0.json](hc/hc-caveat-details-api_1.0.0.json) | live test running (row 223) |
| `hc-caveat-name-api` | [hc-caveat-name-api_1.0.0.json](hc/hc-caveat-name-api_1.0.0.json) | live test running (row 223) |
| `hc-cnr-api` | [hc-cnr-api_1.0.0.json](hc/hc-cnr-api_1.0.0.json) | in use |
| `hc-current-status-api` | [hc-current-status-api_1.0.0.json](hc/hc-current-status-api_1.0.0.json) | in use |
| `hc-district-api` | [hc-district-api_1.0.0.json](hc/hc-district-api_1.0.0.json) | in use |
| `hc-filing-api` | [hc-filing-api_1.0.0.json](hc/hc-filing-api_1.0.0.json) | in use |
| `hc-nuetral-citation-number-api` | [hc-nuetral-citation-number-api_1.0.0.json](hc/hc-nuetral-citation-number-api_1.0.0.json) | not tried |
| `hc-order-api` | [hc-order-api_1.0.0.json](hc/hc-order-api_1.0.0.json) | in use |
| `hc-party-name-api` | [hc-party-name-api_1.0.0.json](hc/hc-party-name-api_1.0.0.json) | in use |
| `hc-show-business-api` | [hc-show-business-api_1.0.0.json](hc/hc-show-business-api_1.0.0.json) | tested live, not used yet (row 221) |
| `hc-show-causelist-api` | [hc-show-causelist-api_1.0.0.json](hc/hc-show-causelist-api_1.0.0.json) | in use |
| `hc-state-api` | [hc-state-api_1.0.0.json](hc/hc-state-api_1.0.0.json) | in use |
| `overview` | [overview_1.0.0.json](hc/overview_1.0.0.json) | in use (window probe) |

## District Court APIs

District Court cases are plan Phase 3, civil and criminal (owner, 3 Nov 2026).

| API | Stub | Use in ASLMS |
|---|---|---|
| `dc-act-api` | [dc-act-api_1.0.0.json](dc/dc-act-api_1.0.0.json) | not called yet (row 222) |
| `dc-act-master-api` | [dc-act-master-api_1.0.0.json](dc/dc-act-master-api_1.0.0.json) | not called yet (row 222) |
| `dc-advocate-bar-reg-api` | [dc-advocate-bar-reg-api_1.0.0.json](dc/dc-advocate-bar-reg-api_1.0.0.json) | not called yet (row 222) |
| `dc-advocate-causelist-api` | [dc-advocate-causelist-api_1.0.0.json](dc/dc-advocate-causelist-api_1.0.0.json) | not called yet (row 222) |
| `dc-advocate-name-api` | [dc-advocate-name-api_1.0.0.json](dc/dc-advocate-name-api_1.0.0.json) | not called yet (row 222) |
| `dc-case-number-api` | [dc-case-number-api_1.0.0.json](dc/dc-case-number-api_1.0.0.json) | not called yet (row 222) |
| `dc-casetype-master-api` | [dc-casetype-master-api_1.0.0.json](dc/dc-casetype-master-api_1.0.0.json) | not called yet (row 222) |
| `dc-causelist-api` | [dc-causelist-api_1.0.0.json](dc/dc-causelist-api_1.0.0.json) | not called yet (row 222) |
| `dc-caveat-details-api` | [dc-caveat-details-api_1.0.0.json](dc/dc-caveat-details-api_1.0.0.json) | not called yet (row 222) |
| `dc-caveat-name-api` | [dc-caveat-name-api_1.0.0.json](dc/dc-caveat-name-api_1.0.0.json) | not called yet (row 222) |
| `dc-caveat-number-api` | [dc-caveat-number-api_1.0.0.json](dc/dc-caveat-number-api_1.0.0.json) | not called yet (row 222) |
| `dc-cnr-api` | [dc-cnr-api_1.0.0.json](dc/dc-cnr-api_1.0.0.json) | not called yet (row 222) |
| `dc-court-complex-api` | [dc-court-complex-api_1.0.0.json](dc/dc-court-complex-api_1.0.0.json) | not called yet (row 222) |
| `dc-court-list-api` | [dc-court-list-api_1.0.0.json](dc/dc-court-list-api_1.0.0.json) | not called yet (row 222) |
| `dc-current-status-api` | [dc-current-status-api_1.0.0.json](dc/dc-current-status-api_1.0.0.json) | not called yet (row 222) |
| `dc-district-api` | [dc-district-api_1.0.0.json](dc/dc-district-api_1.0.0.json) | not called yet (row 222) |
| `dc-filing-date-api` | [dc-filing-date-api_1.0.0.json](dc/dc-filing-date-api_1.0.0.json) | not called yet (row 222) |
| `dc-filing-number-api` | [dc-filing-number-api_1.0.0.json](dc/dc-filing-number-api_1.0.0.json) | not called yet (row 222) |
| `dc-fir-number-api` | [dc-fir-number-api_1.0.0.json](dc/dc-fir-number-api_1.0.0.json) | not called yet (row 222) |
| `dc-oreder-api` | [dc-oreder-api_1.0.0.json](dc/dc-oreder-api_1.0.0.json) | not called yet (row 222) |
| `dc-party-name-api` | [dc-party-name-api_1.0.0.json](dc/dc-party-name-api_1.0.0.json) | not called yet (row 222) |
| `dc-police-station-master` | [dc-police-station-master_1.0.0.json](dc/dc-police-station-master_1.0.0.json) | not called yet (row 222) |
| `dc-register-date-api` | [dc-register-date-api_1.0.0.json](dc/dc-register-date-api_1.0.0.json) | not called yet (row 222) |
| `dc-show-business-api` | [dc-show-business-api_1.0.0.json](dc/dc-show-business-api_1.0.0.json) | not called yet (row 222) |
| `overview` | [overview_1.0.0.json](dc/overview_1.0.0.json) | not called yet (row 222) |
| `state-api` | [state-api_1.0.0.json](dc/state-api_1.0.0.json) | not called yet (row 222) |

Keep the "Use in ASLMS" column in step with section 7 of the integration notes when an API is verified or taken into use.

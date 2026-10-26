/**
 * A synthetic answer for any `GET` the portal makes, built from the API's own OpenAPI document (`frontend/openapi.json`,
 * the file `npm run gen:api` turns into `schema.d.ts`), so every field the screens read is present with a value of
 * the right type. Values are chosen to stress the layout (design portal-ui-polish, decision 20): in every list the
 * first row is the stress row (a party line of about 160 characters, a 60-character office name, the longest case
 * number shape, a 40-character designation, counts above 1,00,000 in the Indian grouping); the other rows are plain.
 * No real party, note or person appears: every value is made up here.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

type Schema = {
  $ref?: string;
  type?: string | string[];
  format?: string;
  enum?: unknown[];
  items?: Schema;
  properties?: Record<string, Schema>;
  required?: string[];
  additionalProperties?: boolean | Schema;
  anyOf?: Schema[];
  oneOf?: Schema[];
  allOf?: Schema[];
  const?: unknown;
  default?: unknown;
};

interface OpenApi {
  paths: Record<string, Record<string, { responses?: Record<string, { content?: Record<string, { schema?: Schema }> }> }>>;
  components: { schemas: Record<string, Schema> };
}

const DOC: OpenApi = JSON.parse(readFileSync(join(__dirname, "..", "..", "openapi.json"), "utf-8")) as OpenApi;

export const STRESS = {
  party:
    "SRI RAMESWAR KALITA AND 14 OTHERS, RESIDENTS OF VILLAGE NO. 2 BORBARI, MOUZA DAKHINPAT, DISTRICT KAMRUP (METRO), ASSAM VS THE STATE OF ASSAM AND 6 ORS",
  office: "Directorate of Secondary Education, Kahilipara, Guwahati-19",
  caseNo: "WP(C)/12345/2025",
  designation: "Joint Secretary to the Govt. of Assam, E",
  count: 123456,
  sentence:
    "Please prepare the parawise comments on the writ petition and place the file with the department's counsel before the next date of hearing.",
} as const;

const PLAIN = {
  party: "RAM KUMAR DAS VS STATE OF ASSAM",
  office: "Education",
  caseNo: "WA/55/2026",
  designation: "Section Officer",
  count: 12,
  sentence: "Seen; put up with the counsel's opinion.",
};

/** The ids, codes and dates the dynamic routes and the stress rows share. */
export const SAMPLE = {
  caseRef: "ASLMS/GHC/CASE/2026/000001",
  caseRefPath: "ASLMS-GHC-CASE-2026-000001",
  userId: "0192a3b4-0000-7000-8000-000000000009",
  officeCode: "EDU",
  ticketRef: "TKT/EDU/2026/0001",
  ticketRefPath: "TKT-EDU-2026-0001",
  auditId: "0192a3b4-0000-7000-8000-0000000000a1",
  // the Case Assistant (design assistant): a cited court order and the answer citing it
  orderId: "0192a3b4-0000-7000-8000-0000000000o1",
  messageId: "0192a3b4-0000-7000-8000-0000000000m9",
  // the user-type page (design case-workspace-admin, decision 25)
  userType: "dept_officer",
  // the View Cause List modal (design portal-ui-polish-2, decision 25): a cause-list date, a bench and its daily list
  causelistDate: "2026-10-23",
  benchId: "1854",
  causelistId: "0192a3b4-0000-7000-8000-0000000000c1",
};

const CODES = ["EDU", "HEALTH", "FIN", "PWD", "HOME"];

function uuid(seed: string, idx: number): string {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const tail = (h.toString(16) + idx.toString(16).padStart(4, "0")).padStart(12, "0").slice(-12);
  return `0192a3b4-0000-7000-8000-${tail}`;
}

function day(idx: number): string {
  const d = new Date(Date.UTC(2026, 9, 23 + idx));
  return d.toISOString().slice(0, 10);
}

function instant(idx: number): string {
  const d = new Date(Date.UTC(2026, 9, 21, 5, 30 - idx * 7));
  return d.toISOString().replace(".000Z", "Z");
}

function resolve(schema: Schema): { schema: Schema; ref: string | null } {
  if (schema.$ref) {
    const name = schema.$ref.split("/").pop()!;
    return { schema: DOC.components.schemas[name]!, ref: name };
  }
  return { schema, ref: null };
}

/** The non-null variant of a nullable `anyOf`, and whether null was allowed. */
function nonNull(schema: Schema): { schema: Schema; nullable: boolean } {
  const variants = schema.anyOf ?? schema.oneOf;
  if (variants) {
    const real = variants.filter((v) => v.type !== "null");
    return { schema: real[0] ?? {}, nullable: real.length < variants.length };
  }
  return { schema, nullable: false };
}

function stringFor(key: string, parent: string, format: string | undefined, idx: number, stress: boolean): string {
  const k = key.toLowerCase();
  const p = parent.toLowerCase();
  const v = stress ? STRESS : PLAIN;
  if (format === "date") return day(idx);
  if (format === "date-time") return instant(idx);
  if (format === "uuid" || k === "id" || k.endsWith("_id")) return uuid(`${parent}.${key}`, idx);
  if (/petitioner|respondent|parties|party_line|party_name|^party$/.test(k)) return v.party;
  if (k === "case_no_text" || k === "case_no" || k === "label" && p.includes("case")) return idx === 0 ? STRESS.caseNo : `${PLAIN.caseNo.slice(0, 3)}${55 + idx}/2026`;
  if (k === "ref_no") return idx === 0 ? SAMPLE.caseRef : `ASLMS/GHC/CASE/2026/00000${2 + idx}`;
  if (k === "cnr") return `ASHC01${String(12345 + idx).padStart(6, "0")}2025`;
  if (k.includes("designation")) return v.designation;
  if ((k === "name" || k === "office_name" || k === "department_name") && /office|department|holder|unit|court|directorate/.test(p + k))
    return idx === 0 ? STRESS.office : `${PLAIN.office} ${idx}`;
  if (k === "office_name" || k === "department_name") return idx === 0 ? STRESS.office : `${PLAIN.office} ${idx}`;
  if (k.endsWith("code") || k === "code") return CODES[idx % CODES.length]!;
  if (k === "email") return `officer${idx}@assam.gov.in`;
  if (k === "mobile") return "9864012345";
  if (k === "mime") return "application/pdf";
  if (k.includes("url") || k === "href") return "/";
  if (k === "full_name" || k === "user_name" || k === "actor_name" || k === "name" || k.endsWith("_by")) return idx === 0 ? "Anita Sharma Baruah" : `Rina Das ${idx}`;
  if (/remark|note|reason|description|phrase|message|detail|summary|text|body|title|purpose|business|order|error/.test(k)) return idx === 0 ? v.sentence : PLAIN.sentence;
  if (k === "month") return `2026-${String(10 - idx).padStart(2, "0")}`;
  if (k === "key" || k === "kind" || k === "status" || k === "role" || k === "source" || k === "kind_label") return `${k}_${idx}`;
  return idx === 0 ? "Sample value with a fair length" : `Sample ${idx}`;
}

const SMALL_INT = /year|sr_no|_no$|^no$|seq|version|attempt|priority|days|hours|minutes|seconds|pct|percent|page|limit|offset|bytes|_ms$|month|hour|minute|bench_id|level|order$|position|rank|week/;

function intFor(key: string, idx: number, stress: boolean): number {
  const k = key.toLowerCase();
  if (k.includes("year")) return 2025 - idx;
  if (SMALL_INT.test(k)) return 2 + idx;
  return stress ? STRESS.count + idx : PLAIN.count + idx;
}

function numberFor(key: string, idx: number): number {
  const k = key.toLowerCase();
  if (k.includes("score") || k.includes("weight") || k.includes("confidence")) return idx === 0 ? 0.912 : 0.64;
  if (k.includes("pct") || k.includes("percent") || k.includes("rate")) return 87.5;
  return 1.5 + idx;
}

const FALSE_FLAG = /archived|revoked|provisional|merged|deleted|disabled|truncated|stale|^must_|failed|error|is_reportable|has_legal_heir|overdue|napix_enabled|paused|current$/;

/** Nullable fields left null: an ordinary record is not merged, superseded, withdrawn, revoked or archived. */
const NULL_KEY = /merged_into|superseded_by|supersedes|withdrawn|revoked|archived|deleted|closed_at|disposal|decided_|reason_for_rej|end_reason|valid_to|error$|last_error/;

export interface SynthOptions {
  /** Items per list (the first is the stress row). */
  listSize?: number;
}

export function synth(schema: Schema, key = "", parent = "", idx = 0, stack: string[] = [], opts: SynthOptions = {}): unknown {
  const { schema: inner, nullable } = nonNull(schema);
  const { schema: s, ref } = resolve(inner);
  if (ref && stack.includes(ref)) return nullable ? null : Array.isArray(s.type) || s.type === "array" ? [] : {};
  const nextStack = ref ? [...stack, ref] : stack;
  if (nullable && (stack.length > 5 || NULL_KEY.test(key.toLowerCase()))) return null;
  if (s.allOf && s.allOf.length > 0) return synth(s.allOf[0]!, key, parent, idx, nextStack, opts);
  if (s.const !== undefined) return s.const;
  if (s.enum && s.enum.length > 0) return s.enum[idx % s.enum.length];
  const type = Array.isArray(s.type) ? s.type.find((t) => t !== "null") : s.type;
  const stress = idx === 0;
  switch (type) {
    case "string":
      return stringFor(key, parent, s.format, idx, stress);
    case "integer":
      return intFor(key, idx, stress);
    case "number":
      return numberFor(key, idx);
    case "boolean":
      return !FALSE_FLAG.test(key.toLowerCase());
    case "array": {
      const n = stack.length > 3 ? 1 : (opts.listSize ?? 2);
      return Array.from({ length: n }, (_, i) => synth(s.items ?? {}, key, parent, i, nextStack, opts));
    }
    default: {
      if (s.properties) {
        const out: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(s.properties)) out[k] = synth(v, k, ref ?? key, idx, nextStack, opts);
        return out;
      }
      if (s.additionalProperties && typeof s.additionalProperties === "object") {
        return { [CODES[idx % CODES.length]!]: synth(s.additionalProperties, key, parent, idx, nextStack, opts) };
      }
      return {};
    }
  }
}

interface Route {
  template: string;
  pattern: RegExp;
  literals: number;
  schema: Schema;
}

const ROUTES: Route[] = Object.entries(DOC.paths)
  .flatMap(([template, ops]) => {
    const get = ops.get;
    const schema = get?.responses?.["200"]?.content?.["application/json"]?.schema;
    if (!schema) return [];
    const segments = template.split("/").filter(Boolean);
    const pattern = new RegExp(
      "^/" + segments.map((seg) => (seg.startsWith("{") ? (seg.includes(":path") ? ".+" : "[^/]+") : seg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))).join("/") + "$",
    );
    return [{ template, pattern, literals: segments.filter((x) => !x.startsWith("{")).length, schema }];
  })
  .sort((a, b) => b.literals - a.literals || b.template.length - a.template.length);

/** The OpenAPI template and synthetic body of a `GET` path of the API, or null when the API has no such `GET`. */
export function synthFor(path: string): { template: string; body: unknown } | null {
  const route = ROUTES.find((r) => r.pattern.test(path));
  if (!route) return null;
  return { template: route.template, body: synth(route.schema) };
}

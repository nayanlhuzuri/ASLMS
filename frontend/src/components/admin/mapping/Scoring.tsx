"use client";

/**
 * The scoring settings (design portal-mapping, decision 8; redrawn by portal-ui-polish-2, decisions 40 and 43; plan
 * §4.2, Table 6; CLAUDE.md: "the super admin can change the weights and bands from the application"). Read with
 * `admin.scoring`, `admin.counsel_codes` or `admin.keywords`; changed, and its history and the rules with their own
 * weight read, only with `admin.scoring`.
 *
 * - **Each weight** has its name, a one-line explanation, a slider (0.05 to 1, step 0.05) and a number field (0.01 to
 *   1, step 0.01), kept in sync. The API refuses 0.
 * - **The bands**: Strong Recommendation From and Possible Match From, with the band bar; Possible stays below Strong.
 *   "Nothing is ever assigned automatically; a department always claims." stays under them.
 * - **The save bar** counts unsaved changes, with Discard and Save Changes. Saving asks for the reason in a confirm
 *   dialog and sends the loaded version; a stale version (409) reloads the settings and keeps the reason.
 * - **Rules With Their Own Weight** (decision 40): the active rules carrying a weight override, read from the list
 *   endpoints the caller may read, each with "Use the Standard Weight" (`PATCH {weight: null}`). No new override is
 *   set from the portal: the Scoring tab is the only place for weights.
 * Without `admin.scoring` the values are read only, with no save bar and no history. The portal never computes a band.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties } from "react";

import {
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  DefinitionList,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  Pagination,
  TextArea,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, MAPPING_KEY, SCORING_KEY, useMe, useScoringSettings } from "@/lib/api/hooks";
import type { CounselCodeList, KeywordList, NamePatternList, ScoringSettings, ScoringSettingsHistory, ScoringSettingsSaved, WatchList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDateTime } from "@/lib/format";
import {
  changedFields,
  given,
  SCORING_FIELDS,
  scoringErrors,
  scoringValue,
  THRESHOLDS,
  WEIGHT_KINDS,
  weightText,
  type ScoringField,
  type WeightKind,
} from "@/lib/mapping";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import { SaveBar } from "../UserTypes";
import { conflictAware, isConflict, OfficeCell } from "./common";
import s from "./mapping.module.css";

const HISTORY_PAGE = 50;
export const SLIDER = { min: 0.05, max: 1, step: 0.05 } as const;
export const NUMBER = { min: 0.01, max: 1, step: 0.01 } as const;

type Values = Record<ScoringField, string>;

function valuesOf(settings: ScoringSettings): Values {
  const out = {} as Values;
  for (const f of SCORING_FIELDS) {
    const v = scoringValue(settings, f);
    out[f] = v === undefined ? "" : String(v);
  }
  return out;
}

/** The fields whose typed value differs from the loaded version. */
export function unsavedFields(values: Values, settings: ScoringSettings): ScoringField[] {
  return SCORING_FIELDS.filter((f) => Number(values[f]) !== scoringValue(settings, f) || values[f].trim() === "");
}

/** The slider's value for a typed number: within the slider's range, on its step. */
export function sliderValue(value: string): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return SLIDER.min;
  const stepped = Number((Math.round(n / SLIDER.step) * SLIDER.step).toFixed(2));
  return Math.min(SLIDER.max, Math.max(SLIDER.min, stepped));
}

function SettingsFacts({ settings }: { settings: ScoringSettings }) {
  return (
    <DefinitionList
      items={[
        [T.mapping.version, settings.version === 0 ? T.mapping.defaults : String(settings.version)],
        [T.mapping.validFrom, settings.valid_from ? formatDateTime(settings.valid_from) : null],
        [T.mapping.by, settings.updated_by?.full_name ?? null],
        [T.mapping.why, settings.reason],
        [T.mapping.engine, <span key="e" className="mono">{settings.engine_version}</span>],
      ]}
    />
  );
}

export function Scoring() {
  const me = useMe();
  const canScore = can(me.data, "admin.scoring");
  const settings = useScoringSettings();
  // kept here so that a reloaded version (after a save or a 409) keeps the typed reason and the after-save line
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <section className="stack" aria-label={T.mapping.scoring}>
      <h3>{T.mapping.scoring}</h3>
      <p>{T.mapping.explain}</p>
      {settings.isPending ? <Loading /> : null}
      <ErrorBanner error={given(settings.error)} onRetry={() => settings.refetch()} />
      {settings.data ? (
        <>
          <SettingsFacts settings={settings.data} />
          {notice ? <Notice>{notice}</Notice> : null}
          <ScoringForm
            key={settings.data.version}
            settings={settings.data}
            editable={canScore}
            reason={reason}
            setReason={setReason}
            setNotice={setNotice}
            reload={async () => {
              await settings.refetch();
            }}
          />
          {!canScore ? <p className="muted">{T.mapping.readOnly}</p> : null}
        </>
      ) : null}
      {canScore && settings.data ? <OwnWeights settings={settings.data} /> : null}
      {canScore ? <ScoringHistory /> : null}
    </section>
  );
}

function WeightRow({
  kind,
  value,
  error,
  changed,
  editable,
  onChange,
}: {
  kind: WeightKind;
  value: string;
  error?: string;
  changed: boolean;
  editable: boolean;
  onChange: (v: string) => void;
}) {
  const name = T.mapping.fields[kind]!;
  return (
    <div className={s.weightRow} data-kind={kind}>
      <div>
        <span className={changed ? `${s.weightName} ${s.unsavedDot}` : s.weightName}>{name}</span>
        <span className={s.weightExplain}>{T.mapping.weightExplain[kind]}</span>
      </div>
      <input
        type="range"
        className={s.slider}
        aria-label={T.mapping.sliderAria(name)}
        min={SLIDER.min}
        max={SLIDER.max}
        step={SLIDER.step}
        value={sliderValue(value)}
        disabled={!editable}
        onChange={(e) => onChange(String(Number(e.target.value).toFixed(2).replace(/0+$/, "").replace(/\.$/, "")))}
      />
      <TextField
        label={name}
        hideLabel
        type="number"
        min={NUMBER.min}
        max={NUMBER.max}
        step={NUMBER.step}
        inputMode="decimal"
        required
        readOnly={!editable}
        error={error}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

/** The band bar (decision 43): No Recommendation below Possible, Possible Match up to Strong, Strong above. */
function BandBar({ possible, strong }: { possible: number; strong: number }) {
  const p = Number.isFinite(possible) ? Math.min(1, Math.max(0, possible)) : 0;
  const st = Number.isFinite(strong) ? Math.min(1, Math.max(p, strong)) : 1;
  const parts: [string, number, string][] = [
    [T.mapping.bandNames.none!, p, s.band0!],
    [T.mapping.bandNames.possible!, st - p, s.band1!],
    [T.mapping.bandNames.strong!, 1 - st, s.band2!],
  ];
  return (
    <div className={s.bandBar} role="img" aria-label={`${T.mapping.bandBarAria}: ${parts.map(([l, w]) => `${l} ${Math.round(w * 100)}%`).join(", ")}`}>
      {parts.map(([label, width, cls]) => (
        <div key={label} className={cls} style={{ flexBasis: `${width * 100}%` } as CSSProperties}>
          {width >= 0.12 ? label : null}
        </div>
      ))}
    </div>
  );
}

/** The form for one loaded version (keyed by it): a newer version read from the server replaces the values. */
function ScoringForm({
  settings,
  editable,
  reason,
  setReason,
  setNotice,
  reload,
}: {
  settings: ScoringSettings;
  editable: boolean;
  reason: string;
  setReason: (reason: string) => void;
  setNotice: (notice: string | null) => void;
  reload: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Values>(() => valuesOf(settings));
  const [errors, setErrors] = useState<Partial<Record<ScoringField, string>>>({});
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const action = useAction();
  const unsaved = unsavedFields(values, settings);

  function set(field: ScoringField, value: string) {
    setValues({ ...values, [field]: value });
    setErrors({ ...errors, [field]: undefined });
  }

  function check() {
    setNotice(null);
    const errs = scoringErrors(values);
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;
    action.reset();
    setReasonError(null);
    setConfirming(true);
  }

  async function save() {
    if (reason.trim() === "") {
      setReasonError(T.mapping.reasonMissing);
      return;
    }
    const num = (f: ScoringField) => Number(values[f]);
    let conflict = false;
    const out = await action.run(() =>
      conflictAware(
        () =>
          api<ScoringSettingsSaved>("/admin/scoring-settings", {
            method: "PUT",
            body: {
              weights: Object.fromEntries(WEIGHT_KINDS.map((k) => [k, num(k)])),
              thresholds: { strong: num("strong"), possible: num("possible") },
              reason: reason.trim(),
              expected_version: settings.version,
            },
          }),
        () => {
          conflict = true;
        },
      ),
    );
    if (!out.ok) {
      if (conflict) {
        // re-read the settings and the history; the form takes the new version's values, the reason is kept
        setConfirming(false);
        setNotice(T.mapping.stale);
        await Promise.all([reload(), queryClient.invalidateQueries({ queryKey: [...SCORING_KEY, "history"] })]);
      }
      return;
    }
    setConfirming(false);
    const saved = out.value;
    if (!saved.changed) {
      setNotice(T.mapping.nothingChanged);
      return;
    }
    setNotice(T.mapping.savedAs(saved.version, saved.rescore_dispatched, saved.applies_within_minutes ?? 15));
    setReason("");
    // effective weights of every rule follow the settings; the inbox's bands too
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: MAPPING_KEY }),
      queryClient.invalidateQueries({ queryKey: INBOX_KEY }),
    ]);
  }

  const stale = isConflict(action.error);

  return (
    <div className="stack">
      <Card title={T.mapping.weights}>
        <div>
          {WEIGHT_KINDS.map((k) => (
            <WeightRow
              key={k}
              kind={k}
              value={values[k]}
              error={errors[k]}
              changed={editable && unsaved.includes(k)}
              editable={editable}
              onChange={(v) => set(k, v)}
            />
          ))}
        </div>
      </Card>
      <Card title={T.mapping.bandsTitle}>
        <div className="stack">
          <div className={s.bands}>
            {THRESHOLDS.map((k) => (
              <TextField
                key={k}
                label={k === "strong" ? T.mapping.strongFrom : T.mapping.possibleFrom}
                type="number"
                min={NUMBER.min}
                max={NUMBER.max}
                step={NUMBER.step}
                inputMode="decimal"
                required
                readOnly={!editable}
                error={errors[k]}
                value={values[k]}
                onChange={(e) => set(k, e.target.value)}
              />
            ))}
          </div>
          <BandBar possible={Number(values.possible)} strong={Number(values.strong)} />
          <p className="muted">{T.mapping.neverAssignedNote}</p>
        </div>
      </Card>
      {editable ? (
        <SaveBar count={unsaved.length} busy={action.busy} onSave={check} onDiscard={() => setValues(valuesOf(settings))} />
      ) : null}
      {editable && !confirming && !stale ? <ErrorBanner error={given(action.error)} /> : null}
      <ConfirmDialog
        open={confirming}
        title={T.mapping.confirmTitle}
        onClose={() => setConfirming(false)}
        onConfirm={() => void save()}
        busy={action.busy}
        error={stale ? null : given(action.error)}
        confirmLabel={T.mapping.saveSettings}
      >
        <p>{T.mapping.confirmText}</p>
        <DataTable
          caption={T.mapping.confirmTitle}
          rows={[...SCORING_FIELDS]}
          rowKey={(f) => f}
          columns={[
            { key: "kind", header: T.mapping.kind, primary: true, rowHeader: true, cell: (f) => T.mapping.fields[f] },
            {
              key: "current",
              header: T.mapping.current,
              align: "right",
              cell: (f) => <span className="mono">{weightText(scoringValue(settings, f))}</span>,
            },
            {
              key: "new",
              header: T.mapping.new,
              align: "right",
              cell: (f) => {
                const before = scoringValue(settings, f);
                const after = Number(values[f]);
                return <span className="mono">{before !== after ? <span className={s.changed}>{weightText(after)}</span> : weightText(after)}</span>;
              },
            },
          ]}
        />
        <TextArea
          label={T.mapping.saveReason}
          aria-required
          maxLength={2000}
          rows={2}
          error={reasonError}
          value={reason}
          onChange={(e) => {
            setReasonError(null);
            setReason(e.target.value);
          }}
        />
      </ConfirmDialog>
    </div>
  );
}

interface OwnWeightRow {
  key: string;
  path: string;
  kind: WeightKind;
  text: string;
  office: { code: string; name: string };
  own: number;
}

/**
 * "Rules With Their Own Weight" (decision 40): the active rules with a weight override, from the list endpoints the
 * caller may read (each needs its own function), and "Use the Standard Weight" to clear one.
 */
function OwnWeights({ settings }: { settings: ScoringSettings }) {
  const me = useMe();
  const queryClient = useQueryClient();
  const codesOk = can(me.data, "admin.counsel_codes");
  const wordsOk = can(me.data, "admin.keywords");
  const watchOk = can(me.data, "admin.watchlist");
  const codes = useQuery({
    queryKey: [...MAPPING_KEY, "codes", { q: "", inactive: false }],
    queryFn: () => api<CounselCodeList>("/admin/counsel-codes"),
    enabled: codesOk,
  });
  const keywords = useQuery({
    queryKey: [...MAPPING_KEY, "keywords", { inactive: false }],
    queryFn: () => api<KeywordList>("/admin/keywords"),
    enabled: wordsOk,
  });
  const patterns = useQuery({
    queryKey: [...MAPPING_KEY, "name-patterns", { inactive: false }],
    queryFn: () => api<NamePatternList>("/admin/name-patterns"),
    enabled: wordsOk,
  });
  const watch = useQuery({
    queryKey: [...MAPPING_KEY, "watchlist", { inactive: false }],
    queryFn: () => api<WatchList>("/admin/watchlist"),
    enabled: watchOk,
  });
  const [notice, setNotice] = useState<string | null>(null);
  const action = useAction();
  const own = (w: number | null | undefined): w is number => w !== null && w !== undefined;
  const rows: OwnWeightRow[] = [
    ...(codes.data?.items ?? [])
      .filter((r) => r.is_active && own(r.weight_override))
      .map((r) => ({ key: `cc-${r.id}`, path: `/admin/counsel-codes/${r.id}`, kind: "counsel_code" as const, text: r.code, office: r.office, own: r.weight_override! })),
    ...(keywords.data?.items ?? [])
      .filter((r) => r.is_active && own(r.weight_override))
      .map((r) => ({ key: `kw-${r.id}`, path: `/admin/keywords/${r.id}`, kind: "keyword" as const, text: r.keyword, office: r.office, own: r.weight_override! })),
    ...(patterns.data?.items ?? [])
      .filter((r) => r.is_active && own(r.weight_override))
      .map((r) => ({ key: `np-${r.id}`, path: `/admin/name-patterns/${r.id}`, kind: "name_pattern" as const, text: r.pattern, office: r.office, own: r.weight_override! })),
    ...(watch.data?.items ?? [])
      .filter((r) => r.is_active && own(r.weight_override))
      .map((r) => ({ key: `w-${r.id}`, path: `/admin/watchlist/${r.id}`, kind: "watchlist" as const, text: r.cnr, office: r.office, own: r.weight_override! })),
  ];
  const pending = (codesOk && codes.isPending) || (wordsOk && (keywords.isPending || patterns.isPending)) || (watchOk && watch.isPending);
  const error = codes.error ?? keywords.error ?? patterns.error ?? watch.error;

  async function clearOwn(row: OwnWeightRow) {
    setNotice(null);
    const out = await action.run(() => api(row.path, { method: "PATCH", body: { weight: null } }));
    if (out.ok) {
      setNotice(T.mapping.ownWeightCleared);
      await queryClient.invalidateQueries({ queryKey: MAPPING_KEY, refetchType: "all" });
    }
  }

  return (
    <Card title={T.mapping.ownWeightTitle}>
      <div className="stack">
        <p className="muted">{T.mapping.ownWeightIntro}</p>
        {pending ? <Loading /> : null}
        <ErrorBanner error={given(error ?? action.error)} />
        {notice ? <Notice>{notice}</Notice> : null}
        {!pending && !error ? (
          rows.length === 0 ? (
            <EmptyState>{T.mapping.noOwnWeight}</EmptyState>
          ) : (
            <DataTable
              caption={T.mapping.ownWeightTitle}
              rows={rows}
              rowKey={(r) => r.key}
              columns={[
                { key: "rule", header: T.mapping.ruleCol, primary: true, cell: (r) => <span className="mono">{r.text}</span> },
                { key: "kind", header: T.mapping.kind, cell: (r) => T.mapping.fields[r.kind] },
                { key: "office", header: T.mapping.office, cell: (r) => <OfficeCell office={r.office} /> },
                { key: "own", header: T.mapping.ownWeightCol, align: "right", cell: (r) => <span className="mono">{weightText(r.own)}</span> },
                {
                  key: "standard",
                  header: T.mapping.standardWeightCol,
                  align: "right",
                  cell: (r) => <span className="mono">{weightText(settings.weights[r.kind])}</span>,
                },
                {
                  key: "use",
                  header: <span className="visually-hidden">{T.mapping.useStandard}</span>,
                  label: T.mapping.useStandard,
                  align: "right",
                  cell: (r) => (
                    <Button variant="secondary" size="sm" busy={action.busy} aria-label={T.mapping.useStandardFor(r.text)} onClick={() => void clearOwn(r)}>
                      {T.mapping.useStandard}
                    </Button>
                  ),
                },
              ]}
            />
          )
        ) : null}
      </div>
    </Card>
  );
}

/** The saved versions, newest first, 50 a page; each value that differs from the next older version is marked. */
export function ScoringHistory() {
  const [offset, setOffset] = useState(0);
  const history = useQuery({
    queryKey: [...SCORING_KEY, "history", offset],
    queryFn: () => api<ScoringSettingsHistory>("/admin/scoring-settings/history", { query: { limit: HISTORY_PAGE, offset } }),
  });
  return (
    <section className="stack" aria-label={T.mapping.history}>
      <h4>{T.mapping.history}</h4>
      {history.isPending ? <Loading /> : null}
      <ErrorBanner error={given(history.error)} onRetry={() => history.refetch()} />
      {history.data ? (
        history.data.items.length === 0 ? (
          <EmptyState>{T.mapping.noHistory}</EmptyState>
        ) : (
          <>
            <DataTable
              caption={`${T.mapping.history} (${history.data.total})`}
              rows={history.data.items.map((v, i, all) => ({ v, changed: changedFields(v, all[i + 1]) }))}
              rowKey={(r) => String(r.v.version)}
              columns={[
                { key: "version", header: T.mapping.version, primary: true, cell: (r) => <span className="mono">{r.v.version}</span> },
                { key: "from", header: T.mapping.validFrom, cell: (r) => formatDateTime(r.v.valid_from) },
                { key: "to", header: T.mapping.validTo, cell: (r) => formatDateTime(r.v.valid_to) },
                { key: "by", header: T.mapping.by, cell: (r) => r.v.updated_by?.full_name ?? "—" },
                { key: "why", header: T.mapping.why, cell: (r) => r.v.reason ?? "—" },
                ...SCORING_FIELDS.map((f) => ({
                  key: f,
                  header: T.mapping.fields[f],
                  align: "right" as const,
                  cell: (r: { v: (typeof history.data.items)[number]; changed: ScoringField[] }) => (
                    <span className="mono">
                      {r.changed.includes(f) ? (
                        <span className={s.changed} title={T.mapping.changedMark}>
                          {weightText(scoringValue(r.v, f))}
                          <span className="visually-hidden"> ({T.mapping.changedMark})</span>
                        </span>
                      ) : (
                        weightText(scoringValue(r.v, f))
                      )}
                    </span>
                  ),
                })),
              ]}
            />
            <Pagination offset={offset} limit={HISTORY_PAGE} total={history.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </section>
  );
}

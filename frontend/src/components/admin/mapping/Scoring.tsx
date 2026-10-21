"use client";

/**
 * The scoring settings (design portal-mapping, decision 8; plan §4.2, Table 6; CLAUDE.md: "the super admin can change
 * the weights and bands from the application"). Read with `admin.scoring`, `admin.counsel_codes` or `admin.keywords`;
 * changed and its history read only with `admin.scoring`. A save sends all seven values, a reason and the version the
 * form was loaded from; a stale version (409) reloads the settings and keeps the reason. The portal never computes a
 * band: this tab shows only the settings themselves.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  Button,
  ConfirmDialog,
  DefinitionList,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  Pagination,
  DataTable,
  TextArea,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { INBOX_KEY, MAPPING_KEY, SCORING_KEY, useMe, useScoringSettings } from "@/lib/api/hooks";
import type { ScoringSettings, ScoringSettingsHistory, ScoringSettingsSaved } from "@/lib/api/types";
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
} from "@/lib/mapping";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import { conflictAware, isConflict } from "./common";
import s from "./mapping.module.css";

const HISTORY_PAGE = 50;

type Values = Record<ScoringField, string>;

function valuesOf(settings: ScoringSettings): Values {
  const out = {} as Values;
  for (const f of SCORING_FIELDS) {
    const v = scoringValue(settings, f);
    out[f] = v === undefined ? "" : String(v);
  }
  return out;
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

function ValuesTable({ settings }: { settings: ScoringSettings }) {
  return (
    <DataTable
      caption={`${T.mapping.weights} and ${T.mapping.thresholds.toLowerCase()}`}
      rows={[...SCORING_FIELDS]}
      rowKey={(f) => f}
      columns={[
        {
          key: "kind",
          header: T.mapping.kind,
          primary: true,
          rowHeader: true,
          cell: (f) => (
            <>
              {T.mapping.fields[f]}
              {(THRESHOLDS as readonly string[]).includes(f) ? ` (${T.mapping.thresholds.toLowerCase()})` : ""}
            </>
          ),
        },
        {
          key: "value",
          header: `${T.mapping.version} ${settings.version}`,
          align: "right",
          cell: (f) => <span className="mono">{weightText(scoringValue(settings, f))}</span>,
        },
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
          {canScore ? (
            <ScoringForm
              key={settings.data.version}
              settings={settings.data}
              reason={reason}
              setReason={setReason}
              notice={notice}
              setNotice={setNotice}
              reload={async () => {
                await settings.refetch();
              }}
            />
          ) : (
            <>
              <ValuesTable settings={settings.data} />
              <p className="muted">{T.mapping.readOnly}</p>
            </>
          )}
        </>
      ) : null}
      {canScore ? <ScoringHistory /> : null}
    </section>
  );
}

/** The form for one loaded version (keyed by it): a newer version read from the server replaces the inputs. */
function ScoringForm({
  settings,
  reason,
  setReason,
  notice,
  setNotice,
  reload,
}: {
  settings: ScoringSettings;
  reason: string;
  setReason: (reason: string) => void;
  notice: string | null;
  setNotice: (notice: string | null) => void;
  reload: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Values>(() => valuesOf(settings));
  const [errors, setErrors] = useState<Partial<Record<ScoringField, string>>>({});
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const action = useAction();

  function check(e: FormEvent) {
    e.preventDefault();
    setNotice(null);
    const errs = scoringErrors(values);
    setErrors(errs);
    const noReason = reason.trim() === "";
    setReasonError(noReason ? T.mapping.reasonMissing : null);
    if (Object.keys(errs).length > 0 || noReason) return;
    action.reset();
    setConfirming(true);
  }

  async function save() {
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
      <h4>{T.mapping.edit}</h4>
      <form className="stack" onSubmit={check} noValidate aria-label={T.mapping.edit}>
        <fieldset className={s.values}>
          <legend>{T.mapping.weights}</legend>
          {WEIGHT_KINDS.map((k) => (
            <TextField
              key={k}
              label={T.mapping.fields[k]}
              type="number"
              step="0.001"
              min="0.001"
              max="1"
              inputMode="decimal"
              required
              error={errors[k]}
              value={values[k]}
              onChange={(e) => setValues({ ...values, [k]: e.target.value })}
            />
          ))}
        </fieldset>
        <fieldset className={s.values}>
          <legend>{T.mapping.thresholds}</legend>
          {THRESHOLDS.map((k) => (
            <TextField
              key={k}
              label={T.mapping.fields[k]}
              type="number"
              step="0.001"
              min="0.001"
              max="1"
              inputMode="decimal"
              required
              error={errors[k]}
              value={values[k]}
              onChange={(e) => setValues({ ...values, [k]: e.target.value })}
            />
          ))}
        </fieldset>
        <TextArea
          label={T.mapping.saveReason}
          required
          maxLength={2000}
          rows={2}
          error={reasonError}
          value={reason}
          onChange={(e) => {
            setReasonError(null);
            setReason(e.target.value);
          }}
        />
        <div>
          <Button type="submit">{T.mapping.saveSettings}</Button>
        </div>
      </form>
      {notice ? <Notice>{notice}</Notice> : null}
      {!confirming && !stale ? <ErrorBanner error={given(action.error)} /> : null}
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
                return (
                  <span className="mono">{before !== after ? <span className={s.changed}>{weightText(after)}</span> : weightText(after)}</span>
                );
              },
            },
          ]}
        />
        <p>
          {T.mapping.why}: {reason.trim()}
        </p>
      </ConfirmDialog>
    </div>
  );
}

/** The saved versions, newest first, 50 a page; each value that differs from the next older version is marked. */
export function ScoringHistory() {
  const [offset, setOffset] = useState(0);
  const history = useQuery({
    queryKey: [...SCORING_KEY, "history", offset],
    queryFn: () =>
      api<ScoringSettingsHistory>("/admin/scoring-settings/history", { query: { limit: HISTORY_PAGE, offset } }),
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

"use client";

/**
 * Send file and Recall (design portal-workflow, decisions 5-7; Annexure B's "Hand over", replaced by sending under the
 * owner's rules of 7 Oct 2026). The buttons show only when the custody card's `can_send` / `can_recall` are true; the
 * API decides every call. Sending never claims, allots or changes the owner. After a move the finalised drafts are
 * listed; when the answer's `card` is null the sender no longer sees the case and the portal goes to Files → Sent
 * with a notice (design portal-files-alerts, decision 14), marking the case's cached queries stale.
 */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import {
  Button,
  CharCounter,
  ConfirmDialog,
  cx,
  ErrorBanner,
  Loading,
  Notice,
  Pagination,
  SelectField,
  Stepper,
  TextArea,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useCaseTitle, useDepartments, useWorkflowCodes } from "@/lib/api/hooks";
import type { CaseDetail, CustodyCard, CustodyMove, Recipient, RecipientList } from "@/lib/api/types";
import { setFlash } from "@/lib/flash";
import { formatDate } from "@/lib/format";
import { CUSTODY_ERRORS, T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";
import { dueDateBounds } from "@/lib/workflow";

import { useWorkflowRefresh, within } from "./common";
import s from "./workflow.module.css";

const REMARK_MIN = 3;
const REMARK_MAX = 2000;
const PEOPLE_PAGE = 50;

function personLabel(p: Recipient): string {
  return [p.full_name, p.designation, `${p.office_code} — ${p.office_name}`, p.role_label].filter(Boolean).join(", ");
}

function personShort(p: Recipient): string {
  return [p.full_name, p.designation, p.office_code].filter(Boolean).join(", ");
}

function holderText(card: CustodyCard): string {
  const who = card.holder_user
    ? [card.holder_user.full_name, card.holder_user.designation].filter(Boolean).join(", ")
    : null;
  const office = card.holder_office ? `${card.holder_office.code} — ${card.holder_office.name}` : null;
  return [who, office].filter(Boolean).join(", ") || "—";
}

function movedNotice(result: CustodyMove, head: string): string {
  return result.finalised_notes.length > 0 ? `${head} ${T.wf.finalised(result.finalised_notes.join(", "))}` : head;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}

/** The people of the chosen department as selectable cards (avatar initials, name, designation, office). */
function PeopleCards({
  people,
  value,
  onChange,
  error,
}: {
  people: Recipient[];
  value: string;
  onChange: (p: Recipient) => void;
  error?: string;
}) {
  const name = useId();
  return (
    <fieldset className={s.people} aria-describedby={error ? `${name}-error` : undefined}>
      <legend>{T.wf.person}</legend>
      {people.map((p) => (
        <label key={p.membership_id} className={cx(s.person, value === p.membership_id && s.personOn)}>
          <input
            type="radio"
            name={name}
            value={p.membership_id}
            checked={value === p.membership_id}
            onChange={() => onChange(p)}
            aria-label={personLabel(p)}
          />
          <span className={s.avatar} aria-hidden="true">
            {initials(p.full_name)}
          </span>
          <span className={s.personText} aria-hidden="true">
            <strong>{p.full_name}</strong>
            <span className="muted">{[p.designation, `${p.office_code} — ${p.office_name}`].filter(Boolean).join(" · ")}</span>
          </span>
        </label>
      ))}
      {error ? (
        <p id={`${name}-error`} className={s.error} role="alert">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}

/**
 * Send file as a three-step dialog (design portal-ui-redesign, decision 25) with the stepper: 1 who receives it
 * (department, search, the people as cards, from `/custody/recipients`); 2 what they should do (pending action, due
 * date within the bounds, optional stage); 3 remark and confirm (remark with its counter, the drafts notice, the
 * summary line). Continue checks the step's required fields; Back keeps what was entered; the last step's primary is
 * "Send file". The request, the refusal texts, the send-away handling and the audit are unchanged.
 */
export function SendDialog({
  open,
  caseRef,
  detail,
  onClose,
  onDone,
}: {
  open: boolean;
  caseRef: string;
  detail: CaseDetail;
  onClose: () => void;
  onDone: (notice: string) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const refresh = useWorkflowRefresh(caseRef);
  const subtitle = useCaseTitle(caseRef);
  const action = useAction();
  const departments = useDepartments(open);
  const codes = useWorkflowCodes(open);
  const [step, setStep] = useState(1);
  const [department, setDepartment] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [person, setPerson] = useState<Recipient | null>(null);
  const [pending, setPending] = useState("");
  const [due, setDue] = useState("");
  const [remark, setRemark] = useState("");
  const [stage, setStage] = useState("");
  const [tried, setTried] = useState(false);
  const people = useQuery({
    queryKey: ["departments", department, "people", "send", q, offset],
    queryFn: () =>
      api<RecipientList>("/custody/recipients", {
        query: { department, q: q.trim() || undefined, limit: PEOPLE_PAGE, offset },
      }),
    enabled: open && !!department,
    placeholderData: keepPreviousData,
  });
  const bounds = dueDateBounds();
  const sendable = (codes.data?.pending_actions ?? []).filter((a) => a.sendable);
  const actionLabel = sendable.find((a) => a.code === pending)?.label ?? "";
  const drafts = detail.counts.my_drafts;
  const remarkOk = within(remark, REMARK_MIN, REMARK_MAX);

  function reset() {
    setStep(1);
    setDepartment("");
    setQ("");
    setOffset(0);
    setPerson(null);
    setPending("");
    setDue("");
    setRemark("");
    setStage("");
    setTried(false);
    action.reset();
  }

  function close() {
    reset();
    onClose();
  }

  /** Continue: the step's required fields first (step 1 a person, step 2 the pending action). */
  function next() {
    setTried(true);
    if (step === 1 && !person) return;
    if (step === 2 && !pending) return;
    setTried(false);
    setStep((n) => n + 1);
  }

  function back() {
    setTried(false);
    action.reset();
    setStep((n) => Math.max(1, n - 1));
  }

  async function submit() {
    setTried(true);
    if (!person || !pending || !remarkOk) return;
    const to = personShort(person);
    const out = await action.run(() =>
      api<CustodyMove>(apiCasePath(caseRef, "custody/send"), {
        method: "POST",
        body: {
          to_membership: person.membership_id,
          pending_action: pending,
          due_date: due || null,
          remark: remark.trim(),
          stage: stage || null,
        },
      }),
    );
    if (!out.ok) {
      await refresh();
      return;
    }
    if (out.value.card === null) {
      // the custody basis left with the file: never show a 404 for a case just sent
      setFlash(movedNotice(out.value, T.wf.sentAway(to)));
      reset();
      onClose();
      router.push("/files/sent");
      // Mark the case's data stale without refetching: removing it here, while the case page is still mounted,
      // made its observers fetch the case again and show the not-found message before the next page (review of
      // 13 Oct 2026). A later visit fetches afresh.
      void queryClient.cancelQueries({ queryKey: caseKey(caseRef) });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: caseKey(caseRef), refetchType: "none" }),
        queryClient.invalidateQueries({ queryKey: ["alerts"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["files"] }),
      ]);
      return;
    }
    reset();
    onClose();
    onDone(movedNotice(out.value, T.wf.sent(to)));
    await refresh();
  }

  const items = people.data?.items ?? [];
  const total = people.data?.total ?? 0;
  return (
    <ConfirmDialog
      open={open}
      title={T.wf.sendTitle}
      subtitle={subtitle}
      head={<Stepper step={step} steps={T.wf.sendSteps} />}
      onClose={close}
      onCancel={step > 1 ? back : close}
      cancelLabel={step > 1 ? T.back : T.cancel}
      onConfirm={step < 3 ? next : submit}
      busy={step === 3 && action.busy}
      error={step === 3 ? action.error : null}
      messages={CUSTODY_ERRORS}
      confirmLabel={step < 3 ? T.wf.continue : T.wf.send}
    >
      {step === 1 ? (
        <div className={cx("stack", s.pane)} key="who">
          <SelectField
            label={T.wf.department}
            options={(departments.data?.departments ?? []).map((d) => ({ value: d.code, label: `${d.code} — ${d.name}` }))}
            placeholder={T.wf.chooseDepartment}
            value={department}
            aria-required
            error={tried && !department ? T.wf.required : undefined}
            onChange={(e) => {
              setDepartment(e.target.value);
              setPerson(null);
              setOffset(0);
              setQ("");
            }}
          />
          {department ? (
            <>
              <TextField
                label={T.wf.searchPeople}
                type="search"
                value={q}
                maxLength={100}
                onChange={(e) => {
                  setQ(e.target.value);
                  setOffset(0);
                }}
              />
              {people.isPending ? <Loading /> : null}
              <ErrorBanner error={people.error} />
              {people.data && items.length === 0 ? <p className="muted">{T.wf.noPeople}</p> : null}
              {items.length > 0 ? (
                <PeopleCards
                  people={items}
                  value={person?.membership_id ?? ""}
                  onChange={setPerson}
                  error={tried && !person ? T.wf.choosePerson : undefined}
                />
              ) : null}
              {total > PEOPLE_PAGE ? (
                <>
                  <p className="muted">{T.wf.morePeople(items.length, total)}</p>
                  <Pagination offset={offset} limit={PEOPLE_PAGE} total={total} onChange={setOffset} />
                </>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
      {step === 2 ? (
        <div className={cx("stack", s.pane)} key="what">
          <SelectField
            label={T.wf.pendingAction}
            options={sendable.map((a) => ({ value: a.code, label: a.label }))}
            placeholder={T.wf.chooseAction}
            value={pending}
            aria-required
            error={tried && !pending ? T.wf.required : undefined}
            onChange={(e) => setPending(e.target.value)}
          />
          <TextField
            label={T.wf.dueDate}
            type="date"
            min={bounds.min}
            max={bounds.max}
            value={due}
            hint={T.wf.dueHint(formatDate(bounds.min), formatDate(bounds.max))}
            onChange={(e) => setDue(e.target.value)}
          />
          {detail.workflow.set_stage ? (
            <SelectField
              label={T.wf.stageOptional}
              options={(codes.data?.stages ?? []).map((st) => ({ value: st.code, label: st.label }))}
              placeholder={T.wf.keepStage}
              value={stage}
              onChange={(e) => setStage(e.target.value)}
            />
          ) : null}
        </div>
      ) : null}
      {step === 3 ? (
        <div className={cx("stack", s.pane)} key="confirm">
          <TextArea
            label={T.wf.remark}
            value={remark}
            rows={3}
            maxLength={REMARK_MAX}
            aria-required
            hint={T.wf.remarkHint}
            error={tried && !remarkOk ? T.wf.remarkRequired : undefined}
            onChange={(e) => setRemark(e.target.value)}
          />
          <CharCounter value={remark} max={REMARK_MAX} />
          {drafts > 0 ? <Notice>{T.wf.draftsWarning(drafts)}</Notice> : null}
          {person && pending ? (
            <p>
              <strong>{T.wf.summary(personShort(person), actionLabel, due ? formatDate(due) : null)}</strong>
            </p>
          ) : null}
        </div>
      ) : null}
    </ConfirmDialog>
  );
}

export function RecallDialog({
  open,
  caseRef,
  card,
  onClose,
  onDone,
}: {
  open: boolean;
  caseRef: string;
  card: CustodyCard;
  onClose: () => void;
  onDone: (notice: string) => void;
}) {
  const refresh = useWorkflowRefresh(caseRef);
  const subtitle = useCaseTitle(caseRef);
  const action = useAction();
  const [remark, setRemark] = useState("");
  const [tried, setTried] = useState(false);
  const remarkOk = within(remark, REMARK_MIN, REMARK_MAX);

  function close() {
    setRemark("");
    setTried(false);
    action.reset();
    onClose();
  }

  async function submit() {
    setTried(true);
    if (!remarkOk) return;
    const out = await action.run(() =>
      api<CustodyMove>(apiCasePath(caseRef, "custody/recall"), { method: "POST", body: { remark: remark.trim() } }),
    );
    if (out.ok) {
      close();
      onDone(movedNotice(out.value, T.wf.recalled));
    }
    await refresh();
  }

  return (
    <ConfirmDialog
      open={open}
      title={T.wf.recallTitle}
      subtitle={subtitle}
      onClose={close}
      onConfirm={submit}
      busy={action.busy}
      error={action.error}
      messages={CUSTODY_ERRORS}
      confirmLabel={T.wf.recall}
    >
      <p>{T.wf.recallText(holderText(card))}</p>
      <p className="muted">{T.wf.recallEffect}</p>
      <TextArea
        label={T.wf.remark}
        value={remark}
        rows={3}
        maxLength={REMARK_MAX}
        aria-required
        hint={T.wf.remarkHint}
        error={tried && !remarkOk ? T.wf.remarkRequired : undefined}
        onChange={(e) => setRemark(e.target.value)}
      />
      <CharCounter value={remark} max={REMARK_MAX} />
    </ConfirmDialog>
  );
}

/**
 * Send file and Recall on a custody card, by the card's flags, with the notice of the last move. Both are secondary:
 * the card sits on the Custody and stage tab under the case header, which holds the page's one primary (decision 16;
 * design portal-ui-polish, decision 11).
 */
export function CustodyActions({ caseRef, detail, card }: { caseRef: string; detail: CaseDetail; card: CustodyCard }) {
  const [open, setOpen] = useState<"send" | "recall" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  if (!card.can_send && !card.can_recall && !notice) return null;
  return (
    <div className="stack">
      {notice ? <Notice>{notice}</Notice> : null}
      <div className="row">
        {card.can_send ? (
          <Button variant="secondary" onClick={() => setOpen("send")}>
            {T.wf.send}
          </Button>
        ) : null}
        {card.can_recall ? (
          <Button variant="secondary" onClick={() => setOpen("recall")}>
            {T.wf.recall}
          </Button>
        ) : null}
      </div>
      <SendDialog open={open === "send"} caseRef={caseRef} detail={detail} onClose={() => setOpen(null)} onDone={setNotice} />
      {card.can_recall ? (
        <RecallDialog open={open === "recall"} caseRef={caseRef} card={card} onClose={() => setOpen(null)} onDone={setNotice} />
      ) : null}
    </div>
  );
}

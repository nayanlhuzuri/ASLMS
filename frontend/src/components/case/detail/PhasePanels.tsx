import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { Card, CardHead, Notice } from "../../ui/Layout";
import { Pill } from "../../ui/Pill";
import s from "./detail.module.css";

export function NotesPanel() {
  return (
    <Card>
      <CardHead title="Notes and custody" actions={<Pill tone="muted">Phase 2</Pill>} />
      <p className="muted" style={{ fontSize: 14, maxWidth: 640 }}>
        Arrives in Phase 2. The case will carry an eOffice-style custody trail (who holds the file, the pending action and its due date) and an
        append-only noting trail that follows the case across offices.
      </p>
    </Card>
  );
}

/** The Case Assistant layout from the UI board, shown disabled until SourceTrace arrives. */
export function AssistantPanel() {
  return (
    <div className={s.assistant}>
      <div className={s.chat}>
        <div className={s.chatBody}>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "center", maxWidth: 460 }}>
            <span style={{ color: "var(--accent)" }}>
              <Icon name="chat" size={28} />
            </span>
            <strong>Case Assistant is powered by SourceTrace and arrives in Phase 3</strong>
            <span className="muted" style={{ fontSize: 14 }}>
              It will answer questions about this case from its orders and court filings, related past cases, and the Acts, rules and policies, with a
              reference for every answer.
            </span>
          </div>
        </div>
        <div className={s.composer}>
          <label style={{ flexGrow: 1 }}>
            <span className="sr-only">Ask about this case</span>
            <textarea className="textarea" rows={2} disabled placeholder="Ask about this case, related past cases, or the Acts, rules and policies" />
          </label>
          <Button variant="primary" icon="send" disabled aria-label="Send question (not yet available)">
            Send
          </Button>
        </div>
      </div>
      <Card className={s.sources}>
        <CardHead title="Sources used" caption />
        <p className="muted" style={{ fontSize: 13 }}>
          Court orders and court filings of this case, and Acts, rules and policies uploaded to SourceTrace.
        </p>
        <Notice tone="warning">
          <Icon name="lock" size={16} />
          Internal documents and notes are never sent to SourceTrace.
        </Notice>
        <p className="muted" style={{ fontSize: 13 }}>
          Conversations will be visible only to you. Check each reference before relying on an answer.
        </p>
      </Card>
    </div>
  );
}

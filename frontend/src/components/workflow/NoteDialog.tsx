"use client";

/**
 * "Add note" from the case summary header (design portal-ui-redesign, decisions 24 and 25): the note composer on the
 * Action dialog template, 720 px wide. Its fields and rules are the composer's (portal-workflow, decisions 10-12): it
 * says before anything is written whether the note will be a draft or permanent, by the overview's
 * `workflow.note_mode`. Notes are never sent to SourceTrace. `initialBody` fills the text for the Case Assistant's
 * "Copy to note" (design assistant, decision 13): the person edits it and saves an ordinary note.
 */
import { Dialog, Notice } from "@/components/ui";
import { useCaseTitle } from "@/lib/api/hooks";
import { T } from "@/lib/messages";

import { NoteComposer, type NoteMode } from "./NoteComposer";

export function NoteDialog({
  open,
  caseRef,
  mode,
  onClose,
  onDone,
  initialBody,
  initialVisibility,
  warning,
}: {
  open: boolean;
  caseRef: string;
  mode: NoteMode;
  onClose: () => void;
  onDone: (notice: string) => void;
  initialBody?: string;
  /** Copy to note of an answer citing internal records: the narrowest setting of those records (design
   * assistant-ollama, decision 10); the person may still choose another. */
  initialVisibility?: string;
  /** A line above the composer (the internal-records warning of Copy to note). */
  warning?: string;
}) {
  const subtitle = useCaseTitle(caseRef);
  return (
    <Dialog open={open} title={T.case.noteTitle} subtitle={subtitle} onClose={onClose} wide>
      {open && warning ? <Notice tone="warning">{warning}</Notice> : null}
      {open ? (
        <NoteComposer
          caseRef={caseRef}
          mode={mode}
          initialBody={initialBody}
          initialVisibility={initialVisibility}
          onCancel={onClose}
          onDone={(text) => {
            onClose();
            onDone(text);
          }}
        />
      ) : null}
    </Dialog>
  );
}

"use client";

/**
 * "Add note" from the case summary header (design portal-ui-redesign, decisions 24 and 25): the note composer on the
 * Action dialog template, 720 px wide. Its fields and rules are the composer's (portal-workflow, decisions 10-12): it
 * says before anything is written whether the note will be a draft or permanent, by the overview's
 * `workflow.note_mode`. Notes are never sent to SourceTrace.
 */
import { Dialog } from "@/components/ui";
import { useCaseTitle } from "@/lib/api/hooks";
import { T } from "@/lib/messages";

import { NoteComposer, type NoteMode } from "./NoteComposer";

export function NoteDialog({
  open,
  caseRef,
  mode,
  onClose,
  onDone,
}: {
  open: boolean;
  caseRef: string;
  mode: NoteMode;
  onClose: () => void;
  onDone: (notice: string) => void;
}) {
  const subtitle = useCaseTitle(caseRef);
  return (
    <Dialog open={open} title={T.case.noteTitle} subtitle={subtitle} onClose={onClose} wide>
      {open ? (
        <NoteComposer
          caseRef={caseRef}
          mode={mode}
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

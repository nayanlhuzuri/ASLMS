"use client";

/**
 * The past-months collection's state, the same on the Overview status line and Load Control (design
 * data-collection-redesign-advisories, decision 4): the server's `collection` in the words of `T.dc.states`, Running
 * info with the pulse, Paused warning with the reason as a tooltip, Finished success, Not Started neutral.
 */
import { Badge } from "@/components/ui";
import type { DataLoad } from "@/lib/api/types";
import { labelFor } from "@/lib/displayLabels";
import { T } from "@/lib/messages";

import ds from "./data.module.css";

export type CollectionState = DataLoad["collection"];

const TONES: Record<CollectionState, "info" | "warning" | "success" | undefined> = {
  running: "info",
  paused: "warning",
  finished: "success",
  not_started: undefined,
};

export function CollectionStateBadge({ state, reason }: { state: CollectionState; reason?: string | null }) {
  return (
    <span className={state === "running" ? ds.pulse : undefined}>
      <Badge tone={TONES[state]} title={state === "paused" && reason ? reason : undefined}>
        {labelFor(T.dc.states, state)}
      </Badge>
    </span>
  );
}

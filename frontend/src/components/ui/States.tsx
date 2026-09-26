import type { ReactNode } from "react";
import s from "./ui.module.css";

export function Loading({ label = "Loading", center }: { label?: string; center?: boolean }) {
  return (
    <div className={`${s.state} ${center ? s.stateCenter : ""}`} role="status" aria-live="polite">
      <span className={s.spinner} aria-hidden="true" />
      <span>{label}…</span>
    </div>
  );
}

export function Empty({ title, children, center }: { title: string; children?: ReactNode; center?: boolean }) {
  return (
    <div className={`${s.state} ${center ? s.stateCenter : ""}`}>
      <div className={s.stateTitle}>{title}</div>
      {children ? <div>{children}</div> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className={s.error} role="alert">
      <span>{message}</span>
      {onRetry ? (
        <button type="button" className={`${s.btn} ${s.secondary} ${s.small}`} onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

/** Renders loading / error / content for a `useApi` result. */
export function Async<T>({
  state,
  children,
  loadingLabel,
}: {
  state: { data: T | undefined; error: string | null; loading: boolean; reload: () => void };
  children: (data: T) => ReactNode;
  loadingLabel?: string;
}) {
  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  if (state.data === undefined) return state.loading ? <Loading label={loadingLabel} /> : null;
  return <>{children(state.data)}</>;
}

/**
 * The navigation's icons (design portal-ui-redesign, decision 22): inline SVG components, stroke 2, 18 px, no icon
 * library. Each is decorative (`aria-hidden`); the entry's label names it.
 */
import type { ReactNode } from "react";

function Svg({ children, size = 18 }: { children: ReactNode; size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}

export function DashboardIcon() {
  return (
    <Svg>
      <rect x="2" y="2" width="6" height="6" rx="1" />
      <rect x="10" y="2" width="6" height="6" rx="1" />
      <rect x="2" y="10" width="6" height="6" rx="1" />
      <rect x="10" y="10" width="6" height="6" rx="1" />
    </Svg>
  );
}

export function InboxIcon() {
  return (
    <Svg>
      <path d="M2 10h4l1 2h4l1-2h4M2 10l2-6h10l2 6v5H2z" />
    </Svg>
  );
}

export function ClaimIcon() {
  return (
    <Svg>
      <path d="M9 2v14M2 9h14" />
    </Svg>
  );
}

export function CauseListIcon() {
  return (
    <Svg>
      <path d="M3 3h12v12H3zM6 7h6M6 10h6M6 13h3" />
    </Svg>
  );
}

export function FilesIcon() {
  return (
    <Svg>
      <path d="M4 2h7l3 3v11H4z" />
    </Svg>
  );
}

export function CalendarIcon() {
  return (
    <Svg>
      <rect x="2" y="3" width="14" height="13" rx="2" />
      <path d="M2 7h14M6 1v4M12 1v4" />
    </Svg>
  );
}

export function BellIcon({ size = 18 }: { size?: number }) {
  return (
    <Svg size={size}>
      <path d="M9 2.5a5 5 0 0 0-5 5v3L2.5 13.5h13L14 10.5v-3a5 5 0 0 0-5-5zM7.3 15.5a1.9 1.9 0 0 0 3.4 0" />
    </Svg>
  );
}

export function SearchIcon({ size = 18 }: { size?: number }) {
  return (
    <Svg size={size}>
      <circle cx="8" cy="8" r="5" />
      <path d="m12 12 4 4" />
    </Svg>
  );
}

export function ReportsIcon() {
  return (
    <Svg>
      <path d="M3 15V9M8 15V5M13 15V7" />
    </Svg>
  );
}

export function AuditIcon() {
  return (
    <Svg>
      <path d="M9 2 3 5v4c0 4 3 6 6 7 3-1 6-3 6-7V5z" />
    </Svg>
  );
}

export function DataIcon() {
  return (
    <Svg>
      <ellipse cx="9" cy="4" rx="6" ry="2" />
      <path d="M3 4v10c0 1.1 2.7 2 6 2s6-.9 6-2V4M3 9c0 1.1 2.7 2 6 2s6-.9 6-2" />
    </Svg>
  );
}

export function AdminIcon() {
  return (
    <Svg>
      <circle cx="9" cy="9" r="2.5" />
      <path d="M9 1v3M9 14v3M1 9h3M14 9h3M3.3 3.3l2.1 2.1M12.6 12.6l2.1 2.1M3.3 14.7l2.1-2.1M12.6 5.4l2.1-2.1" />
    </Svg>
  );
}

export function MenuIcon() {
  return (
    <Svg size={20}>
      <path d="M3 5h12M3 9h12M3 13h12" />
    </Svg>
  );
}

export function MoreIcon() {
  return (
    <Svg>
      <circle cx="4" cy="9" r="1" />
      <circle cx="9" cy="9" r="1" />
      <circle cx="14" cy="9" r="1" />
    </Svg>
  );
}

/** The icon of each navigation entry, by its key. */
export const NAV_ICONS: Record<string, () => ReactNode> = {
  dashboard: DashboardIcon,
  inbox: InboxIcon,
  claim: ClaimIcon,
  causelist: CauseListIcon,
  files: FilesIcon,
  calendar: CalendarIcon,
  alerts: () => <BellIcon />,
  search: () => <SearchIcon />,
  reports: ReportsIcon,
  audit: AuditIcon,
  data: DataIcon,
  admin: AdminIcon,
};

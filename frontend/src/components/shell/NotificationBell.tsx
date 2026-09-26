"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { Notification, Page } from "@/lib/types";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { useToast } from "../ui/Toast";
import ui from "../ui/ui.module.css";
import s from "./shell.module.css";

const POLL_MS = 60_000;

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const toast = useToast();
  const pathname = usePathname();

  const load = useCallback(async () => {
    try {
      const page = await api.get<Page<Notification>>("/notifications", { unread: true, size: 8 });
      setItems(page.items);
      setUnread(page.total);
      setLoaded(true);
    } catch {
      /* the bell stays quiet on failure */
    }
  }, []);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_MS);
    return () => window.clearInterval(t);
  }, [load]);

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const markRead = async (id: string) => {
    try {
      await api.post(`/notifications/${id}/read`);
      await load();
    } catch (e) {
      toast.error(e);
    }
  };

  const markAll = async () => {
    try {
      await api.post("/notifications/read-all");
      toast.success("All notifications marked as read.");
      await load();
    } catch (e) {
      toast.error(e);
    }
  };

  return (
    <div className={s.bellWrap} ref={wrap}>
      <button
        ref={button}
        type="button"
        className={`${ui.iconButton} ${s.bell}`}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        aria-controls="notification-panel"
        onClick={() => {
          setOpen((o) => !o);
          if (!open) void load();
        }}
      >
        <Icon name="bell" />
        {unread > 0 ? <span className={s.dot} aria-hidden="true" /> : null}
      </button>
      {open ? (
        <div id="notification-panel" className={s.dropdown} role="region" aria-label="Unread notifications">
          <div className={s.dropHead}>
            <span className={s.dropTitle}>Notifications</span>
            {unread > 0 ? (
              <Button variant="link" small onClick={markAll}>
                Mark all read
              </Button>
            ) : null}
          </div>
          {!loaded ? (
            <div style={{ padding: 16 }} className="muted">
              Loading…
            </div>
          ) : items.length === 0 ? (
            <div style={{ padding: 16 }} className="muted">
              No unread notifications.
            </div>
          ) : (
            <ul className={s.dropList}>
              {items.map((n) => (
                <li key={n.id} className={s.dropItem}>
                  <div className={s.dropText}>
                    <span style={{ fontWeight: 600 }}>{n.title}</span>
                    {n.body ? <span className="muted">{n.body}</span> : null}
                    <span className={s.dropMeta}>{fmtDateTime(n.created_at)}</span>
                  </div>
                  <Button variant="link" small onClick={() => markRead(n.id)} aria-label={`Mark "${n.title}" as read`}>
                    Mark read
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <div className={s.dropFoot}>
            <Link href="/notifications" style={{ fontSize: 14, fontWeight: 600 }}>
              View all notifications
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}

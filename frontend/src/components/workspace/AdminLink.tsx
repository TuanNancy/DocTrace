"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { adminRequest } from "@/lib/api";

export function AdminLink({ token, active, onNavigate }: { token: string; active: boolean; onNavigate: () => void }) {
  const [allowed, setAllowed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void adminRequest<{ admin: boolean }>(token, "/access", { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setAllowed(value.admin === true); })
      .catch(() => { if (!controller.signal.aborted) setAllowed(false); });
    return () => controller.abort();
  }, [token]);
  return allowed ? <Link href="/admin" onClick={onNavigate} aria-current={active ? "page" : undefined}
    className={`nav-item ${active ? "nav-item-active" : ""}`}><ShieldCheck size={18} aria-hidden="true" />Quản trị</Link> : null;
}

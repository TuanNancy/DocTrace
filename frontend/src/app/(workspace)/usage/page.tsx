"use client";

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { FileText, MessageSquare, RefreshCw, Wallet } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceProvider";
import { getUsage } from "@/lib/api";
import type { UsageMetric, UsageSummary } from "@/types";

function resetDate(value: string | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const day = String(date.getUTCDate()).padStart(2, "0");
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  return `${day}/${month}/${date.getUTCFullYear()}`;
}

function formatCost(micros: number): string {
  return `${(micros / 1_000_000).toLocaleString("en-US", {
    minimumFractionDigits: 2, maximumFractionDigits: 6,
  })} USD`;
}

function demoUsage(plan: "free" | "pro", workspaceId: string): UsageSummary {
  const now = new Date();
  const reset = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1));
  return {
    workspace_id: workspaceId,
    plan,
    period_start: new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString(),
    reset_at: reset.toISOString(),
    chat: { used: 0, limit: plan === "pro" ? 100 : 10, remaining: plan === "pro" ? 100 : 10, metric: "chat_questions_month" },
    documents: { used: 0, limit: plan === "pro" ? 50 : 5, remaining: plan === "pro" ? 50 : 5, metric: "documents" },
    by_user: [],
  };
}

function MetricCard({ label, metric, icon, hint }: {
  label: string; metric: UsageMetric; icon: ReactNode; hint: string;
}) {
  const percent = metric.limit > 0 ? Math.min(100, Math.round(metric.used * 100 / metric.limit)) : 100;
  return <section className="glass-panel p-5">
    <div className="flex items-start justify-between gap-3">
      <div><p className="text-[10px] font-semibold uppercase tracking-[0.17em] text-slate-400">{label}</p>
        <p className="mt-2 font-sans text-2xl font-semibold tracking-tight text-slate-800">
          {metric.used}<span className="ml-1 text-sm font-normal text-slate-400">/ {metric.limit}</span></p></div>
      <span className="rounded-xl bg-blue-50 p-2.5 text-blue-500">{icon}</span>
    </div>
    <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar"
      aria-label={label} aria-valuemin={0} aria-valuemax={metric.limit} aria-valuenow={metric.used}>
      <div className={`h-full rounded-full ${percent >= 100 ? "bg-amber-400" : "bg-blue-400"}`} style={{ width: `${percent}%` }} />
    </div>
    <p className="mt-2 text-[11px] text-slate-500">Còn lại {metric.remaining} · {hint}</p>
  </section>;
}

export default function UsagePage() {
  const workspace = useWorkspace();
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (workspace.mock) {
      setUsage(demoUsage(workspace.activeWorkspace?.plan ?? "free", workspace.workspaceId ?? "demo"));
      setError(null);
      return;
    }
    if (!workspace.accessToken || !workspace.workspaceId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getUsage(workspace.accessToken, workspace.workspaceId, signal);
      if (!signal?.aborted) setUsage(result);
    } catch (cause) {
      if (!signal?.aborted) setError(cause instanceof Error ? cause.message : "Không thể tải mức sử dụng.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [workspace.accessToken, workspace.activeWorkspace?.plan, workspace.mock, workspace.workspaceId]);

  useEffect(() => {
    if (!workspace.workspaceId) { setUsage(null); return; }
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, workspace.workspaceId]);

  const plan = usage?.plan ?? workspace.activeWorkspace?.plan ?? "free";
  const owner = workspace.activeWorkspace?.role === "owner";
  return <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto">
    <section className="glass-panel flex flex-wrap items-center justify-between gap-4 p-5">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-500">Mức sử dụng</p>
        <h2 className="mt-2 font-sans text-xl font-semibold tracking-tight">Gói {plan === "pro" ? "Pro" : "Free"}</h2>
        <p className="mt-1 text-xs text-slate-500">Hạn mức câu hỏi đặt lại vào {resetDate(usage?.reset_at)} (UTC).</p>
      </div>
      <button className="secondary-button text-xs" onClick={() => void load()} disabled={loading}>
        <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> {loading ? "Đang tải…" : "Làm mới"}
      </button>
    </section>

    {error && <div role="alert" className="rounded-xl border border-red-100 bg-red-50/90 px-4 py-3 text-xs text-red-700">{error}</div>}

    {!usage && !error ? <div role="status" className="glass-panel p-8 text-center text-xs text-slate-400">Đang tải mức sử dụng…</div> : usage && <>
      <div className="grid gap-4 sm:grid-cols-2">
        <MetricCard label="Câu hỏi trong tháng" metric={usage.chat}
          icon={<MessageSquare size={20} strokeWidth={1.6} />} hint="đặt lại hằng tháng" />
        <MetricCard label="Tài liệu trong workspace" metric={usage.documents}
          icon={<FileText size={20} strokeWidth={1.6} />} hint="không đặt lại hằng tháng" />
      </div>

      <section className="glass-panel overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-5 py-4">
          <div><h3 className="font-sans text-sm font-semibold">{owner ? "Theo thành viên" : "Của bạn"}</h3>
            <p className="mt-1 text-[11px] text-slate-500">{owner
              ? "Chủ workspace chỉ thấy số liệu tổng hợp, không thấy nội dung hội thoại của thành viên."
              : "Bạn chỉ thấy số liệu sử dụng của chính mình trong workspace này."}</p></div>
          <span className="flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-[10px] text-slate-500"><Wallet size={12} /> chi phí OpenRouter</span>
        </div>
        {usage.by_user.length === 0 ? <p className="px-5 py-8 text-center text-xs text-slate-400">Chưa có dữ liệu sử dụng trong tháng này.</p>
          : <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-slate-400"><tr>
              <th className="px-5 py-3 font-medium">Người dùng</th>
              <th className="px-5 py-3 font-medium">Câu hỏi</th>
              <th className="px-5 py-3 font-medium">Chi phí</th>
              <th className="px-5 py-3 font-medium">Chi phí chưa xác định</th>
            </tr></thead>
            <tbody className="divide-y divide-slate-100/80">{usage.by_user.map((row) => <tr key={row.user_id}>
              <td className="px-5 py-3 font-medium text-slate-700">{row.user_id === workspace.user?.id
                ? "Bạn" : <span title={row.user_id}>{row.user_id.slice(0, 8)}…</span>}</td>
              <td className="px-5 py-3 text-slate-600">{row.chat_questions}</td>
              <td className="px-5 py-3 text-slate-600">{formatCost(row.cost_micros)}</td>
              <td className="px-5 py-3">{row.cost_unknown_calls > 0
                ? <span className="status-badge status-queued">{row.cost_unknown_calls} lượt</span>
                : <span className="text-slate-400">0</span>}</td>
            </tr>)}</tbody>
          </table></div>}
      </section>

      <p className="px-1 text-[10px] leading-5 text-slate-400">Chi phí được ghi nhận tự động từ OpenRouter và hiển thị bằng micro-USD. Số liệu không bao gồm nội dung câu hỏi hay câu trả lời.</p>
    </>}
  </div>;
}

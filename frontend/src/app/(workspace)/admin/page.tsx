"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceProvider";
import { adminRequest, ApiError } from "@/lib/api";
import type { AdminAudit, AdminDocument, AdminFailure, AdminHealth, AdminOverview, AdminPage as Page,
  AdminPurge, AdminWorkspace, CostGroup } from "@/types/admin";

const AdminContext = createContext({ token: "", revision: 0, refresh: () => {}, denied: () => {} });
const money = (micros: number) => `${(micros / 1_000_000).toLocaleString("en-US", { maximumFractionDigits: 6 })} USD`;
const milliseconds = (value: number | null) => value === null ? "Chưa có dữ liệu" : `${Math.round(value).toLocaleString("vi-VN")} ms`;
const date = (value: string) => new Date(value).toLocaleString("vi-VN", { timeZone: "UTC" });
const forbidden = (error: unknown) => error instanceof ApiError && [401, 403].includes(error.status);

function Id({ value }: { value: string | null }) {
  return <code className="break-all text-[11px] text-slate-600">{value ?? "—"}</code>;
}
function Badge({ value }: { value: string }) {
  const color = ["error", "delete_error", "failed", "degraded"].includes(value) ? "bg-amber-50 text-amber-800"
    : ["ready", "active", "completed", "ok"].includes(value) ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-700";
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${color}`}>{value}</span>;
}
function ErrorMessage({ message }: { message: string }) {
  return <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{message}</p>;
}
function Table({ headers, children }: { headers: string[]; children: ReactNode }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[620px] text-left text-xs">
    <thead className="bg-slate-50 text-slate-600"><tr>{headers.map((label) => <th key={label} scope="col" className="px-4 py-3 font-semibold">{label}</th>)}</tr></thead>
    <tbody className="divide-y divide-slate-100 [&_td]:px-4 [&_td]:py-4 [&_td]:align-top">{children}</tbody>
  </table></div>;
}

function useAdminData<T>(path: string) {
  const { token, revision, denied } = useContext(AdminContext);
  const [state, setState] = useState<{ path: string; data?: T; error?: string }>({ path });
  useEffect(() => {
    const controller = new AbortController();
    setState({ path });
    void adminRequest<T>(token, path, { signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) setState({ path, data });
    }).catch((cause) => {
      if (controller.signal.aborted) return;
      if (forbidden(cause)) denied();
      else setState({ path, error: cause instanceof Error ? cause.message : "Không thể tải dữ liệu quản trị." });
    });
    return () => controller.abort();
  }, [token, path, revision, denied]);
  return state.path === path ? state : { path };
}

function useAdminAction() {
  const { token, refresh, denied } = useContext(AdminContext);
  const request = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  async function run(path: string, method: "POST" | "PATCH" = "POST", body?: unknown) {
    if (request.current) return false;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(null);
    try {
      await adminRequest(token, path, { method, body, signal: controller.signal });
      if (controller.signal.aborted) return false;
      refresh();
      return true;
    } catch (cause) {
      if (!controller.signal.aborted) {
        if (forbidden(cause)) denied();
        else setError(`${cause instanceof Error ? cause.message : "Thao tác chưa được xác nhận."} Làm mới để kiểm tra trạng thái trước khi thử lại.`);
      }
      return false;
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }
  return { run, busy, error };
}

function Resource<T>({ path, title, children }: { path: string; title: string; children: (items: T[]) => ReactNode }) {
  const [offsets, setOffsets] = useState([0]);
  const offset = offsets[offsets.length - 1];
  const { data, error } = useAdminData<Page<T>>(`${path}${path.includes("?") ? "&" : "?"}limit=20&offset=${offset}`);
  return <section className="glass-panel overflow-hidden" aria-label={title}>
    <h2 className="border-b border-slate-100 px-5 py-4 font-semibold">{title}</h2>
    {error ? <div className="p-4"><ErrorMessage message={error} /></div> : !data
      ? <p role="status" className="p-6 text-sm text-slate-600">Đang tải…</p>
      : data.items.length ? children(data.items) : <p className="p-6 text-sm text-slate-600">Không có kết quả trong trang này.</p>}
    <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-5 py-3">
      <button className="secondary-button text-xs" disabled={offsets.length === 1 || !data} onClick={() => setOffsets((values) => values.slice(0, -1))}>Trang trước</button>
      <span className="text-xs text-slate-600">Trang {offsets.length}</span>
      <button className="secondary-button text-xs" disabled={!data || data.next_offset === null}
        onClick={() => { if (data?.next_offset !== null && data?.next_offset !== undefined) setOffsets((values) => [...values, data.next_offset!]); }}>Trang sau</button>
    </div>
  </section>;
}

function Health() {
  const { data, error } = useAdminData<AdminHealth>("/health");
  return <section className="glass-panel p-5" aria-label="Tình trạng dịch vụ">
    <h2 className="font-semibold">Tình trạng dịch vụ</h2>
    {error ? <ErrorMessage message={error} /> : !data ? <p role="status" className="mt-3 text-sm">Đang kiểm tra…</p> : <>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Object.entries(data.checks).map(([name, check]) => <div key={name} className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between gap-2"><h3 className="font-medium">{name}</h3><Badge value={check.status} /></div>
        {check.latency_ms !== undefined && <p className="mt-2 text-xs text-slate-600">{check.latency_ms} ms</p>}
        {check.error_code && <p className="mt-2 text-xs text-amber-800">{check.error_code}</p>}
        {check.workers !== undefined && <p className="mt-2 text-xs leading-6 text-slate-600">{check.workers} worker · {check.queued} chờ · {check.started} đang chạy<br />{check.scheduled} hẹn retry · {check.failed} lỗi RQ<br />Chờ lâu nhất: {check.oldest_queued_seconds ?? "—"} giây</p>}
      </div>)}</div>
    </>}
  </section>;
}

function CostTable({ title, rows }: { title: string; rows: CostGroup[] }) {
  return <section className="glass-panel overflow-hidden"><h2 className="px-5 py-4 font-semibold">{title}</h2>
    {!rows.length ? <p className="p-5 text-sm text-slate-600">Chưa có lượt gọi.</p> : <Table headers={["Nhóm", "Lượt gọi", "Chi phí đã biết", "Chưa xác định"]}>
      {rows.map((row) => <tr key={row.key ?? "removed"}><td className="max-w-[240px] break-all">{row.key ?? "Workspace đã xóa"}</td><td>{row.calls}</td><td>{money(row.known_micros)}</td><td>{row.unknown_calls}</td></tr>)}
    </Table>}
  </section>;
}

function Overview() {
  const [days, setDays] = useState(30);
  const { data, error } = useAdminData<AdminOverview>(`/overview?days=${days}`);
  return <div className="space-y-5">
    <label className="flex items-center gap-3 text-sm">Khoảng thống kê
      <select className="rounded-lg border border-slate-300 bg-white px-3 py-2" value={days} onChange={(event) => setDays(Number(event.target.value))}>
        {[7, 30, 90].map((value) => <option key={value} value={value}>{value} ngày</option>)}
      </select>
    </label>
    {error && <ErrorMessage message={error} />}
    {data && <>
      <p className="text-xs text-slate-600">Từ {date(data.since)} UTC · Chi phí chưa xác định được tách riêng.</p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[
        ["Tài liệu", String(data.documents)], ["Câu hỏi", String(data.chat.requests)],
        ["Độ trễ p50 / p95", `${milliseconds(data.chat.latency_p50_ms)} / ${milliseconds(data.chat.latency_p95_ms)}`],
        ["Token đầu p50 / p95", `${milliseconds(data.chat.first_token_p50_ms)} / ${milliseconds(data.chat.first_token_p95_ms)}`],
      ].map(([label, value]) => <section key={label} className="glass-panel p-5"><h2 className="text-xs font-medium text-slate-600">{label}</h2><p className="mt-3 text-lg font-semibold tabular-nums">{value}</p></section>)}</div>
      <p className="text-sm text-slate-600">{data.chat.failed} chat lỗi · {data.chat.interrupted} bị gián đoạn · cache {data.chat.cache_hits}/{data.chat.requests} ({data.chat.requests ? Math.round(data.chat.cache_hits / data.chat.requests * 100) : 0}%) · {data.workspaces.map((row) => `${row.count} workspace ${row.status}`).join(" · ")}</p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{["reported", "reconciled", "estimated", "unknown"].map((status) => {
        const item = data.costs.find((row) => row.cost_status === status);
        return <section key={status} className="glass-panel p-5"><h2 className="text-xs font-medium text-slate-600">{status}</h2>
          <p className="mt-2 text-lg font-semibold">{status === "unknown" ? `${item?.calls ?? 0} lượt chưa rõ giá` : money(item?.known_micros ?? 0)}</p>
          {status !== "unknown" && <p className="mt-1 text-xs text-slate-600">{item?.calls ?? 0} lượt gọi</p>}</section>;
      })}</div>
    </>}
    <Health />
    {data && <div className="grid gap-5 xl:grid-cols-2"><CostTable title="Chi phí theo ngày (UTC)" rows={[...data.by.day].sort((a, b) => (b.key ?? "").localeCompare(a.key ?? ""))} />
      <CostTable title="Chi phí theo model" rows={data.by.model} /><CostTable title="Chi phí theo workspace" rows={data.by.workspace} /><CostTable title="Chi phí theo loại xử lý" rows={data.by.kind} /></div>}
  </div>;
}

function WorkspaceRow({ item }: { item: AdminWorkspace }) {
  const action = useAdminAction();
  const [plan, setPlan] = useState(item.plan);
  const [confirming, setConfirming] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  return <tr><td><p className="font-medium">{item.name}</p><Id value={item.id} /><p className="mt-1 text-slate-600">{item.kind}</p></td>
    <td><Badge value={item.status} /></td><td>{item.members} thành viên<br />{item.documents} tài liệu</td>
    <td><form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void action.run(`/workspaces/${item.id}/plan`, "PATCH", { plan }); }}>
      <select aria-label={`Gói của ${item.name}`} disabled={action.busy || item.status === "purging"} value={plan} onChange={(event) => setPlan(event.target.value as "free" | "pro")} className="rounded-lg border border-slate-300 bg-white p-2">
        <option value="free">Free</option><option value="pro">Pro</option></select><button className="secondary-button text-xs" disabled={plan === item.plan || action.busy || item.status === "purging"}>Lưu</button></form></td>
    <td className="min-w-[260px]"><div className="flex flex-wrap gap-2">
      {item.status === "active" && <button className="secondary-button text-xs" disabled={action.busy} onClick={() => void action.run(`/workspaces/${item.id}/archive`)}>Archive</button>}
      {item.status === "archived" && <><button className="secondary-button text-xs" disabled={action.busy} onClick={() => void action.run(`/workspaces/${item.id}/restore`)}>Khôi phục</button>
        <button className="secondary-button text-xs text-red-700" disabled={action.busy} aria-expanded={confirming} onClick={() => setConfirming(!confirming)}>Xóa vĩnh viễn</button></>}
    </div>
    {confirming && <form className="mt-3 space-y-3 rounded-xl border border-red-200 bg-red-50 p-3" onSubmit={(event) => { event.preventDefault(); void action.run(`/workspaces/${item.id}/purge`, "POST", { confirm_workspace_id: confirmation }); }}>
      <p className="text-red-800">Xóa PDF, vector và hội thoại của mọi thành viên. Thao tác không thể hoàn tác.</p>
      <label className="block">Nhập ID workspace để xác nhận<input className="mt-2 w-full rounded-lg border border-red-300 bg-white p-2" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" /></label>
      <button className="rounded-lg bg-red-700 px-3 py-2 text-white disabled:opacity-50" disabled={confirmation !== item.id || action.busy}>Bắt đầu xóa</button>
    </form>}
    {action.error && <div className="mt-3"><ErrorMessage message={action.error} /></div>}</td></tr>;
}

function Workspaces() {
  return <div className="space-y-5"><Resource<AdminWorkspace> path="/workspaces" title="Workspace và gói sử dụng">{(items) =>
    <Table headers={["Workspace", "Trạng thái", "Quy mô", "Gói", "Thao tác"]}>{items.map((item) => <WorkspaceRow key={`${item.id}:${item.plan}:${item.status}`} item={item} />)}</Table>}</Resource>
    <Resource<AdminPurge> path="/purges" title="Tiến trình xóa workspace">{(items) => <Table headers={["Workspace", "Trạng thái", "Tiến độ", "Cập nhật (UTC)"]}>{items.map((item) => <tr key={item.workspace_id}>
      <td><Id value={item.workspace_id} /></td><td><Badge value={item.status} /></td><td>{item.deleted} / {item.total} đã xóa · {item.deleting} đang xóa · {item.failed} lỗi
        <progress aria-label={`Tiến độ ${item.workspace_id}`} className="mt-2 block w-full accent-blue-600" max={Math.max(1, item.total)} value={item.status === "completed" ? Math.max(1, item.total) : item.deleted} /></td><td>{date(item.updated_at)}</td>
    </tr>)}</Table>}</Resource></div>;
}

function DocumentRow({ item }: { item: AdminDocument }) {
  const action = useAdminAction();
  return <tr><td><Id value={item.doc_id} /><p className="mt-2">Workspace: <Id value={item.workspace_id} /></p><p>Owner: <Id value={item.owner_user_id} /></p></td>
    <td><Badge value={item.status} /><p className="mt-2">RQ: {item.queue_state ?? "đã hết hạn"}</p><p className="mt-1 text-amber-800">{item.error_code}</p></td>
    <td>{item.chunks_count} chunks<br />{item.size_bytes.toLocaleString("vi-VN")} bytes</td>
    <td><p>Job: <Id value={item.job_id} /></p><p className="mt-1">Request: <Id value={item.request_id} /></p><p>Lần chạy: {item.attempt_number}</p></td>
    <td>{["error", "delete_error"].includes(item.status) && <button className="secondary-button text-xs" disabled={action.busy} onClick={() => void action.run(`/documents/${item.doc_id}/retry`)}>Thử lại</button>}
      {action.error && <ErrorMessage message={action.error} />}</td></tr>;
}

function Documents() {
  const [workspace, setWorkspace] = useState("");
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("");
  const params = new URLSearchParams();
  if (workspace) params.set("workspace_id", workspace);
  if (status) params.set("status", status);
  const path = `/documents?${params}`;
  return <div className="space-y-5"><form className="glass-panel flex flex-wrap items-end gap-3 p-5" onSubmit={(event) => { event.preventDefault(); setWorkspace(draft.trim()); }}>
    <label className="flex-1 text-xs font-medium">ID workspace<input className="mt-2 block w-full min-w-[200px] rounded-lg border border-slate-300 bg-white p-2.5" placeholder="Tất cả workspace" value={draft} onChange={(event) => setDraft(event.target.value)} /></label>
    <label className="text-xs font-medium">Trạng thái<select className="mt-2 block rounded-lg border border-slate-300 bg-white p-2.5" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">Tất cả</option>{["queued", "processing", "ready", "error", "deleting", "delete_error"].map((value) => <option key={value}>{value}</option>)}</select></label>
    <button className="secondary-button">Lọc</button>
  </form><Resource<AdminDocument> key={path} path={path} title="Metadata tài liệu">{(items) => <Table headers={["Định danh", "Trạng thái", "Kích thước", "Truy vết", "Thao tác"]}>{items.map((item) => <DocumentRow key={item.doc_id} item={item} />)}</Table>}</Resource>
    <p className="text-xs text-slate-600">Bộ lọc quét từng trang catalog; trang trống vẫn có thể có trang tiếp theo.</p></div>;
}

function Failures() {
  return <Resource<AdminFailure> path="/failures" title="Lịch sử lỗi xử lý">{(items) => <Table headers={["Tài liệu / workspace", "Lỗi", "Job / request", "Thời điểm (UTC)"]}>{items.map((item) => <tr key={item.id}>
    <td><Id value={item.doc_id} /><p className="mt-1"><Id value={item.workspace_id} /></p></td><td><Badge value={item.error_code} /><p className="mt-2 max-w-xs">{item.message}</p></td>
    <td><Id value={item.job_id} /><p className="mt-1"><Id value={item.request_id} /></p><p>{item.kind} · lần {item.attempt}</p></td><td>{date(item.created_at)}</td>
  </tr>)}</Table>}</Resource>;
}
function Audit() {
  return <Resource<AdminAudit> path="/audit" title="Nhật ký thao tác">{(items) => <Table headers={["Thao tác", "Người thực hiện", "Đối tượng", "Request", "Thời điểm (UTC)"]}>{items.map((item) => <tr key={item.id}>
    <td className="max-w-xs break-all"><p className="font-medium">{item.action}</p>{Object.entries(item.metadata).map(([key, value]) => <p key={key} className="mt-1 text-slate-600">{key}: {String(value)}</p>)}</td><td><Id value={item.actor_user_id} /></td><td><Id value={item.target_id} /></td><td><Id value={item.request_id} /></td><td>{date(item.created_at)}</td>
  </tr>)}</Table>}</Resource>;
}

function AdminConsole({ token, denied }: { token: string; denied: () => void }) {
  const [tab, setTab] = useState("overview");
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  return <AdminContext.Provider value={{ token, denied, refresh, revision }}><div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-1">
    <section className="glass-panel flex flex-wrap items-center justify-between gap-4 p-5"><div><p className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck size={18} aria-hidden="true" />Platform admin</p>
      <p className="mt-2 text-xs text-slate-600">Metadata, chi phí và vận hành. Nội dung tài liệu và hội thoại luôn riêng tư.</p></div>
      <button className="secondary-button" onClick={refresh}><RefreshCw size={16} aria-hidden="true" />Làm mới</button></section>
    <nav className="flex flex-wrap gap-2" aria-label="Mục quản trị">{[["overview", "Tổng quan"], ["workspaces", "Workspaces"], ["documents", "Tài liệu"], ["failures", "Lỗi xử lý"], ["audit", "Audit"]].map(([key, label]) =>
      <button key={key} className={`secondary-button ${tab === key ? "border-blue-300 bg-blue-50 text-blue-700" : ""}`} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}</nav>
    {tab === "overview" ? <Overview /> : tab === "workspaces" ? <Workspaces /> : tab === "documents" ? <Documents /> : tab === "failures" ? <Failures /> : <Audit />}
  </div></AdminContext.Provider>;
}

function AdminSession({ token }: { token: string }) {
  const [allowed, setAllowed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const denied = useCallback(() => { setAllowed(false); setError("Tài khoản không có quyền platform admin hoặc phiên đăng nhập đã hết hạn."); }, []);
  useEffect(() => {
    const controller = new AbortController();
    setAllowed(false); setError(null);
    void adminRequest<{ admin: boolean }>(token, "/access", { signal: controller.signal }).then((result) => {
      if (!controller.signal.aborted) { if (result.admin === true) setAllowed(true); else denied(); }
    }).catch((cause) => {
      if (controller.signal.aborted) return;
      if (forbidden(cause)) denied();
      else setError(cause instanceof Error ? cause.message : "Không thể kiểm tra quyền quản trị.");
    });
    return () => controller.abort();
  }, [token, attempt, denied]);
  if (allowed) return <AdminConsole token={token} denied={denied} />;
  return <section className="glass-panel space-y-4 p-6">{error ? <><ErrorMessage message={error} /><button className="secondary-button" onClick={() => setAttempt((value) => value + 1)}>Kiểm tra lại</button></>
    : <p role="status" className="text-sm">Đang kiểm tra quyền quản trị…</p>}</section>;
}

export default function AdminPage() {
  const workspace = useWorkspace();
  if (!workspace.accessToken || !workspace.user) return <p role="status">Đăng nhập để tiếp tục.</p>;
  if (workspace.mock) return <p className="glass-panel p-6">Cấu hình API backend để sử dụng quản trị nền tảng.</p>;
  return <AdminSession key={`${workspace.user.id}:${workspace.accessToken}`} token={workspace.accessToken} />;
}

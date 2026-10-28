import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import AdminPage from "@/app/(workspace)/admin/page";
import { adminRequest, ApiError } from "@/lib/api";
import type { AdminDocument, AdminOverview, AdminWorkspace } from "@/types/admin";

const state = vi.hoisted(() => ({ workspace: {} as Record<string, unknown> }));
vi.mock("@/components/workspace/WorkspaceProvider", () => ({ useWorkspace: () => state.workspace }));
vi.mock("@/lib/api", async (original) => ({ ...await original<typeof import("@/lib/api")>(), adminRequest: vi.fn() }));

const workspace: AdminWorkspace = {
  id: "33333333-3333-4333-8333-333333333333", name: "Test team", kind: "team", status: "archived", plan: "free",
  created_by: "owner-id", created_at: "2026-10-29T00:00:00Z", members: 2, documents: 1,
};
const document: AdminDocument = {
  doc_id: "22222222-2222-4222-8222-222222222222", workspace_id: workspace.id, owner_user_id: "member-id",
  status: "error", chunks_count: 0, size_bytes: 100, created_at: workspace.created_at, updated_at: workspace.created_at,
  error_code: "invalid_pdf", job_id: "job-id", request_id: "request-id", attempt_number: 1, queue_state: "finished",
};
const overview: AdminOverview = {
  since: workspace.created_at, documents: 1, workspaces: [{ status: "archived", count: 1 }],
  costs: [{ cost_status: "reported", calls: 2, known_micros: 250000 }, { cost_status: "unknown", calls: 3, known_micros: 0 }],
  by: { day: [], workspace: [], kind: [], model: [] },
  chat: { requests: 2, failed: 0, interrupted: 1, cache_hits: 1, latency_p50_ms: 100, latency_p95_ms: 200, first_token_p50_ms: 50, first_token_p95_ms: 75 },
};
const empty = { items: [], next_offset: null };
const api = vi.mocked(adminRequest);
function answer(path: string): unknown {
  if (path === "/access") return { admin: true };
  if (path.startsWith("/overview")) return overview;
  if (path === "/health") return { status: "ok", checks: { postgres: { status: "ok", latency_ms: 2 } } };
  if (path.startsWith("/workspaces?")) return { items: [workspace], next_offset: null };
  if (path.startsWith("/documents?")) return { items: [{ ...document, name: "private.pdf", storage_key: "private-key", content: "private transcript" }], next_offset: null };
  return empty;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
beforeEach(() => {
  state.workspace = { user: { id: "admin" }, accessToken: "token", mock: false };
  api.mockReset().mockImplementation(async (_token, path) => answer(path));
});

it("authorizes before reports and never infers platform access from workspace ownership", async () => {
  const access = deferred<unknown>();
  api.mockReturnValueOnce(access.promise);
  render(<AdminPage />);
  expect(api).toHaveBeenCalledTimes(1);
  expect(api.mock.calls[0][1]).toBe("/access");
  await act(async () => access.resolve({ admin: false }));
  expect(screen.getByRole("alert")).toHaveTextContent("không có quyền platform admin");
  expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  expect(api).toHaveBeenCalledTimes(1);
});

it("renders known USD and unknown call counts separately, and only explicit metadata fields", async () => {
  render(<AdminPage />);
  expect(await screen.findByText("0.25 USD")).toBeInTheDocument();
  expect(screen.getByText("3 lượt chưa rõ giá")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Tài liệu" }));
  expect(await screen.findByText(document.doc_id)).toBeInTheDocument();
  expect(screen.getByText("RQ: finished")).toBeInTheDocument();
  expect(screen.getByText("request-id")).toBeInTheDocument();
  for (const value of ["private.pdf", "private-key", "private transcript"]) expect(screen.queryByText(value)).not.toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it.each(["identity", "token"])("aborts reports and actions and rejects late results after %s changes", async (change) => {
  const mutation = deferred<unknown>();
  api.mockImplementation(async (_token, path, options) => options?.method === "POST" ? mutation.promise : answer(path));
  const { rerender } = render(<AdminPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Tài liệu" }));
  fireEvent.click(await screen.findByRole("button", { name: "Thử lại" }));
  const signal = api.mock.calls.find(([, path]) => path.endsWith("/retry"))?.[2]?.signal;
  const access = deferred<unknown>();
  api.mockReturnValue(access.promise);
  state.workspace = { ...state.workspace, ...(change === "identity" ? { user: { id: "member" } } : { accessToken: "renewed" }) };
  rerender(<AdminPage />);
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  const calls = api.mock.calls.length;
  await act(async () => mutation.resolve({ ...document, status: "queued" }));
  expect(api).toHaveBeenCalledTimes(calls);
  expect(screen.queryByText(document.doc_id)).not.toBeInTheDocument();
  await act(async () => access.resolve({ admin: false }));
  expect(screen.getByRole("alert")).toBeInTheDocument();
});

it("clears all panels on a revoked role response and aborts other in-flight reads", async () => {
  const health = deferred<unknown>();
  api.mockImplementation(async (_token, path) => path === "/health" ? health.promise : answer(path));
  render(<AdminPage />);
  await screen.findByText("0.25 USD");
  const signal = api.mock.calls.find(([, path]) => path === "/health")?.[2]?.signal;
  api.mockRejectedValue(new ApiError("Forbidden", 403, "admin_required"));
  fireEvent.click(screen.getByRole("button", { name: "Làm mới" }));
  await screen.findByRole("alert");
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByText("0.25 USD")).not.toBeInTheDocument();
  await act(async () => health.resolve({ status: "ok", checks: {} }));
  expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
});

it("continues a filtered empty catalog page and resets pagination when filters change", async () => {
  api.mockImplementation(async (_token, path) => path.startsWith("/documents?")
    ? (path.includes("offset=20") ? { items: [document], next_offset: null } : { items: [], next_offset: 20 }) : answer(path));
  render(<AdminPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Tài liệu" }));
  await screen.findByText("Không có kết quả trong trang này.");
  fireEvent.click(screen.getByRole("button", { name: "Trang sau" }));
  await screen.findByText(document.doc_id);
  expect(screen.getByText("Trang 2")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Trạng thái"), { target: { value: "error" } });
  await waitFor(() => expect(api.mock.calls.at(-1)?.[1]).toContain("status=error&limit=20&offset=0"));
  expect(screen.queryByText(document.doc_id)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Trang trước" })).toBeDisabled();
});

it("requires the exact workspace ID for purge and never retries an uncertain mutation automatically", async () => {
  api.mockImplementation(async (_token, path, options) => {
    if (options?.method === "POST") throw new ApiError("Service unavailable", 503);
    return answer(path);
  });
  render(<AdminPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Workspaces" }));
  fireEvent.click(await screen.findByRole("button", { name: "Xóa vĩnh viễn" }));
  const submit = screen.getByRole("button", { name: "Bắt đầu xóa" });
  expect(submit).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Nhập ID workspace để xác nhận"), { target: { value: "wrong-id" } });
  expect(submit).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Nhập ID workspace để xác nhận"), { target: { value: workspace.id } });
  expect(submit).toBeEnabled();
  fireEvent.click(submit);
  expect(await screen.findByRole("alert")).toHaveTextContent("Làm mới để kiểm tra trạng thái");
  const posts = api.mock.calls.filter(([, , options]) => options?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0]).toEqual(["token", `/workspaces/${workspace.id}/purge`, expect.objectContaining({ body: { confirm_workspace_id: workspace.id } })]);
  expect(within(screen.getByRole("region", { name: "Workspace và gói sử dụng" })).getByText("Test team")).toBeInTheDocument();
});

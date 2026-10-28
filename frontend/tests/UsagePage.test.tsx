import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import UsagePage from "@/app/(workspace)/usage/page";
import { getUsage } from "@/lib/api";
import type { UsageSummary, Workspace } from "@/types";

const state = vi.hoisted(() => ({ workspace: null as unknown }));
vi.mock("@/components/workspace/WorkspaceProvider", () => ({
  useWorkspace: () => state.workspace,
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  getUsage: vi.fn(),
}));

const activeWorkspace: Workspace = {
  id: "workspace-a", name: "Nhóm học tập", kind: "team", role: "owner",
  plan: "free", status: "active", created_at: null,
};

const usage: UsageSummary = {
  workspace_id: "workspace-a", scope: "workspace", plan: "free",
  period_start: "2026-10-01T00:00:00Z", reset_at: "2026-11-01T00:00:00Z",
  chat: { used: 4, limit: 10, remaining: 6, metric: "chat_questions_month" },
  documents: { used: 2, limit: 5, remaining: 3, metric: "documents" },
  by_user: [{
    user_id: "owner", chat_questions: 4, cost_micros: 250000, cost_unknown_calls: 1,
  }],
  costs: { known_micros: 250000, unknown_calls: 1 },
};

beforeEach(() => {
  vi.mocked(getUsage).mockReset().mockResolvedValue(usage);
  state.workspace = {
    mock: false, accessToken: "token", workspaceId: "workspace-a",
    activeWorkspace, user: { id: "owner" },
  };
});

it("renders plan counters, reset date, costs and the owner privacy note", async () => {
  render(<UsagePage />);

  expect(await screen.findByText("Gói Free")).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "Câu hỏi trong tháng" }))
    .toHaveAttribute("aria-valuenow", "4");
  expect(screen.getByRole("progressbar", { name: "Tài liệu trong workspace" }))
    .toHaveAttribute("aria-valuenow", "2");
  expect(screen.getByText("Còn lại 6 · đặt lại hằng tháng")).toBeInTheDocument();
  expect(screen.getByText("Còn lại 3 · không đặt lại hằng tháng")).toBeInTheDocument();
  expect(screen.getByText(/01\/11\/2026/)).toBeInTheDocument();
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Tổng chi phí đã biết" })).getByText("0.25 USD")).toBeInTheDocument();
  expect(screen.getByText(/1 lượt gọi chưa xác định chi phí/)).toBeInTheDocument();
  expect(screen.getByText(/hiển thị bằng USD/)).toBeInTheDocument();
  expect(screen.getByText("1 lượt")).toBeInTheDocument();
  expect(screen.getByText(/Chủ workspace chỉ thấy số liệu tổng hợp/)).toBeInTheDocument();
  expect(getUsage).toHaveBeenCalledWith("token", "workspace-a", expect.any(AbortSignal));
});

it("shows personal counts and shared plan limits without implying remaining quota for a member", async () => {
  state.workspace = { ...(state.workspace as object), activeWorkspace: { ...activeWorkspace, role: "member" } };
  vi.mocked(getUsage).mockResolvedValue({
    ...usage, scope: "self", chat: { ...usage.chat, remaining: null }, documents: { ...usage.documents, remaining: null },
  });
  render(<UsagePage />);
  expect(await screen.findByText("Chi phí đã biết của bạn")).toBeInTheDocument();
  expect(screen.getByText("Câu hỏi của bạn trong tháng")).toBeInTheDocument();
  expect(screen.getByText(/Hạn mức chung của workspace: 10/)).toBeInTheDocument();
  expect(screen.queryByText(/Còn lại/)).not.toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function switchWorkspace() {
  state.workspace = { ...(state.workspace as object), workspaceId: "workspace-b",
    activeWorkspace: { ...activeWorkspace, id: "workspace-b", plan: "pro" } };
}

it.each(["initial", "refresh"])("ignores late %s results after switching workspace and hides old data immediately", async (kind) => {
  const old = deferred<UsageSummary>();
  const next = deferred<UsageSummary>();
  const mock = vi.mocked(getUsage);
  if (kind === "initial") mock.mockReturnValueOnce(old.promise);
  else mock.mockResolvedValueOnce(usage).mockReturnValueOnce(old.promise);
  const { rerender } = render(<UsagePage />);
  if (kind === "refresh") {
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Làm mới" }));
  }
  const oldSignal = mock.mock.calls.at(-1)?.[2];
  mock.mockReturnValueOnce(next.promise);
  switchWorkspace();
  rerender(<UsagePage />);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(screen.getByText("Gói Pro")).toBeInTheDocument();
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => old.resolve(usage));
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Đang tải…" })).toBeDisabled();
  await act(async () => next.resolve({ ...usage, workspace_id: "workspace-b", plan: "pro" }));
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByText("Gói Pro")).toBeInTheDocument();
});

it("ignores a late refresh failure after switching workspace", async () => {
  const old = deferred<UsageSummary>();
  vi.mocked(getUsage).mockResolvedValueOnce(usage).mockReturnValueOnce(old.promise);
  const { rerender } = render(<UsagePage />);
  await screen.findByRole("table");
  fireEvent.click(screen.getByRole("button", { name: "Làm mới" }));
  vi.mocked(getUsage).mockResolvedValueOnce({ ...usage, workspace_id: "workspace-b", plan: "pro" });
  switchWorkspace();
  rerender(<UsagePage />);
  await screen.findByRole("table");
  await act(async () => old.reject(new Error("Old workspace failed")));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("aborts a manual refresh when unmounted", async () => {
  vi.mocked(getUsage).mockResolvedValueOnce(usage).mockReturnValueOnce(new Promise(() => {}));
  const { unmount } = render(<UsagePage />);
  await screen.findByRole("table");
  fireEvent.click(screen.getByRole("button", { name: "Làm mới" }));
  const signal = vi.mocked(getUsage).mock.calls.at(-1)?.[2];
  unmount();
  expect(signal?.aborted).toBe(true);
});

it.each(["identity", "role", "deselection"])("clears previous data on %s changes", async (change) => {
  const { rerender } = render(<UsagePage />);
  await screen.findByRole("table");
  vi.mocked(getUsage).mockReturnValue(new Promise(() => {}));
  state.workspace = { ...(state.workspace as object), ...(change === "identity" ? { user: { id: "new-user" } }
    : change === "role" ? { activeWorkspace: { ...activeWorkspace, role: "member" } } : { workspaceId: null, activeWorkspace: null }) };
  rerender(<UsagePage />);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  if (change === "deselection") expect(screen.getByText("Chọn workspace để xem mức sử dụng.")).toBeInTheDocument();
});

it("rejects a response for the wrong workspace", async () => {
  vi.mocked(getUsage).mockResolvedValueOnce({ ...usage, workspace_id: "wrong" });
  render(<UsagePage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Số liệu không khớp workspace hiện tại");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("supersedes a refresh when authentication is renewed", async () => {
  const old = deferred<UsageSummary>();
  vi.mocked(getUsage).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ ...usage, chat: { ...usage.chat, used: 5 } });
  const { rerender } = render(<UsagePage />);
  const signal = vi.mocked(getUsage).mock.calls[0][2];
  state.workspace = { ...(state.workspace as object), accessToken: "new-token" };
  rerender(<UsagePage />);
  await waitFor(() => expect(screen.getByRole("progressbar", { name: "Câu hỏi trong tháng" })).toHaveAttribute("aria-valuenow", "5"));
  expect(signal?.aborted).toBe(true);
  await act(async () => old.resolve(usage));
  expect(screen.getByRole("progressbar", { name: "Câu hỏi trong tháng" })).toHaveAttribute("aria-valuenow", "5");
});

it("shows an inline error when usage cannot be loaded", async () => {
  vi.mocked(getUsage).mockRejectedValue(new Error("Không thể tải mức sử dụng."));

  render(<UsagePage />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Không thể tải mức sử dụng.");
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

it("uses the demo plan without calling the API in demo mode", async () => {
  state.workspace = { ...(state.workspace as object), mock: true };

  render(<UsagePage />);

  expect(await screen.findByText("Gói Free")).toBeInTheDocument();
  expect(screen.getByText("Còn lại 10 · đặt lại hằng tháng")).toBeInTheDocument();
  expect(getUsage).not.toHaveBeenCalled();
});

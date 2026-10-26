import { render, screen } from "@testing-library/react";
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
  workspace_id: "workspace-a", plan: "free",
  period_start: "2026-10-01T00:00:00Z", reset_at: "2026-11-01T00:00:00Z",
  chat: { used: 4, limit: 10, remaining: 6, metric: "chat_questions_month" },
  documents: { used: 2, limit: 5, remaining: 3, metric: "documents" },
  by_user: [{
    user_id: "owner", chat_questions: 4, cost_micros: 250000, cost_unknown_calls: 1,
  }],
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
  expect(screen.getByText("0.25 USD")).toBeInTheDocument();
  expect(screen.getByText("1 lượt")).toBeInTheDocument();
  expect(screen.getByText(/Chủ workspace chỉ thấy số liệu tổng hợp/)).toBeInTheDocument();
  expect(getUsage).toHaveBeenCalledWith("token", "workspace-a", expect.any(AbortSignal));
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

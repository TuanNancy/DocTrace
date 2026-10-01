import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { UploadZone } from "@/components/UploadZone";
import { uploadPDF } from "@/lib/api";
import type { UploadResponse } from "@/types";

vi.mock("@/lib/api", () => ({ uploadPDF: vi.fn() }));
const uploadMock = vi.mocked(uploadPDF);
const pdf = (name = "a.pdf") => new File(["%PDF"], name, { type: "application/pdf" });
const result = { doc_id: "doc-a", chunks_count: 3 };

beforeEach(() => { uploadMock.mockReset(); });

it("allows choosing another PDF after a successful upload", async () => {
  uploadMock.mockResolvedValue(result);
  const onUploadComplete = vi.fn();
  render(<UploadZone mock={false} accessToken="token" onUploadComplete={onUploadComplete} />);
  fireEvent.change(screen.getByLabelText("Chọn file"), { target: { files: [pdf()] } });
  await screen.findByText("Tải lên thành công");
  fireEvent.change(screen.getByLabelText("Chọn file khác"), { target: { files: [pdf("b.pdf")] } });
  await waitFor(() => expect(onUploadComplete).toHaveBeenCalledTimes(2));
});

it("allows retrying after an API error", async () => {
  uploadMock.mockRejectedValueOnce(new Error("Server unavailable")).mockResolvedValue(result);
  render(<UploadZone mock={false} accessToken="token" />);
  fireEvent.change(screen.getByLabelText("Chọn file"), { target: { files: [pdf()] } });
  await screen.findByText("Server unavailable");
  fireEvent.change(screen.getByLabelText("Thử lại"), { target: { files: [pdf()] } });
  await screen.findByText("Tải lên thành công");
});

it("does not start a second upload when files are dropped while busy", async () => {
  let resolve!: (value: UploadResponse) => void;
  uploadMock.mockReturnValue(new Promise((r) => { resolve = r; }));
  const { container } = render(<UploadZone mock={false} accessToken="token" />);
  fireEvent.change(screen.getByLabelText("Chọn file"), { target: { files: [pdf()] } });
  const dropZone = container.firstElementChild!.firstElementChild!;
  fireEvent.dragOver(dropZone);
  fireEvent.drop(dropZone, { dataTransfer: { files: [pdf("b.pdf")] } });
  expect(uploadMock).toHaveBeenCalledTimes(1);
  await act(async () => resolve(result));
});

it("aborts on unmount and ignores a late upload result", async () => {
  let resolve!: (value: UploadResponse) => void;
  uploadMock.mockReturnValue(new Promise((r) => { resolve = r; }));
  const onUploadComplete = vi.fn();
  const { unmount } = render(<UploadZone mock={false} accessToken="token" onUploadComplete={onUploadComplete} />);
  fireEvent.change(screen.getByLabelText("Chọn file"), { target: { files: [pdf()] } });
  const signal = uploadMock.mock.calls[0][2];
  unmount();
  await act(async () => resolve(result));
  expect(signal?.aborted).toBe(true);
  expect(onUploadComplete).not.toHaveBeenCalled();
});

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MessageMarkdown } from "@/components/MessageMarkdown";

it("renders GFM and binds only known citation IDs outside code", () => {
  const source = { citation_id: 1, chunk_id: "chunk", doc_id: "doc", page: 3, source: "a.pdf", score: null };
  const select = vi.fn();
  render(<MessageMarkdown content={"## Kết quả\n\nNội dung **chính** [1] và [99].\n\n`[1]`\n\n| A | B |\n|---|---|\n| 1 | 2 |"} sources={[source]} onSelectSource={select} />);
  expect(screen.getByRole("heading", { name: "Kết quả" })).toBeInTheDocument();
  expect(screen.getByRole("table")).toBeInTheDocument();
  const button = screen.getByRole("button", { name: "Xem nguồn 1, trang 3" });
  fireEvent.click(button);
  expect(select).toHaveBeenCalledWith(source);
  expect(screen.getAllByRole("button")).toHaveLength(1);
});

it("does not execute raw HTML or unsafe links from model output", () => {
  const { container } = render(<MessageMarkdown content={'<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[bad](javascript:alert%281%29)'} />);
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
});

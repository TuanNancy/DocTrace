import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "./globals.css";

export const metadata: Metadata = {
  title: "DocTrace · Hỏi đáp tài liệu",
  description: "Khám phá tài liệu PDF cùng DocTrace — câu trả lời rõ ràng, trích dẫn nguồn có thể kiểm chứng.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" suppressHydrationWarning className="font-sans">
      <body className="min-h-screen bg-[var(--bg)]">{children}</body>
    </html>
  );
}

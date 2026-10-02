import type { Metadata } from "next";
import "./globals.css";
import { Inter } from "next/font/google";
import { cn } from "@/lib/utils";

const inter = Inter({ subsets: ["latin", "vietnamese"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Baymax · Hỏi đáp tài liệu",
  description: "Khám phá tài liệu PDF cùng Baymax — câu trả lời rõ ràng, trích dẫn nguồn có thể kiểm chứng.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" suppressHydrationWarning className={cn("font-sans", inter.variable)}>
      <body className="min-h-screen bg-[var(--bg)]">{children}</body>
    </html>
  );
}

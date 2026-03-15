import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RAG PDF Chatbot",
  description: "Upload PDFs and chat with your documents",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <body className="min-h-screen bg-[var(--bg)]">{children}</body>
    </html>
  );
}

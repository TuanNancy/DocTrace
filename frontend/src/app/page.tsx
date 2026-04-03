import Link from "next/link";
import { BrandMark } from "@/components/BrandMark";
import { ThemeToggle } from "@/components/ThemeToggle";

const FEATURES = [
  {
    icon: "📄",
    title: "Upload & Index PDF",
    desc: "Tải lên tài liệu PDF, hệ thống tự động trích xuất nội dung và tạo chỉ mục tìm kiếm.",
  },
  {
    icon: "🔍",
    title: "Tìm kiếm thông minh",
    desc: "Đặt câu hỏi bằng ngôn ngữ tự nhiên, AI tìm các đoạn liên quan nhất trong tài liệu.",
  },
  {
    icon: "💬",
    title: "Hỏi đáp với AI",
    desc: "Nhận câu trả lời chính xác kèm trích dẫn số trang, stream theo thời gian thực.",
  },
  {
    icon: "🔒",
    title: "Bảo mật & Riêng tư",
    desc: "Xác thực qua Supabase, mỗi người dùng chỉ truy cập tài liệu của mình.",
  },
];

const STEPS = [
  { step: "1", title: "Upload PDF", desc: "Kéo thả hoặc chọn file PDF để tải lên." },
  { step: "2", title: "Đặt câu hỏi", desc: "Hỏi bất kỳ điều gì về nội dung tài liệu." },
  { step: "3", title: "Nhận câu trả lời", desc: "AI trả lời kèm nguồn trang cụ thể." },
];

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col bg-[#f7f7f4] dark:bg-slate-900">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-[#B22222]/10 px-6 py-4">
        <BrandMark />
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <Link
            href="/auth/login"
            className="rounded-lg px-4 py-2 text-sm font-medium text-slate-700 transition hover:text-[#B22222] dark:text-slate-300"
          >
            Đăng nhập
          </Link>
          <Link
            href="/auth/signup"
            className="rounded-lg bg-[#B22222] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#9a1d1d]"
          >
            Đăng ký
          </Link>
        </div>
      </header>

      {/* Hero */}
      <section className="flex flex-1 items-center justify-center px-6 py-20">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-slate-100 sm:text-5xl">
            Hỏi đáp thông minh trên{" "}
            <span className="text-[#B22222]">tài liệu PDF</span>
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-lg text-slate-600 dark:text-slate-400">
            Upload tài liệu PDF, đặt câu hỏi bằng ngôn ngữ tự nhiên và nhận câu trả lời chính xác kèm trích dẫn số trang.
          </p>
          <div className="mt-10 flex items-center justify-center gap-4">
            <Link
              href="/auth/signup"
              className="rounded-xl bg-[#B22222] px-8 py-3 text-base font-semibold text-white shadow-lg shadow-[#B22222]/20 transition hover:bg-[#9a1d1d]"
            >
              Bắt đầu miễn phí
            </Link>
            <Link
              href="/auth/login"
              className="rounded-xl border border-slate-300 px-8 py-3 text-base font-semibold text-slate-700 transition hover:border-[#B22222] hover:text-[#B22222] dark:border-slate-600 dark:text-slate-300"
            >
              Đăng nhập
            </Link>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="border-t border-[#B22222]/10 px-6 py-16">
        <div className="mx-auto max-w-4xl">
          <h2 className="mb-10 text-center text-2xl font-semibold text-slate-900 dark:text-slate-100">
            Cách hoạt động
          </h2>
          <div className="grid gap-8 sm:grid-cols-3">
            {STEPS.map((s) => (
              <div key={s.step} className="flex flex-col items-center text-center">
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#B22222] text-lg font-bold text-white">
                  {s.step}
                </div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  {s.title}
                </h3>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="border-t border-[#B22222]/10 px-6 py-16">
        <div className="mx-auto max-w-4xl">
          <h2 className="mb-10 text-center text-2xl font-semibold text-slate-900 dark:text-slate-100">
            Tính năng
          </h2>
          <div className="grid gap-6 sm:grid-cols-2">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm transition hover:shadow-md dark:border-slate-700 dark:bg-slate-800"
              >
                <div className="mb-3 text-2xl">{f.icon}</div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  {f.title}
                </h3>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-[#B22222]/10 px-6 py-6 text-center text-xs text-slate-500">
        Baymax — AI-powered PDF Q&A
      </footer>
    </div>
  );
}

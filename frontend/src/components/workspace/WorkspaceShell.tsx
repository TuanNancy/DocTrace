"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BarChart3, BookOpen, Building2, ChevronRight, FileText, LogOut, Menu, MessageSquare, Plus, Sparkles, X } from "lucide-react";
import { BrandMark } from "@/components/BrandMark";
import { useWorkspace } from "./WorkspaceProvider";
import { Drawer } from "./Drawer";

function Navigation() {
  const workspace = useWorkspace();
  const pathname = usePathname();
  const router = useRouter();
  return <>
    <Link href="/" className="workspace-brand mb-9 inline-flex" aria-label="DocTrace — Trang chủ"><BrandMark /></Link>
    <div className="mb-7">
      <p className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Không gian làm việc</p>
      <div className="flex items-center gap-2 rounded-xl border border-slate-200/70 bg-white/75 px-2.5 py-2">
        <Building2 size={16} className="shrink-0 text-blue-400" />
        <select
          aria-label="Chọn không gian làm việc"
          className="min-w-0 flex-1 bg-transparent text-xs font-medium text-slate-700 outline-none disabled:opacity-60"
          value={workspace.workspaceId ?? ""}
          disabled={workspace.workspacesLoading || !workspace.workspaces.length}
          onChange={(event) => workspace.switchWorkspace(event.target.value)}
        >
          {!workspace.workspaceId && <option value="">{workspace.workspacesLoading ? "Đang tải…" : "Không có workspace hoạt động"}</option>}
          {workspace.workspaces.map((item) => <option key={item.id} value={item.id} disabled={item.status !== "active"}>
            {item.name}{item.kind === "team" ? " · Nhóm" : ""}{item.status === "archived" ? " — Đã lưu trữ"
              : item.status === "purging" ? " — Đang xóa" : ""}
          </option>)}
        </select>
      </div>
      {workspace.activeWorkspace && <p className="mt-1.5 px-1 text-[10px] text-slate-400">
        {workspace.activeWorkspace.role === "owner" ? "Chủ sở hữu" : "Thành viên"} · {workspace.activeWorkspace.plan === "pro" ? "Pro" : "Free"}
      </p>}
    </div>
    <button className="primary-button mb-7 w-full" onClick={() => { workspace.newChat(); router.push("/chat"); }}>
      <Plus size={18} /> Chat mới
    </button>
    <p className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Điều hướng</p>
    <nav className="space-y-1.5" aria-label="Điều hướng chính">
      {[{ href: "/chat", label: "Hỏi đáp tài liệu", icon: MessageSquare }, { href: "/documents", label: "Thư viện", icon: BookOpen }, { href: "/usage", label: "Mức sử dụng", icon: BarChart3 }].map(({ href, label, icon: Icon }) =>
        <Link key={href} href={href} onClick={() => workspace.setSidebarOpen(false)} aria-current={pathname === href ? "page" : undefined}
          className={`nav-item ${pathname === href ? "nav-item-active" : ""}`}><Icon size={18} />{label}
          {href === "/documents" && <span className="ml-auto text-xs opacity-70">{workspace.documents.length}</span>}
        </Link>)}
    </nav>
    <div className="mt-9 rounded-2xl border border-white/80 bg-white/40 p-4">
      <Sparkles size={18} className="mb-3 text-blue-500" />
      <p className="text-xs font-medium text-slate-700">Hiểu tài liệu, rõ nguồn tin.</p>
      <p className="mt-2 text-xs leading-relaxed text-slate-500">Mỗi câu trả lời đều có đường dẫn để bạn đối chiếu với tài liệu gốc.</p>
    </div>
    <div className="mt-auto pt-8">
      <div className="flex items-center gap-2.5 border-t border-slate-200/60 pt-5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-100 text-sm font-semibold text-blue-600">
          {(workspace.user?.user_metadata?.full_name || workspace.user?.email || "D").slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1"><p className="truncate text-xs font-medium text-slate-700">{workspace.user?.user_metadata?.full_name || "Tài khoản DocTrace"}</p>
          <p className="mt-0.5 truncate text-[10px] text-slate-500">{workspace.user?.email}</p></div>
        <button className="icon-button" aria-label="Đăng xuất" title="Đăng xuất" onClick={() => void workspace.signOut()}><LogOut size={16} /></button>
      </div>
    </div>
  </>;
}

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const workspace = useWorkspace();
  const pathname = usePathname();
  const title = pathname === "/documents" ? "Thư viện tài liệu"
    : pathname === "/usage" ? "Mức sử dụng" : "Hỏi đáp tài liệu";
  if (!workspace.authReady) return <div className="workspace flex min-h-dvh items-center justify-center text-sm text-slate-500">Đang kiểm tra phiên đăng nhập…</div>;
  if (!workspace.user || !workspace.accessToken) return <div className="workspace flex min-h-dvh flex-col items-center justify-center gap-5">
    <BrandMark /><h1 className="font-sans text-2xl">Chào mừng đến với DocTrace</h1>
    <p className="text-sm text-slate-500">Đăng nhập để mở thư viện tài liệu của bạn.</p><Link href="/auth/login" className="primary-button">Đăng nhập <ChevronRight size={16} /></Link>
  </div>;
  return <div className="workspace workspace-background flex h-dvh min-h-[480px] overflow-hidden text-slate-800">
    <aside className="hidden w-[230px] shrink-0 flex-col border-r border-white/80 bg-white/35 px-5 py-7 lg:flex"><Navigation /></aside>
    <Drawer open={workspace.sidebarOpen} onOpenChange={workspace.setSidebarOpen} title="Không gian DocTrace" side="left" below={1024}><Navigation /></Drawer>
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex h-[80px] shrink-0 items-center justify-between gap-3 px-5 sm:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <button className="icon-button lg:hidden" aria-label="Mở điều hướng" onClick={() => workspace.setSidebarOpen(true)}><Menu size={20} /></button>
          <div><p className="hidden text-[10px] font-semibold uppercase tracking-[0.2em] text-blue-500 sm:block">{workspace.activeWorkspace?.name ?? "DocTrace workspace"}</p>
            <h1 className="mt-1 font-sans text-xl font-semibold tracking-tight">{title}</h1></div>
        </div>
        <div className="flex items-center gap-2">
          {workspace.mock && <span className="status-badge status-queued">Demo</span>}
          <Link href="/documents" className="secondary-button text-xs"><FileText size={15} /><span>{workspace.documents.length} tài liệu</span></Link>
        </div>
      </header>
      {workspace.workspaceError && <div role="alert" className="mx-5 mb-3 flex items-start justify-between gap-3 rounded-xl border border-red-100 bg-red-50/90 px-4 py-2.5 text-xs leading-relaxed text-red-700 sm:mx-8">
        <span>Không thể tải không gian làm việc: {workspace.workspaceError}</span>
        <button className="shrink-0 font-medium underline" onClick={() => void workspace.refreshWorkspaces()}>Thử lại</button>
      </div>}
      {workspace.notice && <div role="status" className="mx-5 mb-3 flex items-start justify-between gap-3 rounded-xl border border-blue-100 bg-blue-50/90 px-4 py-2.5 text-xs leading-relaxed text-blue-800 sm:mx-8">
        {workspace.notice}<button aria-label="Đóng thông báo" onClick={() => workspace.setNotice(null)}><X size={16} /></button>
      </div>}
      <main className="flex min-h-0 flex-1 flex-col px-3 pb-3 sm:px-6 sm:pb-5">{children}</main>
    </div>
  </div>;
}

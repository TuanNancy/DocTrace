import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft, BookOpen, Check, FileText, Quote, Sparkles } from "lucide-react";
import { BrandMark } from "@/components/BrandMark";
import styles from "./Auth.module.css";

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link href="/" aria-label="DocTrace — Trang chủ" className={styles.brand}><BrandMark /></Link>
        <Link href="/" className={styles.backLink}><ArrowLeft size={16} aria-hidden="true" /> Về trang chủ</Link>
      </header>

      <main className={styles.main}>
        <div className={styles.shell}>
          <aside className={styles.story} aria-label="Khám phá DocTrace">
            <div className={styles.eyebrow}><Sparkles size={14} aria-hidden="true" /> ĐỌC ÍT HƠN. HIỂU SÂU HƠN.</div>
            <h2>Từ trang PDF,<br />đến điều bạn <em>cần.</em></h2>
            <p className={styles.storyDescription}>Hỏi, tóm tắt và tìm lại nguồn. DocTrace giúp bạn khám phá tài liệu qua từng cuộc trò chuyện.</p>

            <div className={styles.preview} aria-hidden="true">
              <div className={styles.previewHeader}><span><FileText size={16} /> Ghi chú học tập.pdf</span><span className={styles.previewTag}>Minh họa</span></div>
              <div className={styles.previewBody}>
                <p className={styles.question}>Làm sao để ghi nhớ tốt hơn?</p>
                <div className={styles.answer}>
                  <div className={styles.assistantLabel}><Sparkles size={15} /> DocTrace</div>
                  <p>Chia nội dung thành các phần nhỏ và <mark>ôn tập cách quãng</mark> giúp bạn ghi nhớ kiến thức lâu hơn.</p>
                  <div className={styles.citation}><Quote size={12} /><span>1</span> Ghi chú học tập · Trang 4</div>
                </div>
                <div className={styles.source}><BookOpen size={16} /><div><strong>Luôn có nguồn để đối chiếu</strong><p>Từ câu trả lời, trở về đúng trang tài liệu.</p></div></div>
              </div>
            </div>

            <div className={styles.benefits}>
              <span><Check size={15} aria-hidden="true" /> Hỏi bằng tiếng Việt</span>
              <span><Check size={15} aria-hidden="true" /> Trích dẫn theo trang</span>
            </div>
          </aside>
          <section className={styles.formPanel} aria-labelledby="auth-heading">{children}</section>
        </div>
      </main>

      <footer className={styles.footer}>Hiểu tài liệu. Rõ nguồn tin. <span>Đó là DocTrace.</span></footer>
    </div>
  );
}

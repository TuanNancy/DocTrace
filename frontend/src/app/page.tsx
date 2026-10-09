import Link from "next/link";
import { ArrowRight, BookOpen, Check, FileText, Layers3, MessageSquareText, MoveUpRight, Quote, Sparkles, Upload } from "lucide-react";
import { BrandMark } from "@/components/BrandMark";
import { ChatPreview } from "@/components/landing/ChatPreview";
import { TechnologyLogos } from "@/components/landing/TechnologyLogos";
import styles from "@/components/landing/Landing.module.css";

const FEATURES = [
  {
    icon: MessageSquareText,
    number: "01",
    title: "Hỏi tự nhiên. Hiểu rõ hơn.",
    description: "Đặt câu hỏi bằng tiếng Việt. Baymax tìm các đoạn liên quan trong PDF bạn chọn để tạo câu trả lời.",
    detail: "Câu trả lời hiện dần theo thời gian thực",
  },
  {
    icon: Layers3,
    number: "02",
    title: "Tài liệu dài. Ý chính gọn.",
    description: "Yêu cầu tóm tắt để nắm nội dung toàn tài liệu, rồi đặt câu hỏi cụ thể về phần bạn muốn tìm hiểu.",
    detail: "Tóm tắt từ nội dung của PDF đang chọn",
  },
  {
    icon: Quote,
    number: "03",
    title: "Có câu trả lời. Có nguồn.",
    description: "Bấm vào trích dẫn để đọc đoạn gốc và mở PDF đúng trang. Bạn luôn có thể tự đối chiếu thông tin.",
    detail: "Trích dẫn gắn với đoạn văn và số trang",
  },
];

const STEPS = [
  { icon: Upload, title: "Thêm PDF vào thư viện", description: "Đăng nhập, tải lên PDF có nội dung văn bản và chờ tài liệu chuyển sang Sẵn sàng." },
  { icon: MessageSquareText, title: "Chọn tài liệu. Đặt câu hỏi.", description: "Hỏi về một chi tiết cụ thể hoặc yêu cầu Baymax tóm tắt tài liệu đang chọn." },
  { icon: BookOpen, title: "Đọc và đối chiếu nguồn", description: "Theo dõi câu trả lời, mở trích dẫn để kiểm chứng, sao chép hoặc xuất cuộc trò chuyện." },
];

export default function Home() {
  return (
    <div className={styles.landing}>
      <a href="#noi-dung" className={styles.skipLink}>Đến nội dung chính</a>
      <header className={styles.header}>
        <div className={`${styles.container} ${styles.headerInner}`}>
          <Link href="/" aria-label="Baymax — Trang chủ" className={styles.brand}><BrandMark /></Link>
          <nav aria-label="Điều hướng trang chủ" className={styles.navigation}>
            <a href="#tinh-nang">Tính năng</a>
            <a href="#cach-hoat-dong">Cách hoạt động</a>
            <a href="#minh-hoa">Xem minh họa</a>
          </nav>
          <div className={styles.headerActions}>
            <Link href="/auth/login" className={styles.loginLink}>Đăng nhập</Link>
            <Link href="/chat" className={`${styles.primaryButton} ${styles.headerCta}`}>
              Dùng thử ngay <ArrowRight size={15} aria-hidden="true" />
            </Link>
          </div>
        </div>
      </header>

      <main id="noi-dung">
        <section className={`${styles.container} ${styles.hero}`} aria-labelledby="hero-title">
          <div className={styles.eyebrow}><Sparkles size={14} aria-hidden="true" /> MỘT CÁCH KHÁC ĐỂ ĐỌC PDF</div>
          <h1 id="hero-title">Tài liệu của bạn.<br /><span>Câu trả lời rõ ràng.</span></h1>
          <p className={styles.heroDescription}>
            Biến những trang PDF thành cuộc trò chuyện.<br className={styles.desktopBreak} />
            Hỏi, tóm tắt và tìm lại nguồn — cùng trợ lý AI Baymax.
          </p>
          <div className={styles.heroActions}>
            <Link href="/chat" className={styles.primaryButton}>Dùng thử ngay <ArrowRight size={17} aria-hidden="true" /></Link>
            <a href="#minh-hoa" className={styles.secondaryButton}><MessageSquareText size={17} aria-hidden="true" /> Khám phá cách hoạt động</a>
          </div>
          <p className={styles.heroNote}><Check size={14} aria-hidden="true" /> Hỏi bằng tiếng Việt <span aria-hidden="true">·</span> Trích dẫn theo trang</p>
        </section>

        <section id="minh-hoa" className={`${styles.container} ${styles.previewSection}`} aria-label="Minh họa hỏi đáp PDF">
          <div className={styles.previewGlow} aria-hidden="true" />
          <ChatPreview />
          <p className={styles.previewCaption}>Một cuộc trò chuyện mẫu. Tài liệu và câu trả lời trong bản xem trước chỉ dùng để minh họa.</p>
        </section>

        <section className={`${styles.container} ${styles.technologySection}`} aria-labelledby="technology-title">
          <h2 id="technology-title">ĐƯỢC XÂY DỰNG VỚI CÁC CÔNG NGHỆ</h2>
          <TechnologyLogos />
        </section>

        <section id="tinh-nang" className={`${styles.container} ${styles.featuresSection}`} aria-labelledby="features-title">
          <div className={styles.sectionHeading}>
            <p className={styles.sectionLabel}>ÍT LỤC TÌM HƠN. NHIỀU ĐIỀU SÁNG TỎ HƠN.</p>
            <h2 id="features-title">Đọc tài liệu, theo cách của bạn.</h2>
            <p>Từ câu hỏi đầu tiên đến đoạn trích cần kiểm chứng.</p>
          </div>
          <div className={styles.featureGrid}>
            {FEATURES.map(({ icon: Icon, number, title, description, detail }) => (
              <article className={styles.featureCard} key={title}>
                <div className={styles.featureTop}><span className={styles.featureIcon}><Icon size={22} strokeWidth={1.6} aria-hidden="true" /></span><span className={styles.featureNumber}>{number}</span></div>
                <h3>{title}</h3>
                <p>{description}</p>
                <div className={styles.featureDetail}><Check size={14} aria-hidden="true" />{detail}</div>
              </article>
            ))}
          </div>
          <div className={styles.libraryNote}>
            <span className={styles.libraryIcon}><FileText size={20} aria-hidden="true" /></span>
            <p><strong>Một thư viện riêng cho tài liệu của bạn.</strong> Theo dõi trạng thái xử lý, tìm kiếm, thử lại hoặc xóa PDF ngay trong tài khoản.</p>
            <Link href="/documents" aria-label="Mở thư viện tài liệu"><MoveUpRight size={20} aria-hidden="true" /></Link>
          </div>
        </section>

        <section id="cach-hoat-dong" className={styles.stepsSection} aria-labelledby="steps-title">
          <div className={styles.container}>
            <div className={styles.sectionHeading}>
              <p className={styles.sectionLabel}>BẮT ĐẦU THẬT ĐƠN GIẢN</p>
              <h2 id="steps-title">Một PDF. Ba bước.</h2>
              <p>Từ tài liệu có sẵn đến thông tin bạn đang cần.</p>
            </div>
            <ol className={styles.steps}>
              {STEPS.map(({ icon: Icon, title, description }, index) => (
                <li key={title}>
                  <div className={styles.stepSymbol}><Icon size={23} strokeWidth={1.6} aria-hidden="true" /><span>{index + 1}</span></div>
                  <h3>{title}</h3>
                  <p>{description}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className={`${styles.container} ${styles.closingSection}`} aria-labelledby="closing-title">
          <div className={styles.closingCard}>
            <span className={styles.closingIcon}><Sparkles size={25} strokeWidth={1.5} aria-hidden="true" /></span>
            <h2 id="closing-title">Câu hỏi của bạn.<br />Điểm bắt đầu của mọi khám phá.</h2>
            <p>Thêm PDF đầu tiên và cùng Baymax tìm hiểu điều bạn quan tâm.</p>
            <Link href="/chat" className={styles.primaryButton}>Dùng thử ngay <ArrowRight size={17} aria-hidden="true" /></Link>
            <span className={styles.closingNote}>Đăng nhập để bắt đầu với tài liệu của bạn.</span>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={`${styles.container} ${styles.footerInner}`}>
          <div className={styles.brand}><BrandMark compact /></div>
          <p>Hỏi đáp PDF, có nguồn để kiểm chứng.</p>
          <nav aria-label="Liên kết cuối trang">
            <a href="#tinh-nang">Tính năng</a>
            <Link href="/auth/login">Đăng nhập</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}

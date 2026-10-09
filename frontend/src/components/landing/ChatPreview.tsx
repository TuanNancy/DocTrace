"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUp, Check, ChevronDown, FileText, Library, MessageSquareText, Pause, Play, Plus, RotateCcw, Sparkles, X } from "lucide-react";
import styles from "./Landing.module.css";

const EXAMPLES = [
  {
    label: "Tìm một ý cụ thể",
    question: "Làm thế nào để làm việc tập trung hơn?",
    answer: "Tài liệu gợi ý ba thói quen bạn có thể bắt đầu ngay:\n\n1. Chọn một việc ưu tiên cho mỗi phiên làm việc.\n2. Tắt thông báo để hạn chế sự gián đoạn.\n3. Dành một khoảng nghỉ ngắn giữa các phiên.",
    page: 4,
    quote: "Trước mỗi phiên làm việc, hãy chọn một nhiệm vụ ưu tiên và tắt các thông báo không cần thiết. Xen kẽ các phiên tập trung với những khoảng nghỉ ngắn.",
  },
  {
    label: "Tóm tắt tài liệu",
    question: "Tóm tắt những ý chính của tài liệu này.",
    answer: "Cẩm nang đề cập đến ba nội dung chính:\n\n1. Sắp xếp công việc theo mức độ ưu tiên.\n2. Tạo không gian và thói quen giúp tập trung.\n3. Duy trì nhịp làm việc có thời gian nghỉ ngơi.\n\nBạn có thể xem đoạn trích về thói quen tập trung bên dưới.",
    page: 4,
    quote: "Trước mỗi phiên làm việc, hãy chọn một nhiệm vụ ưu tiên và tắt các thông báo không cần thiết. Xen kẽ các phiên tập trung với những khoảng nghỉ ngắn.",
  },
];

/** Local, illustrative content: this preview never calls the chat API. */
export function ChatPreview() {
  const [exampleIndex, setExampleIndex] = useState(0);
  const [characters, setCharacters] = useState(0);
  const [paused, setPaused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [inView, setInView] = useState(false);
  const [pageVisible, setPageVisible] = useState(true);
  const [sourceOpen, setSourceOpen] = useState(false);
  const preview = useRef<HTMLDivElement>(null);
  const sourceButton = useRef<HTMLButtonElement>(null);
  const example = EXAMPLES[exampleIndex];
  const complete = characters >= example.answer.length;

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateMotion = () => setReducedMotion(media.matches);
    const updateVisibility = () => setPageVisible(!document.hidden);
    updateMotion();
    updateVisibility();
    media.addEventListener("change", updateMotion);
    document.addEventListener("visibilitychange", updateVisibility);
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { threshold: 0.15 });
    if (preview.current) observer.observe(preview.current);
    return () => {
      media.removeEventListener("change", updateMotion);
      document.removeEventListener("visibilitychange", updateVisibility);
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (reducedMotion) {
      setCharacters(example.answer.length);
      return;
    }
    if (paused || !inView || !pageVisible || complete) return;
    const timer = window.setInterval(() => {
      setCharacters((count) => Math.min(count + 3, example.answer.length));
    }, 35);
    return () => window.clearInterval(timer);
  }, [complete, example.answer, inView, pageVisible, paused, reducedMotion]);

  const selectExample = (index: number) => {
    setExampleIndex(index);
    setCharacters(reducedMotion ? EXAMPLES[index].answer.length : 0);
    setPaused(false);
    setSourceOpen(false);
  };

  const status = complete ? "Đã trả lời" : paused ? "Đã tạm dừng" : "Đang trả lời…";

  return (
    <div className={styles.previewFrame} ref={preview}>
      <div className={styles.previewToolbar}>
        <div className={styles.previewTitle}><span className={styles.windowDots} aria-hidden="true"><i /><i /><i /></span><span>Baymax <span className={styles.toolbarSlash}>/</span> Hỏi đáp tài liệu</span></div>
        <span className={styles.demoBadge}>Bản minh họa</span>
      </div>
      <div className={styles.previewBody}>
        <aside className={styles.previewSidebar} aria-label="Thư viện minh họa">
          <div className={styles.sidebarLabel}><Library size={15} aria-hidden="true" /> THƯ VIỆN CỦA BẠN</div>
          <div className={styles.selectedFile}>
            <span className={styles.fileIcon}><FileText size={19} aria-hidden="true" /></span>
            <div><strong>Cẩm nang làm việc.pdf</strong><span>12 trang · PDF mẫu</span></div>
          </div>
          <div className={styles.readyLabel}><Check size={12} aria-hidden="true" /> Sẵn sàng để hỏi đáp</div>
          <Link href="/documents" className={styles.addDocument}><Plus size={15} aria-hidden="true" /> Thêm tài liệu của bạn</Link>
          <div className={styles.sidebarTip}><QuoteMark /><p>Mỗi câu trả lời là một điểm bắt đầu. Nguồn trích dẫn giúp bạn hiểu sâu hơn.</p></div>
          <div className={styles.sidebarFooter}><span aria-hidden="true">B</span><div>Không gian của bạn<small>Tài liệu riêng theo tài khoản</small></div></div>
        </aside>
        <div className={styles.conversation}>
          <div className={styles.conversationHeader}>
            <div><FileText size={15} aria-hidden="true" /><span>Cẩm nang làm việc.pdf</span><ChevronDown size={13} aria-hidden="true" /></div>
            <span className={styles.documentTag}>PDF</span>
          </div>
          <div className={styles.messages}>
            <div className={styles.messageDate}>KHÁM PHÁ TÀI LIỆU CÙNG BAYMAX</div>
            <div className={styles.userMessage} key={example.question}>{example.question}</div>
            <div className={styles.assistantMessage}>
              <span className={styles.assistantAvatar}><Sparkles size={17} aria-hidden="true" /></span>
              <div className={styles.assistantContent}>
                <div className={styles.assistantName}>Baymax <span>Dựa trên tài liệu</span></div>
                <div className={styles.answer}>
                  <p aria-hidden="true">{example.answer.slice(0, characters)}{!complete && <span className={styles.typingCursor} data-paused={paused || !inView || !pageVisible} />}</p>
                  <p className="sr-only">{example.answer}</p>
                </div>
                <div className={styles.answerFooter}>
                  <button ref={sourceButton} type="button" className={styles.sourceChip} aria-label="Xem nguồn minh họa 1, trang 4" aria-expanded={sourceOpen} aria-controls="demo-source" onClick={() => setSourceOpen(!sourceOpen)}>
                    <span>1</span><FileText size={12} aria-hidden="true" /> Trang {example.page}
                  </button>
                  <div className={styles.streamControls}>
                    <span role="status" className={styles.streamStatus}>{status}</span>
                    {!reducedMotion && <button type="button" className={styles.replayButton} aria-label={complete ? "Phát lại minh họa" : paused ? "Tiếp tục minh họa" : "Tạm dừng minh họa"} onClick={() => complete ? selectExample(exampleIndex) : setPaused(!paused)}>
                      {complete ? <RotateCcw size={14} aria-hidden="true" /> : paused ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}
                    </button>}
                  </div>
                </div>
                <div id="demo-source" hidden={!sourceOpen} className={styles.sourceExcerpt}>
                  <div><strong>Đoạn trích mẫu · Trang {example.page}</strong><button type="button" aria-label="Đóng nguồn minh họa" onClick={() => { setSourceOpen(false); sourceButton.current?.focus(); }}><X size={14} aria-hidden="true" /></button></div>
                  <blockquote>“{example.quote}”</blockquote>
                </div>
              </div>
            </div>
          </div>
          <div className={styles.previewComposer}>
            <div className={styles.examplePrompts} aria-label="Chọn câu hỏi minh họa">
              {EXAMPLES.map((item, index) => <button type="button" key={item.label} aria-pressed={index === exampleIndex} onClick={() => selectExample(index)}><MessageSquareText size={12} aria-hidden="true" />{item.label}</button>)}
            </div>
            <Link href="/chat" className={styles.composerLink}><span>Đặt câu hỏi cho tài liệu của bạn…</span><span className={styles.sendIcon}><ArrowUp size={17} aria-hidden="true" /></span></Link>
            <p>Baymax có thể mắc lỗi. Hãy đối chiếu với nguồn trích dẫn.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function QuoteMark() {
  return <span className={styles.decorativeQuote} aria-hidden="true">“</span>;
}

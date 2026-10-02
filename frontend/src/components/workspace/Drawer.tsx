"use client";

import { Dialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { useEffect, useState } from "react";

export function Drawer({ open, onOpenChange, title, side = "right", children, below = 1280 }: {
  open: boolean; onOpenChange: (open: boolean) => void; title: string;
  side?: "left" | "right"; children: React.ReactNode; below?: number;
}) {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const media = window.matchMedia(`(max-width: ${below - 1}px)`);
    const update = () => setNarrow(media.matches);
    update(); media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [below]);
  return <Dialog.Root open={open && narrow} onOpenChange={onOpenChange}>
    <Dialog.Portal>
      <Dialog.Backdrop className="fixed inset-0 z-40 bg-slate-900/20 backdrop-blur-sm" />
      <Dialog.Popup className={`workspace fixed inset-y-0 z-50 flex w-[min(90vw,380px)] flex-col overflow-y-auto bg-[#f5f8fe] p-5 shadow-2xl ${side === "left" ? "left-0" : "right-0"}`}>
        <div className="mb-5 flex items-center justify-between">
          <Dialog.Title className="font-semibold text-slate-800">{title}</Dialog.Title>
          <Dialog.Close className="icon-button" aria-label="Đóng bảng"><X size={19} /></Dialog.Close>
        </div>
        {children}
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>;
}

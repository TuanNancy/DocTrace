import Image from "next/image";
import logo from "@/assets/baymax.png";

interface BrandMarkProps {
  compact?: boolean;
  variant?: "default" | "onDark";
}

export function BrandMark({
  compact = false,
  variant = "default",
}: BrandMarkProps) {
  const imageClass = compact
    ? "h-8 w-8 rounded-md object-contain"
    : "h-10 w-10 rounded-md object-contain";
  const textClass =
    variant === "onDark"
      ? compact
        ? "text-base font-semibold text-white"
        : "text-lg font-semibold text-white"
      : compact
        ? "text-base font-semibold text-slate-800 dark:text-slate-100"
        : "text-lg font-semibold text-slate-800 dark:text-slate-100";

  return (
    <div className="flex items-center gap-2">
      <Image src={logo} alt="Baymax logo" width={compact ? 32 : 40} height={compact ? 32 : 40} className={imageClass} />
      <span className={textClass}>Baymax</span>
    </div>
  );
}

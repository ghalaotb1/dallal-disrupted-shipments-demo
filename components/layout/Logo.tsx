import Image from "next/image";

export function LogoMark({ size = 30, className }: { size?: number; className?: string }) {
  return (
    <Image src="/dallal-logo.png" alt="" width={Math.round(size * (661 / 353))} height={size} className={className} aria-hidden />
  );
}

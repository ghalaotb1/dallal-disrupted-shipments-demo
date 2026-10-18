import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { ModelLab } from "@/components/models/ModelLab";
import { ModelsBoot } from "@/components/models/ModelsBoot";

export const metadata = { title: "Model evidence" };

export default function ModelsPage() {
  return (
    <div className="min-h-dvh bg-canvas">
      <ModelsBoot />
      <header className="flex h-14 items-center gap-3 border-b border-line bg-surface px-4">
        <Link href="/" className="flex items-center gap-1.5 text-13 font-medium text-ink-2 hover:text-ink">
          <ArrowLeft className="size-4" aria-hidden /> Back to operations
        </Link>
        <span className="text-sm font-semibold text-ink">Model evidence</span>
        <span className="text-xs text-ink-4">The trained risk models behind Dallal, with their real held-out metrics</span>
      </header>
      <ModelLab />
    </div>
  );
}

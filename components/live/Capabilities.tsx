"use client";

import { ShieldCheck } from "lucide-react";
import { Card, CardHeader } from "@/components/common/Card";
import { useLive } from "@/store/live";

/** What this deployment can and cannot do, as reported by the backend itself (not hard-coded in the UI). */
export function Capabilities() {
  const meta = useLive((s) => s.meta);
  if (!meta) return null;
  const rows: [string, string][] = [
    ["Environment", meta.env ?? "dev"],
    ["Operational actions", `${meta.execution?.mode ?? "simulated"} - ${meta.execution?.note ?? "recorded in the ledger, never executed on real systems"}`],
    ["WhatsApp", meta.whatsapp ? `${meta.whatsapp.mode}${meta.whatsapp.mode === "cloud" ? (meta.whatsapp.send_requires_supervisor_approval ? ", every message held for supervisor approval" : ", sends immediately") : " - nothing is ever sent to a phone"}` : meta.whatsapp_mode],
    ["Language model", meta.llm ? (meta.llm.available ? `${meta.llm.backend} available${meta.llm.interpreter_active ? `, reply suggestions by ${meta.llm.interpreter_model}` : ", reply suggestions off"}` : "none in this environment - replies are read by rules only; planning is the deterministic EVOI planner") : "unknown"],
    ["Trained models", meta.ml ? `${meta.ml.models.length} loaded. ${meta.ml.agent_scoring}` : "unknown"],
    ["Persistence", meta.persistence ? `${meta.persistence.db}${meta.persistence.backups ? `, backups on${meta.persistence.last_backup ? " (last: " + meta.persistence.last_backup.split("/").pop() + ")" : ""}` : ", backups off"}${meta.persistence.backup_error ? " - backup error " + meta.persistence.backup_error : ""}` : "unknown"],
    ["Learned responsiveness", meta.response_learning ? (Object.keys(meta.response_learning.learned).length ? Object.entries(meta.response_learning.learned).map(([k, v]) => `${k.replace("ask_", "")}: ${Math.round(v.p_response * 100)}% answer, ~${Math.round(v.median_latency_min)} min`).join(" · ") : "no inquiries closed yet - using the catalogue's assumed response rates as the prior") : "unknown"],
    ["Access", meta.auth ? `${meta.auth.api_key_required ? "API key required" : "open (dev)"}. ${meta.auth.roles}` : "unknown"],
  ];
  return (
    <Card>
      <CardHeader icon={<ShieldCheck />} title="This deployment" subtitle="Reported live by the backend" />
      <dl className="grid gap-x-6 gap-y-1.5 px-4 pb-4 text-xs sm:grid-cols-[140px_minmax(0,1fr)]">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-4">{k}</dt>
            <dd className="text-ink-2">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

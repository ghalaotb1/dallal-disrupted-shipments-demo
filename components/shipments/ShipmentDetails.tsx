"use client";

import { Check, MapPinHouse, Package, TriangleAlert, User, X } from "lucide-react";
import { corridors, places } from "@/data/network";
import { cn } from "@/lib/cn";
import { fmtSar } from "@/lib/format";
import { fmtWindow } from "@/lib/time";
import type { Shipment, ShipmentContext } from "@/types/domain";

export function ShipmentDetails({ s, ctx }: { s: Shipment; ctx: ShipmentContext }) {
  const conf = ctx.address.confidence;
  return (
    <section className="grid gap-px overflow-hidden rounded-xl border border-line bg-line-soft shadow-card md:grid-cols-3" aria-label="Shipment details">
      <div className="bg-surface p-4">
        <Title icon={<User />} title="Recipient" />
        <dl className="mt-2 space-y-1.5 text-xs">
          <Row k="Name" v={s.recipient.name} />
          <Row k="Phone" v={s.recipient.phone} mono />
          <Row k="Preferred channel" v={ctx.recipient.preferredChannel} />
          <Row k="Responsiveness" v={ctx.recipient.responsiveness} capitalize />
          <Row k="Confirmed window" v={ctx.recipient.confirmedWindow ? fmtWindow(ctx.recipient.confirmedWindow) : "—"} />
        </dl>
        <p className="mt-2 text-2xs text-ink-4">Personal data masked (PDPL-aware display).</p>
      </div>
      <div className="bg-surface p-4">
        <Title icon={<MapPinHouse />} title="Address" />
        <p className="mt-2 text-13 font-medium text-ink">{s.address.line}</p>
        <p className="text-xs text-ink-3">
          {s.address.district}, {s.address.city} · <span className="font-mono">{s.address.shortCode}</span>
        </p>
        <div className="mt-2.5 flex items-center gap-2">
          <span className="text-xs text-ink-3">Confidence</span>
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
            <span className={cn("block h-full rounded-full", conf >= 0.8 ? "bg-ok-500" : conf >= 0.5 ? "bg-warn-500" : "bg-crit-500")} style={{ width: `${Math.round(conf * 100)}%` }} />
          </span>
          <span className={cn("text-xs font-semibold tabular", conf >= 0.8 ? "text-ok-700" : conf >= 0.5 ? "text-warn-700" : "text-crit-700")}>{conf.toFixed(2)}</span>
        </div>
        {ctx.address.checks.length ? (
          <ul className="mt-2 space-y-1">
            {ctx.address.checks.map((c) => (
              <li key={c.label} className="flex items-start gap-1.5 text-xs">
                {c.result === "pass" ? <Check className="mt-0.5 size-3.5 shrink-0 text-ok-600" aria-label="pass" /> : c.result === "warn" ? <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warn-600" aria-label="warning" /> : <X className="mt-0.5 size-3.5 shrink-0 text-crit-600" aria-label="fail" />}
                <span>
                  <span className="text-ink-2">{c.label}</span> <span className="text-ink-4">— {c.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <div className="bg-surface p-4">
        <Title icon={<Package />} title="Order & route" />
        <dl className="mt-2 space-y-1.5 text-xs">
          <Row k="Merchant" v={`${s.merchant} · ${s.orderRef}`} />
          <Row k="Contents" v={s.contents} />
          <Row k="Payment" v={s.payment.type === "COD" ? `COD ${fmtSar(s.payment.amountSar)}` : "Prepaid"} />
          <Row k="Origin" v={places[s.originId].name} />
          <Row k="Corridor" v={`${corridors[s.corridorId].code} · ${corridors[s.corridorId].name}`} />
          <Row k="Courier" v={s.courier ? `${s.courier.id} · ${s.courier.name} · ${s.courier.vehicle}` : "Not assigned"} />
        </dl>
      </div>
    </section>
  );
}

function Title({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <h3 className="flex items-center gap-1.5 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase [&_svg]:size-3.5">
      {icon}
      {title}
    </h3>
  );
}

function Row({ k, v, mono, capitalize }: { k: string; v: string; mono?: boolean; capitalize?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-ink-4">{k}</dt>
      <dd className={cn("text-right text-ink-2", mono && "font-mono", capitalize && "capitalize")}>{v}</dd>
    </div>
  );
}

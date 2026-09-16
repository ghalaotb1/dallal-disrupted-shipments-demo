import { corridors, places } from "@/data/network";
import { getWorld } from "@/store/world";
import type { SearchHit, ShipmentService } from "@/services/contracts";

export const demoShipmentService: ShipmentService = {
  async list(opts) {
    return Object.values(getWorld().shipments).filter((s) => opts?.includeClosed || !s.closed);
  },
  async get(id) {
    return getWorld().shipments[id.toUpperCase()];
  },
  async getJourney(id) {
    return getWorld().journeys[id] ?? [];
  },
  search(text) {
    const q = text.trim().toLowerCase();
    if (!q) return [];
    const w = getWorld();
    const digits = q.replace(/[^0-9]/g, "");
    const hits: SearchHit[] = [];
    for (const s of Object.values(w.shipments)) {
      const hay = `${s.id} ${s.orderRef} ${s.destination.label} ${s.merchant} ${s.corridorId}`.toLowerCase();
      if (hay.includes(q) || (digits.length >= 3 && s.id.includes(digits))) {
        hits.push({ type: "shipment", id: s.id, title: s.id, subtitle: `${s.destination.label} · ${s.merchant}`, href: `/shipments/${s.id}` });
      }
    }
    for (const i of Object.values(w.incidents)) {
      if (`${i.id} ${i.title} ${i.subtitle}`.toLowerCase().includes(q)) {
        hits.push({ type: "incident", id: i.id, title: `${i.id} · ${i.title}`, subtitle: i.subtitle, href: `/incidents/${i.id}` });
      }
    }
    for (const p of Object.values(places)) {
      if (`${p.name} ${p.district} ${p.city}`.toLowerCase().includes(q)) {
        hits.push({ type: "place", id: p.id, title: p.name, subtitle: `${p.district}, ${p.city}` });
      }
    }
    for (const c of Object.values(corridors)) {
      if (`${c.code} ${c.name}`.toLowerCase().includes(q)) {
        hits.push({ type: "place", id: c.id, title: `${c.code} · ${c.name}`, subtitle: c.description });
      }
    }
    return hits.slice(0, 12);
  },
};

import { Marker, type Map as MLMap, type PositionAnchor } from "maplibre-gl";

/** Imperative DOM markers keyed by id: created once, moved and restyled in place, removed when no longer wanted. */
export class MarkerLayer {
  private items = new Map<string, { marker: Marker; node: HTMLElement }>();
  private seen = new Set<string>();

  constructor(private map: MLMap) {}

  begin() {
    this.seen = new Set();
  }

  upsert(key: string, lngLat: [number, number], build: () => HTMLElement, update: (node: HTMLElement) => void, z: number, anchor: PositionAnchor = "center", offset?: [number, number]) {
    this.seen.add(key);
    let cur = this.items.get(key);
    if (!cur) {
      const node = build();
      cur = { marker: new Marker({ element: node, anchor, offset }).setLngLat(lngLat).addTo(this.map), node };
      this.items.set(key, cur);
    } else {
      cur.marker.setLngLat(lngLat);
    }
    cur.node.style.zIndex = String(z);
    update(cur.node);
  }

  end() {
    for (const [k, v] of this.items) {
      if (!this.seen.has(k)) {
        v.marker.remove();
        this.items.delete(k);
      }
    }
  }

  clear() {
    this.items.forEach((v) => v.marker.remove());
    this.items.clear();
  }
}

export function el(html: string, cls: string): HTMLElement {
  const e = document.createElement("div");
  e.className = cls;
  e.innerHTML = html;
  return e;
}

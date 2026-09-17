import type { Metadata } from "next";
import { ShipmentIntelligence } from "@/components/shipments/ShipmentIntelligence";

export async function generateMetadata({ params }: PageProps<"/shipments/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: `${decodeURIComponent(id).toUpperCase()} · Shipment Intelligence` };
}

export default async function ShipmentPage({ params }: PageProps<"/shipments/[id]">) {
  const { id } = await params;
  return <ShipmentIntelligence id={decodeURIComponent(id).toUpperCase()} />;
}

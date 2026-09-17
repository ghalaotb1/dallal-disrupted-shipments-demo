import type { Metadata } from "next";
import { IncidentIntelligence } from "@/components/incidents/IncidentIntelligence";

export async function generateMetadata({ params }: PageProps<"/incidents/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: `${decodeURIComponent(id).toUpperCase()} · Incident Intelligence` };
}

export default async function IncidentPage({ params }: PageProps<"/incidents/[id]">) {
  const { id } = await params;
  return <IncidentIntelligence id={decodeURIComponent(id).toUpperCase()} />;
}

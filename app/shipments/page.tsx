import { Suspense } from "react";
import { ShipmentsScreen } from "@/components/shipments/ShipmentsScreen";

export const metadata = { title: "Shipments" };

export default function ShipmentsPage() {
  return (
    <Suspense fallback={<div className="skeleton m-4 h-96 rounded-xl" />}>
      <ShipmentsScreen />
    </Suspense>
  );
}

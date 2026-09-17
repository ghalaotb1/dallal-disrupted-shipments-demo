"use client";

import dynamic from "next/dynamic";

/** MapLibre touches `window`; load the map on the client only. */
export const LazyNetworkMap = dynamic(() => import("@/components/map/NetworkMap"), {
  ssr: false,
  loading: () => <div className="size-full skeleton" aria-label="Loading map" />,
});

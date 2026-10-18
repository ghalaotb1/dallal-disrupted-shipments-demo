"use client";

import dynamic from "next/dynamic";

/** MapLibre touches `window`; load it on the client only. */
export const LazyOpsMap = dynamic(() => import("@/components/ops/OpsMap"), { ssr: false, loading: () => <div className="skeleton size-full" aria-label="Loading map" /> });

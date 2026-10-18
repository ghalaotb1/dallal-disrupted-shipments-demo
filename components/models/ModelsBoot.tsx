"use client";

import { useEffect } from "react";
import { connectBackend } from "@/lib/ops/agent";

/** The evidence page talks to the backend directly; make sure its connection state is known. */
export function ModelsBoot() {
  useEffect(() => {
    void connectBackend();
  }, []);
  return null;
}

import { DK04_BLOCKAGE, getRoute } from "@/data/network";
import { projectOnPath } from "@/lib/geo";
import { distanceAt } from "@/services/logic/movement";
import type { DemoTime, Shipment } from "@/types/domain";

/**
 * Incident detection (blueprint §6): count disruptions per corridor in a rolling
 * window and compare with that corridor's baseline. Flag when the count exceeds
 * the baseline mean by `threshold` standard deviations. Simple, explainable,
 * genuinely statistical — here running over the simulated event stream.
 */

export const DETECTOR = { windowMin: 30, threshold: 3, minCount: 3, stdFloor: 0.35 };

export interface CorridorEvaluation {
  corridorId: string;
  observed: number;
  mean: number;
  std: number;
  z: number;
  triggered: boolean;
  members: string[];
}

export function baselineStats(series: number[]) {
  const mean = series.reduce((a, b) => a + b, 0) / series.length;
  const variance = series.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, series.length - 1);
  return { mean, std: Math.sqrt(variance) };
}

export function evaluateCorridor(corridorId: string, shipments: Shipment[], now: DemoTime, baseline: number[]): CorridorEvaluation {
  const since = now - DETECTOR.windowMin * 60_000;
  const members = shipments
    .filter((s) => s.corridorId === corridorId && !s.closed && s.health === "disrupted" && (s.exception?.recordedAt ?? 0) >= since)
    .map((s) => s.id);
  const { mean, std } = baselineStats(baseline);
  const observed = members.length;
  const z = (observed - mean) / Math.max(std, DETECTOR.stdFloor);
  return {
    corridorId,
    observed,
    mean,
    std,
    z,
    triggered: observed >= DETECTOR.minCount && z >= DETECTOR.threshold,
    members,
  };
}

/** Shipments not yet failing whose remaining path crosses the incident zone. */
export function findExposed(shipments: Shipment[], corridorId: string, affected: string[], now: DemoTime) {
  return shipments
    .filter((s) => s.corridorId === corridorId && !s.closed && !affected.includes(s.id))
    .filter((s) => {
      const route = getRoute(s.routeKey);
      if (!route) return false;
      const hit = projectOnPath(route, DK04_BLOCKAGE.coord);
      if (hit.gap > 200) return false;
      const travelled = s.movement.mode === "facility" ? 0 : distanceAt(s.movement, route.lengthM, now);
      return travelled < hit.d;
    })
    .map((s) => s.id);
}

"""Deterministic operational signals computed from a Bundle. Pure functions: no LLM, no randomness, no hidden state.

These are the 'facts' the agent reasons over. Thresholds are named constants so they can be reviewed and later tuned from
real SPL data; they are operational definitions, not learned parameters.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from dallal.tools.bundle import Bundle

STALL_HOURS = 4.0  # no scan for this long on an open parcel counts as stalled
STATIONARY_RADIUS_M = 80.0
STATIONARY_MIN_FLAG = 15.0
GEO_MISMATCH_M = 300.0  # a failed attempt logged this far from the address was not made at the address
SLOW_RATIO = 0.6
BLOCKED_RATIO = 0.5
INCIDENT_WINDOW_MIN = 30
INCIDENT_MIN_COUNT = 3
INCIDENT_Z = 3.0
STD_FLOOR = 0.35
BACKLOG_MIN_PARCELS = 40
BACKLOG_RATIO = 2.5

SCAN_TYPES = {"created", "scan", "arrived_facility", "departed_facility", "out_for_delivery", "failed_attempt", "delivered",
              "handoff_to_carrier", "accepted", "rescheduled", "redirected", "returned", "exception_recorded"}
POST_DELIVERY = {"out_for_delivery", "arrived_facility", "departed_facility", "failed_attempt", "delivered"}


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _attrs(sh: dict[str, Any]) -> dict[str, Any]:
    a = sh.get("attrs")
    return a if isinstance(a, dict) else {}


def shipment_facts(b: Bundle, sid: str) -> dict[str, Any]:
    sh = b.shipment(sid)
    a = _attrs(sh)
    exc = b.exception(sid)
    ev = b.events(sid)
    alt = a.get("alt_pickup_point_id")
    alt_state = b.row("node_state", "node_id", alt) if alt else None
    n_failed = int((ev["event_type"] == "failed_attempt").sum()) if not ev.empty else 0
    return {
        "shipment_id": sid, "service_level": sh.get("service_level"), "payment_type": sh.get("payment_type"),
        "cod_amount": _f(sh.get("cod_amount")), "value": _f(sh.get("value")), "origin_node_id": sh.get("origin_node_id"),
        "courier_id": sh.get("courier_id"), "dest_lat": _f(sh.get("dest_lat")), "dest_lng": _f(sh.get("dest_lng")),
        "promised_end_ts": sh.get("promised_end_ts"), "corridor_id": a.get("corridor_id"), "pickup_point_id": a.get("pickup_point_id"),
        "alt_pickup_online": bool(alt_state and alt_state.get("status") == "online"),
        "alt_route_available": bool(a.get("alt_route_available", False)), "spare_courier_available": bool(a.get("spare_courier_available", False)),
        "recorded_code": None if exc is None else exc["code"], "recorded_label": None if exc is None else exc.get("label"),
        "recorded_ts": None if exc is None else exc.get("recorded_ts"), "failed_attempts": n_failed,
        "delivered": bool((ev["event_type"] == "delivered").any()) if not ev.empty else False,
        "origin": sh.get("origin"), "scenario_id": sh.get("scenario_id"),
    }


def _f(v: Any) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def journey_signals(b: Bundle, sid: str) -> dict[str, Any]:
    ev = b.events(sid)
    ev = ev[ev["event_type"] != "gps_ping"] if not ev.empty else ev
    out: dict[str, Any] = {"n_events": len(ev), "failed_attempts": 0, "sequence_conflict": False, "stalled": False,
                           "hours_since_scan": None, "conflict_detail": None, "failed_events": []}
    if ev.empty:
        return out
    ev = ev.sort_values("ts")
    scans = ev[ev["event_type"].isin(SCAN_TYPES)]
    last = scans["ts"].max()
    out["hours_since_scan"] = float((b.as_of - last).total_seconds() / 3600)
    fails = ev[ev["event_type"] == "failed_attempt"]
    out["failed_attempts"] = len(fails)
    out["failed_events"] = [{"ts": r["ts"], "raw_code": r.get("raw_code")} for _, r in fails.iterrows()]
    delivered = ev[ev["event_type"] == "delivered"]
    if not delivered.empty:
        t0 = delivered["ts"].min()
        later = ev[(ev["ts"] > t0) & ev["event_type"].isin(POST_DELIVERY)]
        if not later.empty or len(delivered) > 1:
            out["sequence_conflict"] = True
            first = later.iloc[0] if not later.empty else delivered.iloc[1]
            out["conflict_detail"] = f"'{first['event_type']}' recorded after 'delivered' at {t0:%H:%M}"
    out["delivered"] = not delivered.empty
    out["stalled"] = (not out["sequence_conflict"]) and (not out["delivered"]) and out["hours_since_scan"] > STALL_HOURS
    return out


def address_signals(b: Bundle, sid: str) -> dict[str, Any]:
    r = b.row("address_context", "shipment_id", sid)
    if r is None:
        return {"available": False, "weak": False}
    conf = _f(r.get("confidence"))
    past = r.get("past_failures_at_address")
    past = 0 if past is None or (isinstance(past, float) and math.isnan(past)) else int(past)
    first = bool(r.get("first_delivery_to_address")) if r.get("first_delivery_to_address") is not None else False
    weak = (conf is not None and conf < 0.6) or past >= 2 or (first and conf is not None and conf < 0.75)
    return {"available": True, "weak": weak, "confidence": conf, "past_failures": past, "first_delivery": first,
            "geocode_quality": r.get("geocode_quality")}


def recipient_signals(b: Bundle, sid: str) -> dict[str, Any]:
    r = b.row("recipient_context", "shipment_id", sid)
    if r is None:
        return {"available": False, "missed": False, "window_conflict": False}
    missed_n = r.get("missed_windows")
    missed_n = 0 if missed_n is None or (isinstance(missed_n, float) and math.isnan(missed_n)) else int(missed_n)
    resp = r.get("responsiveness")
    missed = missed_n >= 2 or (missed_n >= 1 and resp == "low")
    ws, we = r.get("confirmed_window_start_ts"), r.get("confirmed_window_end_ts")
    conflict = False
    detail = None
    if pd.notna(ws) and pd.notna(we):
        ev = b.events(sid)
        fails = ev[ev["event_type"] == "failed_attempt"] if not ev.empty else ev
        for _, f in fails.iterrows():
            if ws <= f["ts"] <= we and str(f.get("raw_code") or "").upper().startswith("RECIPIENT"):
                conflict = True
                detail = f"recipient confirmed {ws:%H:%M}-{we:%H:%M}; 'not available' recorded {f['ts']:%H:%M}"
    return {"available": True, "missed": missed, "missed_windows": missed_n, "responsiveness": resp,
            "channel": r.get("preferred_channel"), "window_conflict": conflict, "conflict_detail": detail,
            "confirmed_window": None if not (pd.notna(ws) and pd.notna(we)) else (ws, we)}


def route_signals(b: Bundle, sid: str, facts: dict[str, Any]) -> dict[str, Any]:
    ev = b.events(sid)
    out: dict[str, Any] = {"stationary_min": 0.0, "corridor_ratio": None, "geo_mismatch": False, "mismatch_m": None,
                           "corridor_speed": None, "corridor_typical": None, "has_telemetry": False}
    if not ev.empty:
        pings = ev[(ev["event_type"] == "gps_ping") & ev["lat"].notna()].sort_values("ts")
        if not pings.empty:
            out["has_telemetry"] = True
            last = pings.iloc[-1]
            t_start = last["ts"]
            for _, p in pings.iloc[::-1].iterrows():
                if haversine_m(last["lat"], last["lng"], p["lat"], p["lng"]) <= STATIONARY_RADIUS_M:
                    t_start = p["ts"]
                else:
                    break
            out["stationary_min"] = float((b.as_of - t_start).total_seconds() / 60) if (b.as_of - last["ts"]).total_seconds() < 900 else 0.0
        fails = ev[(ev["event_type"] == "failed_attempt") & ev["lat"].notna()]
        if not fails.empty and facts.get("dest_lat") is not None:
            d = max(haversine_m(r["lat"], r["lng"], facts["dest_lat"], facts["dest_lng"]) for _, r in fails.iterrows())
            out["mismatch_m"] = float(d)
            out["geo_mismatch"] = d > GEO_MISMATCH_M
    cid = facts.get("corridor_id")
    if cid:
        cs = b.row("corridor_state", "corridor_id", cid)
        if cs and _f(cs.get("speed_kmh")) is not None and _f(cs.get("typical_speed_kmh")):
            out["corridor_speed"], out["corridor_typical"] = _f(cs["speed_kmh"]), _f(cs["typical_speed_kmh"])
            out["corridor_ratio"] = out["corridor_speed"] / out["corridor_typical"]
    return out


def facility_signals(b: Bundle, facts: dict[str, Any]) -> dict[str, Any]:
    nid = facts.get("origin_node_id")
    st = b.row("node_state", "node_id", nid) if nid else None
    if not st:
        return {"available": False, "backlog": False, "scan_gap": False}
    backlog = st.get("backlog_parcels")
    base = _f(st.get("baseline_backlog")) or 0.0
    backlog = 0 if backlog is None or (isinstance(backlog, float) and math.isnan(backlog)) else int(backlog)
    is_backlog = backlog >= BACKLOG_MIN_PARCELS and backlog >= BACKLOG_RATIO * max(base, 1.0)
    last = st.get("last_scan_ts")
    gap_h = float((b.as_of - last).total_seconds() / 3600) if pd.notna(last) else None
    return {"available": True, "backlog": is_backlog, "backlog_parcels": backlog, "baseline": base,
            "scan_gap": gap_h is not None and gap_h > STALL_HOURS, "gap_hours": gap_h, "node_id": nid, "status": st.get("status")}


def pickup_signals(b: Bundle, facts: dict[str, Any]) -> dict[str, Any]:
    pid = facts.get("pickup_point_id")
    st = b.row("node_state", "node_id", pid) if pid else None
    return {"available": bool(st), "offline": bool(st and st.get("status") == "offline"), "node_id": pid,
            "status": None if not st else st.get("status")}


def incident_signals(b: Bundle, sid: str, facts: dict[str, Any]) -> dict[str, Any]:
    """Rolling-window count of failing shipments per scope (corridor or origin facility) vs the scope's baseline."""
    sh = b.shipments()
    since = b.as_of - pd.Timedelta(minutes=INCIDENT_WINDOW_MIN)
    ev = b.all_events()
    failing: set[str] = set()
    if not ev.empty:
        f = ev[(ev["event_type"].isin(["failed_attempt", "exception_recorded"])) & (ev["ts"] > since)]
        failing |= set(f["shipment_id"])
    exc = b.exceptions()
    if not exc.empty:
        failing |= set(exc[exc["recorded_ts"] > since]["shipment_id"])
    # stalled parcels at the same facility also count as failing symptoms
    best: dict[str, Any] | None = None
    for scope, key, scope_id in (("corridor", "corridor_id", facts.get("corridor_id")), ("facility", "origin_node_id", facts.get("origin_node_id"))):
        if not scope_id:
            continue
        members_all = []
        for _, r in sh.iterrows():
            a = _attrs(r.to_dict())
            val = a.get("corridor_id") if key == "corridor_id" else r.get("origin_node_id")
            if val == scope_id:
                members_all.append(r["shipment_id"])
        members = [m for m in members_all if m in failing]
        if scope == "facility":
            for m in members_all:
                if m not in members:
                    js = journey_signals(b, m)
                    if js["stalled"]:
                        members.append(m)
        # Default exception-count baseline per 30-min window when no history is supplied (ASSUMPTION; real baselines come
        # from corridor_state.baseline_exceptions_* computed over the previous weeks).
        mean, std = (0.4, 0.6) if scope == "corridor" else (0.3, 0.5)
        if scope == "corridor":
            cs = b.row("corridor_state", "corridor_id", scope_id)
            if cs and _f(cs.get("baseline_exceptions_mean")) is not None:
                mean, std = _f(cs["baseline_exceptions_mean"]), _f(cs.get("baseline_exceptions_std")) or 0.6
        z = (len(members) - mean) / max(std, STD_FLOOR)
        cand = {"scope": scope, "scope_id": scope_id, "observed": len(members), "population": len(members_all), "baseline_mean": mean,
                "baseline_std": std, "z": float(z), "concentration": len(members) / max(1, len(members_all)),
                "members": sorted(members), "includes_subject": sid in members,
                "exposed": sorted(m for m in members_all if m not in members and not _delivered(b, m))}
        cand["triggered"] = cand["observed"] >= INCIDENT_MIN_COUNT and cand["z"] >= INCIDENT_Z and cand["includes_subject"]
        # Scope attribution: among scopes that trip the detector prefer the one where failures are most CONCENTRATED (a corridor
        # blockage fails most of the corridor; a hub that merely originates the same parcels fails a small share of its volume).
        key = (cand["triggered"], cand["concentration"], cand["z"])
        if best is None or key > (best["triggered"], best["concentration"], best["z"]):
            best = cand
    if best is None:
        return {"scope": None, "observed": 0, "z": 0.0, "members": [], "exposed": [], "includes_subject": False,
                "triggered": False, "subthreshold": False}
    best["subthreshold"] = (not best["triggered"]) and (best["observed"] >= 2 or best["z"] >= 1.5)
    return best


def _delivered(b: Bundle, sid: str) -> bool:
    ev = b.events(sid)
    return (not ev.empty) and bool((ev["event_type"] == "delivered").any())

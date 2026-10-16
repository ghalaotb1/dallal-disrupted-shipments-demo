"""Frontend case snapshot -> canonical Bundle.

The Next.js app owns the simulated physical world (vehicles, roads, shipment state). To reason about a shipment the backend receives a
compact snapshot and expresses it in the canonical tables, tagged origin='demo' (it is NOT SPL data). Recipient contact details are never
taken from the snapshot: the backend substitutes a non-routable `SANDBOX-<shipment>` handle, so a demo case can never address a real phone.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from dallal.data.augment.scenarios import World
from dallal.tools.bundle import Bundle

CODE_MAP = {"RNA": "RECIPIENT_NOT_AVAILABLE", "ADR": "ADDRESS_INCORRECT", "DLY": "TRAFFIC_DELAY", "NSC": "NO_SCAN", "LKR": "PICKUP_POINT_CLOSED", "RSC": "ROUTE_BLOCKED"}
RIYADH = pd.Timedelta(hours=3)


def _ts(ms: float) -> pd.Timestamp:
    """Epoch milliseconds -> naive Riyadh wall-clock (the backend's operating timezone; used for quiet-hours rules)."""
    return pd.Timestamp(int(ms), unit="ms") + RIYADH


class DemoWorld(World):
    def prov(self, key: str) -> dict[str, Any]:
        return {"origin": "demo", "source_id": "dallal-demo-frontend", "source_record_id": key, "adapter_version": "frontend-case-1.0", "scenario_id": self.scenario, "generator_seed": None}


def _event_type(title: str, code: str | None, tone: str) -> str:
    t = title.lower()
    if t.startswith("order created"):
        return "created"
    if t.startswith("received at") or "arrived" in t:
        return "arrived_facility"
    if "out for delivery" in t:
        return "out_for_delivery"
    if "delivered" in t and "failed" not in t:
        return "delivered"
    if "failed" in t and ("attempt" in t or code):
        return "failed_attempt"
    if code and tone in ("crit", "warn"):
        return "exception_recorded"
    return "scan"


def bundle_from_frontend(case: dict[str, Any]) -> Bundle:
    now = _ts(case["now"])
    sh, ctx = case["shipment"], case["context"]
    sid = sh["id"]
    w = DemoWorld(f"frontend-case:{sid}", 0, now=now)
    mins = lambda ms: max(0.0, (case["now"] - ms) / 60_000.0)  # noqa: E731

    origin = sh["originId"]
    w.node(origin, "hub", sh.get("originName", origin), sh["originLat"], sh["originLng"]) if "originLat" in sh else w.node(origin, "hub", sh.get("originName", origin), 26.4, 50.1)
    fac = ctx.get("facility")
    if fac:
        w.node_state(fac["placeId"], backlog=int(fac.get("backlogParcels") or 0), baseline=float(case.get("facilityBaseline", 30)), last_scan_min=mins(fac["lastScanAt"]))
    if not fac or fac["placeId"] != origin:
        w.node_state(origin, backlog=int(case.get("facilityBaseline", 30)), baseline=float(case.get("facilityBaseline", 30)), last_scan_min=10.0)
    pp = ctx.get("pickupPoint")
    if pp:
        w.node(pp["placeId"], "pickup", pp["placeId"], 26.3, 50.2)
        w.node_state(pp["placeId"], backlog=0, baseline=0, last_scan_min=15.0, status=pp.get("status", "online"))
    corridor = sh["corridorId"]
    tel = ctx.get("telemetry", {})
    base = case.get("corridorBaseline", {"mean": 0.4, "std": 0.6})
    w.corridor(corridor, tel.get("corridorSpeedKmh") if tel.get("corridorSpeedKmh") is not None else 55.0, tel.get("corridorTypicalKmh") or 60.0, base["mean"], base["std"])

    pay = sh.get("payment", {})
    cod = pay.get("amountSar") if pay.get("type") == "COD" else None
    lat, lng = sh["destLat"], sh["destLng"]
    w.add("shipment", sid, shipment_id=sid, origin_node_id=origin, courier_id=(sh.get("courier") or {}).get("id"), service_level=sh["service"], created_ts=_ts(sh["createdAt"]),
          promised_end_ts=_ts(sh["window"]["end"]), dest_lat=lat, dest_lng=lng, payment_type="COD" if cod else "Prepaid", cod_amount=cod, value=sh["valueSar"],
          attrs={"corridor_id": corridor, "pickup_point_id": pp["placeId"] if pp else None, "alt_route_available": bool(sh.get("altRoute")), "spare_courier_available": True,
                 "recipient_phone": f"SANDBOX-{sid}", "recipient_opt_in": True, "recipient_name": (sh.get("recipientName") or "").split(" ")[0] or None,
                 "window_text": f"{_ts(sh['window']['start']):%H:%M}-{_ts(sh['window']['end']):%H:%M}", "merchant": sh.get("merchant", "Dallal")})
    for e in case.get("journey", []):
        if e["at"] > case["now"]:
            continue
        et = _event_type(e["title"], e.get("code"), e.get("tone", "neutral"))
        code = CODE_MAP.get(e.get("code") or "", e.get("code"))
        at_vehicle = None
        w.event(sid, et, mins(e["at"]), code=code, at=at_vehicle)
    veh = case.get("vehicle")
    if veh:
        since = veh.get("stationarySince")
        span = min(60.0, mins(since)) if since else 0.0
        for k in range(int(span // 5), -1, -1):
            w.event(sid, "gps_ping", k * 5.0, at=(veh["lat"], veh["lng"]))
        if not since:
            w.event(sid, "gps_ping", 0.0, at=(veh["lat"], veh["lng"]))
    exc = sh.get("exception")
    if exc:
        code = CODE_MAP.get(exc["code"], exc["code"])
        w.exception(sid, code, mins(exc["recordedAt"]), exc.get("label"))
    a = ctx["address"]
    w.address(sid, conf=a["confidence"], past=a.get("pastFailuresAtAddress", 0), first=a.get("firstDeliveryToAddress", False))
    r = ctx["recipient"]
    cw = r.get("confirmedWindow")
    w.recipient(sid, resp=r["responsiveness"], channel=r["preferredChannel"], missed=len(r.get("missedWindows", [])), confirmed=(mins(cw["start"]), mins(cw["end"])) if cw else None)

    for p in case.get("peers", []):
        pid = p["id"]
        w.add("shipment", pid, shipment_id=pid, origin_node_id=p.get("originId", origin), service_level="Standard", promised_end_ts=now + pd.Timedelta(hours=2), dest_lat=lat, dest_lng=lng,
              attrs={"corridor_id": p["corridorId"], "alt_route_available": True, "spare_courier_available": True})
        if p.get("exceptionAt"):
            w.event(pid, "exception_recorded", mins(p["exceptionAt"]), code=CODE_MAP.get(p.get("code") or "", p.get("code")))
            w.exception(pid, CODE_MAP.get(p.get("code") or "", p.get("code") or "TRAFFIC_DELAY"), mins(p["exceptionAt"]))
        if p.get("delivered"):
            w.event(pid, "delivered", 5.0)
        w.event(pid, "out_for_delivery", 90.0)
    trig = case.get("trigger") or {"kind": "analyst_request"}
    return w.build(sid, trig, {})

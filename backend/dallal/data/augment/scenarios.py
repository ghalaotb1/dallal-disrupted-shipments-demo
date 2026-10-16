"""Synthetic operational scenarios (augmentation). Everything emitted here is origin=SYNTHETIC with a scenario_id + seed.

WHY these scenarios (each is a gap the audit found in the real data — docs/data/DATASET_DECISION_REPORT.md §3):
  recipient_unavailable, wrong/incomplete address, repeated failed attempt  -> no public data states failure reasons
  route blockage, branch backlog, pickup/locker unavailable, stalled/no scan -> no public data labels operational root causes
  conflicting custody/delivery evidence, unknown anomaly                    -> no public data contains contradictory evidence
  multi-shipment incident                                                   -> no public data labels systemic incidents

WHAT this data is for: exercising and regression-testing the agent and tools in situations real data cannot show. It is NOT used
to train or evaluate any risk model, never enters a held-out evaluation split (splits.time_split rejects non-observed origins),
and any accuracy measured on it describes the agent's logic, not real-world performance.

Calibration status: timings are jittered, not fitted; background exception rates are assumptions (documented in each builder).
The only real-data calibration planned is for incident-baseline noise (LaDe/Amazon), see docs/data/AUGMENTATION.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from dallal.data.schema import TABLES
from dallal.tools.bundle import Bundle

VERSION = "scenarios-1.0"
NOW = pd.Timestamp("2026-03-10 14:00:00")  # fictional decision time
HUB = "dallal-demo:hub:dammam-1"
HUB2 = "dallal-demo:hub:khobar-1"
PP = "dallal-demo:pickup:khobar-3"
ADDR = (26.3100, 50.2000)


def _m(lat: float, lng: float, north_m: float, east_m: float) -> tuple[float, float]:
    return lat + north_m / 110_540.0, lng + east_m / (111_320.0 * np.cos(np.deg2rad(lat)))


@dataclass
class World:
    scenario: str
    seed: int
    rng: np.random.Generator = field(init=False)
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {t: [] for t in TABLES})
    n_ship: int = 0

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)

    @property
    def sid_prefix(self) -> str:
        return f"DL-{self.scenario[:3].upper()}"

    def prov(self, key: str) -> dict[str, Any]:
        return {"origin": "synthetic", "source_id": "dallal-augment", "source_record_id": key, "adapter_version": VERSION,
                "scenario_id": f"{self.scenario}-seed{self.seed}", "generator_seed": self.seed}

    def add(self, table: str, key: str, **kw: Any) -> None:
        self.rows[table].append({**kw, **self.prov(key)})

    # ── primitives ──
    def minutes_ago(self, m: float) -> pd.Timestamp:
        return NOW - pd.Timedelta(minutes=float(m))

    def node(self, node_id: str, kind: str, name: str, lat: float, lng: float) -> None:
        self.add("node", node_id, node_id=node_id, kind=kind, name=name, city="Dammam/Khobar", lat=lat, lng=lng)

    def _replace(self, table: str, key_col: str, key: str) -> None:
        self.rows[table] = [r for r in self.rows[table] if r[key_col] != key]

    def node_state(self, node_id: str, *, backlog: int = 25, baseline: float = 28, last_scan_min: float = 10, status: str = "online") -> None:
        self._replace("node_state", "node_state_id", f"ns:{node_id}")  # scenario overrides replace the default state
        self.add("node_state", f"ns:{node_id}", node_state_id=f"ns:{node_id}", node_id=node_id, ts=NOW - pd.Timedelta(minutes=1), backlog_parcels=backlog,
                 last_scan_ts=self.minutes_ago(last_scan_min), status=status, baseline_backlog=baseline)

    def corridor(self, cid: str, speed: float, typical: float = 62.0, mean: float = 0.4, std: float = 0.6) -> None:
        self._replace("corridor_state", "corridor_state_id", f"cs:{cid}")
        self.add("corridor_state", f"cs:{cid}", corridor_state_id=f"cs:{cid}", corridor_id=cid, ts=NOW - pd.Timedelta(minutes=1), speed_kmh=speed,
                 typical_speed_kmh=typical, baseline_exceptions_mean=mean, baseline_exceptions_std=std)

    def shipment(self, *, corridor: str = "DK-01", origin: str = HUB, service: str = "Standard", cod: float | None = None, value: float | None = None,
                 pickup_point: str | None = None, alt_pickup: str | None = None, alt_route: bool = True, spare_courier: bool = True, dest: tuple[float, float] | None = None,
                 sid: str | None = None, courier: str = "cr-1") -> str:
        self.n_ship += 1
        sid = sid or f"{self.sid_prefix}-{self.n_ship:03d}"
        lat, lng = dest or _m(*ADDR, float(self.rng.uniform(-400, 400)), float(self.rng.uniform(-400, 400)))
        self.add("shipment", sid, shipment_id=sid, origin_node_id=origin, courier_id=f"dallal-demo:{courier}", service_level=service,
                 created_ts=self.minutes_ago(420), promised_end_ts=NOW + pd.Timedelta(hours=4), dest_lat=lat, dest_lng=lng,
                 payment_type="COD" if cod else "Prepaid", cod_amount=cod, value=value if value is not None else (cod or 180.0),
                 attrs={"corridor_id": corridor, "pickup_point_id": pickup_point, "alt_pickup_point_id": alt_pickup, "alt_route_available": alt_route,
                        "spare_courier_available": spare_courier,
                        "recipient_phone": f"SANDBOX-{self.n_ship:04d}", "recipient_opt_in": True, "window_text": "14:00-18:00",
                        "recipient_name": f"Recipient {self.n_ship}"})
        return sid

    def event(self, sid: str, etype: str, mins_ago: float, *, code: str | None = None, at: tuple[float, float] | None = None, node: str | None = None) -> None:
        k = f"ev:{sid}:{etype}:{len(self.rows['event'])}"
        self.add("event", k, event_id=k, shipment_id=sid, event_type=etype, ts=self.minutes_ago(mins_ago), ts_quality="exact",
                 raw_code=code, lat=None if at is None else at[0], lng=None if at is None else at[1], node_id=node)

    def journey_base(self, sid: str, *, out_for_delivery_min: float = 90) -> None:
        self.event(sid, "created", 420)
        self.event(sid, "arrived_facility", 330, node=HUB)
        self.event(sid, "scan", 240, node=HUB)
        self.event(sid, "out_for_delivery", out_for_delivery_min)

    def pings(self, sid: str, dest: tuple[float, float], *, moving: bool = True, near_m: float = 3000, span_min: int = 60, at: tuple[float, float] | None = None) -> None:
        """GPS pings every 10 min; moving toward `dest`, or parked at `at` (stationary)."""
        for i, m in enumerate(range(span_min, -1, -10)):
            if moving:
                frac = 1 - i / max(1, span_min // 10)
                pos = _m(*dest, near_m * frac, near_m * frac * 0.5)
            else:
                pos = at if at is not None else _m(*dest, near_m, near_m / 2)
            self.event(sid, "gps_ping", m, at=pos)

    def exception(self, sid: str, code: str, mins_ago: float, label: str | None = None) -> None:
        k = f"exc:{sid}"
        self.add("exception", k, exception_id=k, shipment_id=sid, code=code, label=label or code.replace("_", " ").title(),
                 recorded_ts=self.minutes_ago(mins_ago), recorded_by="courier-app")
        self.event(sid, "exception_recorded", mins_ago, code=code)

    def address(self, sid: str, conf: float = 0.93, past: int = 0, first: bool = False) -> None:
        self.add("address_context", f"ad:{sid}", shipment_id=sid, confidence=conf, geocode_quality="rooftop" if conf > 0.8 else "street", past_failures_at_address=past,
                 first_delivery_to_address=first)

    def recipient(self, sid: str, *, resp: str = "high", channel: str = "WhatsApp", missed: int = 0, confirmed: tuple[float, float] | None = None) -> None:
        kw: dict[str, Any] = {}
        if confirmed:
            kw = {"confirmed_window_start_ts": self.minutes_ago(confirmed[0]), "confirmed_window_end_ts": self.minutes_ago(confirmed[1])}
        self.add("recipient_context", f"rc:{sid}", shipment_id=sid, responsiveness=resp, preferred_channel=channel, missed_windows=missed, **kw)

    def default_context(self, sid: str) -> None:
        self.address(sid)
        self.recipient(sid)

    def background(self, n: int = 4, corridor: str = "DK-01") -> None:
        """Healthy shipments on the same network, so incident logic has something to (not) count."""
        for _ in range(n):
            s = self.shipment(corridor=corridor)
            self.journey_base(s)
            self.default_context(s)

    def standard_nodes(self) -> None:
        self.node(HUB, "hub", "Dammam Hub 1", 26.43, 50.10)
        self.node(HUB2, "hub", "Khobar Hub 1", 26.28, 50.21)
        self.node(PP, "pickup", "Khobar Pickup Point 3", 26.30, 50.20)
        self.node_state(HUB)
        self.corridor("DK-01", 58.0)

    def build(self, subject: str, trigger: dict[str, Any], expected: dict[str, Any]) -> Bundle:
        tables = {}
        for t, rows in self.rows.items():
            if not rows:
                continue
            df = pd.DataFrame(rows)
            tables[t] = df
        b = Bundle(f"{self.scenario}-seed{self.seed}", NOW, subject, trigger, tables, expected)
        b.validate()
        return b


# ── scenario builders ────────────────────────────────────────────────────────────────────────────────────────────────────
def healthy(seed: int) -> Bundle:
    w = World("healthy", seed)
    w.standard_nodes()
    s = w.shipment()
    w.journey_base(s)
    w.pings(s, (w.rows["shipment"][0]["dest_lat"], w.rows["shipment"][0]["dest_lng"]))
    w.default_context(s)
    w.background(3)
    return w.build(s, {"kind": "scheduled_scan"}, {"decision": "resolved", "cause": "none", "must_not_call": ["rank_recovery_actions", "check_incident_context"]})


def address_risk(seed: int) -> Bundle:
    """CASE A. Pre-failure: weak address detected before the attempt. Safe, reversible recovery."""
    w = World("address_risk", seed)
    w.standard_nodes()
    s = w.shipment(value=180.0, pickup_point=None)
    d = (w.rows["shipment"][0]["dest_lat"], w.rows["shipment"][0]["dest_lng"])
    w.journey_base(s, out_for_delivery_min=70)
    w.pings(s, d, moving=True)
    w.address(s, conf=round(float(w.rng.uniform(0.35, 0.5)), 2), past=2, first=True)
    w.recipient(s, resp="high", channel="WhatsApp", missed=0)
    w.background(4)
    return w.build(s, {"kind": "risk_alert", "detail": "address validation failed"},
                   {"decision": "auto_eligible", "cause": "address_issue", "action": "verify_address", "must_not_call": ["check_incident_context"]})


def route_blockage_incident(seed: int) -> Bundle:
    """CASE B. Many failures share one corridor blockage; the subject was mis-coded 'recipient not available'."""
    w = World("route_blockage", seed)
    w.standard_nodes()
    w.corridor("DK-04", speed=float(w.rng.uniform(6, 12)), typical=62.0, mean=0.4, std=0.6)
    held = _m(*ADDR, 2600, 1800)
    s = w.shipment(corridor="DK-04", cod=2450.0)
    d = (w.rows["shipment"][0]["dest_lat"], w.rows["shipment"][0]["dest_lng"])
    w.journey_base(s, out_for_delivery_min=95)
    w.pings(s, d, moving=False, at=held, span_min=50)
    w.exception(s, "RECIPIENT_NOT_AVAILABLE", 11)
    w.default_context(s)
    for i in range(5):  # peers failing on the same corridor within the 30-min window
        p = w.shipment(corridor="DK-04", cod=float(w.rng.choice([0, 0, 380, 640])) or None)
        w.journey_base(p, out_for_delivery_min=100)
        w.pings(p, ADDR, moving=False, at=_m(*held, float(i * 15), float(i * 10)), span_min=40)
        w.exception(p, "RECIPIENT_NOT_AVAILABLE" if i % 2 else "TRAFFIC_DELAY", float(w.rng.uniform(4, 24)))
        w.default_context(p)
    for _ in range(3):  # exposed: still on the corridor, not failed yet
        e = w.shipment(corridor="DK-04")
        w.journey_base(e)
        w.default_context(e)
    w.background(3)
    return w.build(s, {"kind": "exception_recorded"},
                   {"decision": "incident", "cause": "route_disruption", "must_call": ["check_incident_context"], "must_not_call": ["rank_recovery_actions"]})


def custody_conflict(seed: int) -> Bundle:
    """CASE C. 'Delivered' then 'out for delivery' again; recipient disputes; nothing else explains it. Do not guess."""
    w = World("custody_conflict", seed)
    w.standard_nodes()
    s = w.shipment(value=950.0)
    far = _m(*ADDR, 1900, 600)
    w.event(s, "created", 600)
    w.event(s, "arrived_facility", 500, node=HUB)
    w.event(s, "out_for_delivery", 420)
    w.event(s, "delivered", 170, at=far)
    w.event(s, "out_for_delivery", 85)
    w.event(s, "failed_attempt", 40, code="RECIPIENT_NOT_AVAILABLE", at=_m(*ADDR, 20, 10))
    w.pings(s, ADDR, moving=True, near_m=1500, span_min=40)
    w.address(s, conf=0.9)
    w.recipient(s, resp="medium", channel="Call", missed=0)
    w.background(3)
    return w.build(s, {"kind": "analyst_request"}, {"decision": "escalate", "cause": "custody_anomaly", "reason": "conflicting_evidence", "must_not_call": ["rank_recovery_actions"]})


def recipient_unavailable(seed: int) -> Bundle:
    w = World("recipient_unavail", seed)
    w.standard_nodes()
    s = w.shipment(value=260.0)
    d = (w.rows["shipment"][0]["dest_lat"], w.rows["shipment"][0]["dest_lng"])
    w.journey_base(s, out_for_delivery_min=120)
    w.event(s, "failed_attempt", 25, code="RECIPIENT_NOT_AVAILABLE", at=_m(*d, 15, 10))
    w.pings(s, d, moving=False, at=_m(*d, 15, 10), span_min=30)
    w.exception(s, "RECIPIENT_NOT_AVAILABLE", 24)
    w.address(s, conf=0.94)
    w.recipient(s, resp="low", channel="SMS", missed=2)
    w.background(3)
    return w.build(s, {"kind": "exception_recorded"}, {"decision_in": ["auto_eligible", "recommend"], "cause": "recipient_unavailable"})


def repeated_failed_attempts(seed: int) -> Bundle:
    w = World("repeated_failures", seed)
    w.standard_nodes()
    s = w.shipment(value=420.0, pickup_point=PP)
    d = (w.rows["shipment"][0]["dest_lat"], w.rows["shipment"][0]["dest_lng"])
    w.event(s, "created", 3000)
    w.event(s, "arrived_facility", 2900, node=HUB)
    for m in (2400, 1500, 60):
        w.event(s, "out_for_delivery", m + 90)
        w.event(s, "failed_attempt", m, code="RECIPIENT_NOT_AVAILABLE", at=_m(*d, 10, 5))
    w.exception(s, "RECIPIENT_NOT_AVAILABLE", 59)
    w.pings(s, d, moving=False, at=_m(*d, 10, 5), span_min=20)
    w.address(s, conf=0.95)
    w.recipient(s, resp="low", channel="Call", missed=3)
    w.node_state(PP, backlog=0, baseline=0, last_scan_min=20, status="online")
    w.background(3)
    return w.build(s, {"kind": "exception_recorded"}, {"decision_in": ["recommend", "escalate"], "cause": "recipient_unavailable", "failed_attempts": 3})


def branch_backlog_incident(seed: int) -> Bundle:
    w = World("branch_backlog", seed)
    w.standard_nodes()
    w.node_state(HUB, backlog=int(w.rng.integers(170, 230)), baseline=30, last_scan_min=330)
    s = w.shipment()
    w.event(s, "created", 600)
    w.event(s, "arrived_facility", 560, node=HUB)
    w.exception(s, "NO_SCAN", 20)
    w.default_context(s)
    for _ in range(5):
        p = w.shipment()
        w.event(p, "created", 600)
        w.event(p, "arrived_facility", float(w.rng.uniform(380, 520)), node=HUB)
        w.default_context(p)
    return w.build(s, {"kind": "exception_recorded"}, {"decision": "incident", "cause": "facility_backlog", "must_call": ["check_incident_context"]})


def stalled_no_scan(seed: int) -> Bundle:
    w = World("stalled_no_scan", seed)
    w.standard_nodes()
    w.node_state(HUB, backlog=32, baseline=30, last_scan_min=310)
    s = w.shipment()
    w.event(s, "created", 600)
    w.event(s, "arrived_facility", 330, node=HUB)
    w.default_context(s)
    w.background(3)
    return w.build(s, {"kind": "risk_alert"}, {"decision_in": ["auto_eligible", "recommend", "escalate"], "cause_in": ["facility_backlog", "unknown"]})


def pickup_unavailable(seed: int) -> Bundle:
    w = World("pickup_unavail", seed)
    w.standard_nodes()
    w.node_state(PP, backlog=0, baseline=0, last_scan_min=240, status="offline")
    alt = "dallal-demo:pickup:dammam-2"
    w.node(alt, "pickup", "Dammam Pickup Point 2", 26.42, 50.09)
    w.node_state(alt, backlog=3, baseline=5, last_scan_min=8, status="online")
    s = w.shipment(pickup_point=PP, alt_pickup=alt, value=300.0)
    w.event(s, "created", 700)
    w.event(s, "redirected", 400, node=PP)
    w.event(s, "arrived_facility", 380, node=PP)
    w.default_context(s)
    w.background(2)
    return w.build(s, {"kind": "risk_alert"}, {"decision_in": ["recommend", "escalate"], "cause_in": ["pickup_point_unavailable"], "action_in": ["redirect_locker"]})


def courier_never_arrived(seed: int) -> Bundle:
    """Failed attempt logged ~2 km from the address, COD 2,450: best fix is high-impact -> supervisor."""
    w = World("courier_no_show", seed)
    w.standard_nodes()
    s = w.shipment(cod=2450.0)
    d = (w.rows["shipment"][0]["dest_lat"], w.rows["shipment"][0]["dest_lng"])
    far = _m(*d, 1500, 1500)
    w.journey_base(s, out_for_delivery_min=130)
    w.event(s, "failed_attempt", 30, code="RECIPIENT_NOT_AVAILABLE", at=far)
    w.pings(s, d, moving=False, at=far, span_min=30)
    w.exception(s, "RECIPIENT_NOT_AVAILABLE", 29)
    w.address(s, conf=0.95)
    w.recipient(s, resp="high", channel="WhatsApp", missed=0, confirmed=(100, 20))
    w.background(3)
    return w.build(s, {"kind": "exception_recorded"}, {"decision": "escalate", "reason_in": ["conflicting_evidence", "high_impact"], "cause": "attempt_not_completed"})


def unknown_anomaly(seed: int) -> Bundle:
    w = World("unknown_anomaly", seed)
    w.standard_nodes()
    s = w.shipment()
    w.journey_base(s)
    w.exception(s, "UNMAPPED_X77", 15)
    w.pings(s, ADDR, moving=True)
    w.default_context(s)
    w.background(3)
    return w.build(s, {"kind": "exception_recorded"}, {"decision": "escalate", "reason_in": ["unknown_pattern", "insufficient_evidence"]})


SCENARIOS: dict[str, Callable[[int], Bundle]] = {
    "healthy": healthy, "address_risk": address_risk, "route_blockage": route_blockage_incident, "custody_conflict": custody_conflict,
    "recipient_unavailable": recipient_unavailable, "repeated_failures": repeated_failed_attempts, "branch_backlog": branch_backlog_incident,
    "stalled_no_scan": stalled_no_scan, "pickup_unavailable": pickup_unavailable, "courier_no_show": courier_never_arrived,
    "unknown_anomaly": unknown_anomaly,
}

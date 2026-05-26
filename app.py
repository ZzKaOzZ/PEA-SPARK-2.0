"""
PEA SPARK — Provincial Electricity Authority · Prachuap Khiri Khan
GIS distribution-network operations dashboard.

Architectural fixes applied (over original appdemo.py):

  R1  Feeders without any source CB (e.g. NA-side KUA07 / PDDA10F-*) were
      being marked source-off because `all([]) == True`. Now the check
      requires `cb_set` to be non-empty before running `all(...)`. Also
      `cb_status` honours the real PRESENTPOS value from data instead of
      being hard-coded to 1, so closed-by-default CBs reflect the source.

  R2  Tie-switch toggle: derives from R1 + correct PRESENTPOS state.

  R3  Zoom stutter: client-side debounce + skip refresh during pan/zoom
      (see indexpro.html).

  R4  Wrong-feeder snapping on click: brute-force O(N) `find_nearest`
      replaced with scipy.spatial.cKDTree for accuracy at scale.

  R5  Backend/frontend desync: /scada now returns faultLat/faultLon so
      the client can hydrate the marker after reload.

  R6  Feeder-blind snapping was placing 17/146 switches (and could place
      CBs) on nodes belonging to a *different* feeder, which made the
      "energised" colouring of conductors look misaligned with the map.
      Snapping is now feeder-aware (per-feeder cKDTree) and only falls
      back to the global tree if the CB/switch carries no FEEDERID.

  R7  Feeders without any source CB in pscb.json (KUA01 / KUA02 / KUA07
      and the NA-side stubs of PDA02/06/10) used to render as fully
      dark — there was no BFS seed for them at all, even though the
      lines are physically present. A *virtual* source CB ("V-<feeder>")
      is now synthesised at a representative node of each such feeder.
      It behaves exactly like a normal CB (toggleable, snapshotable,
      counted in /scada, recorded in outage history) and is rendered
      with a distinct dashed-diamond icon so the operator knows it
      represents an external tie-feed and can switch it off.

  +   Pre-switching snapshot/restore on clear-fault.
  +   /outage-polygon — convex hull around de-energized nodes.
  +   /dashboard — outage history & stats per feeder / cause / phase
      backed by SQLite (no mock data, only real fault events get logged).
  +   Secrets (SESSION_SECRET, PEA_USERNAME, PEA_PASSWORD) via env.
"""
from __future__ import annotations
import json
import math
import os
import sqlite3
import time
from collections import deque
from datetime import datetime, timezone
from threading import Lock

import numpy as np
from flask import (
    Flask, jsonify, request, abort, session, redirect, render_template, g,
)
from pyproj import Transformer
from scipy.spatial import cKDTree

# ── Coordinate transforms ────────────────────────────────────────────────────
_TRANSFORMER     = Transformer.from_crs("EPSG:24047", "EPSG:4326", always_xy=True)
_TRANSFORMER_INV = Transformer.from_crs("EPSG:4326", "EPSG:24047", always_xy=True)

def to_wgs(x: float, y: float) -> tuple[float, float]:
    lon, lat = _TRANSFORMER.transform(x, y)
    return lon, lat

def to_utm(lon: float, lat: float) -> tuple[float, float]:
    x, y = _TRANSFORMER_INV.transform(lon, lat)
    return x, y

# ── Paths ────────────────────────────────────────────────────────────────────
_HERE    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "data")
DB_PATH  = os.path.join(DATA_DIR, "outages.db")

FEEDER_PALETTE = [
    "#00e5ff","#7c4dff","#ff9100","#00e676","#ff5252","#ffd600",
    "#40c4ff","#b388ff","#ff6e40","#69f0ae","#f06292","#ffab40",
]

# ─────────────────────────────────────────────────────────────────────────────
# Network state
# ─────────────────────────────────────────────────────────────────────────────
class NetworkState:
    def __init__(self):
        self.adjacency:    dict[str, set[str]] = {}
        self.node_feeder:  dict[str, str]       = {}
        self.node_xy:      dict[str, tuple[float, float]] = {}
        self.nodes:        list[tuple[str, float, float]] = []

        # cKDTree + parallel key array used by find_nearest (R4 fix)
        self._kd_tree:     cKDTree | None = None
        self._kd_keys:     list[str] = []

        # R6: per-feeder cKDTrees for feeder-aware snapping
        self._feeder_kd:   dict[str, cKDTree]   = {}
        self._feeder_keys: dict[str, list[str]] = {}

        self.conductor_keys: list[list[str]] = []
        self.conductor_wgs:  list[dict]      = []

        self.switches:     list[dict]        = []
        self.switch_node:  dict[str, str]    = {}
        self.switch_status:dict[str, int]    = {}   # 1=closed 0=open

        self.substations:  list[dict]        = []
        self.cb_node:      dict[str, str]    = {}
        self.cb_feeder:    dict[str, str]    = {}
        self.cb_status:    dict[str, int]    = {}
        self.feeder_cbs:   dict[str, set[str]] = {}

        self.reclosers:    list[dict]        = []
        self.transformers: list[dict]        = []

        self.feeder_color:      dict[str, str] = {}
        self.feeder_edge_count: dict[str, int] = {}

        self.fault_node:   str | None   = None
        self.fault_feeder: str | None   = None
        self.fault_lat:    float | None = None
        self.fault_lon:    float | None = None
        self.fault_id:     int | None   = None
        self.fault_started_at: float | None = None

        # Pre-switching snapshot (for clear-fault restoration)
        self.snapshot_switch:  dict[str, int] | None = None
        self.snapshot_cb:      dict[str, int] | None = None

_STATE: NetworkState | None = None
_STATE_LOCK = Lock()


def load_json(filename: str) -> dict:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"ไม่พบไฟล์ข้อมูล: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def node_key(x: float, y: float) -> str:
    return f"{round(x * 1e4) / 1e4}|{round(y * 1e4) / 1e4}"


def find_nearest(s: NetworkState, x: float, y: float) -> str | None:
    """R4: O(log N) nearest via cKDTree (global, feeder-agnostic)."""
    if s._kd_tree is None or not s._kd_keys:
        return None
    _, idx = s._kd_tree.query([x, y], k=1)
    if idx < 0 or idx >= len(s._kd_keys):
        return None
    return s._kd_keys[int(idx)]


def find_nearest_in_feeder(
    s: NetworkState, x: float, y: float,
    feeder: str | None, fallback: bool = True,
) -> str | None:
    """R6: nearest node *within* `feeder`. Falls back to the global tree
    if the feeder is unknown / has no nodes yet (or fallback=False to
    disable that)."""
    if feeder:
        tree = s._feeder_kd.get(feeder)
        keys = s._feeder_keys.get(feeder, [])
        if tree is not None and keys:
            _, idx = tree.query([x, y], k=1)
            if 0 <= idx < len(keys):
                return keys[int(idx)]
    return find_nearest(s, x, y) if fallback else None


def build_state() -> NetworkState:
    s = NetworkState()
    print("กำลังโหลดข้อมูลเครือข่าย…", flush=True)

    conductor_fc1 = load_json("psconductor.json")
    conductor_fc2 = load_json("naconductor.json")
    all_conductor = conductor_fc1["features"] + conductor_fc2["features"]
    dof_fc1 = load_json("DOF.json")
    dof_fc2 = load_json("naDOF.json")
    all_dof = dof_fc1["features"] + dof_fc2["features"]
    recloser_fc1 = load_json("psrecloser.json")
    recloser_fc2 = load_json("narecloser.json")
    all_recloser = recloser_fc1["features"] + recloser_fc2["features"]
    trans_fc1 = load_json("pstrans.json")
    trans_fc2 = load_json("natrans.json")
    all_trans = trans_fc1["features"] + trans_fc2["features"]
    pscb_fc = load_json("pscb.json")
    # Force all breakers CLOSED at startup
    s.cb_status = {}

    for cb in pscb_fc["features"]:
      fid = cb["properties"].get("id")

      if fid:
        s.cb_status[fid] = 1

    s.snapshot_cb = dict(s.cb_status)
    # Conductors
    for feat in all_conductor:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue
        props  = feat.get("properties") or {}
        feeder = str(props.get("FEEDERID", "UNK"))
        keys: list[str] = []
        for c in coords:
            x, y = float(c[0]), float(c[1])
            k = node_key(x, y)
            if k not in s.node_xy:
                s.node_xy[k] = (x, y)
            keys.append(k)
            s.node_feeder.setdefault(k, feeder)
        for i in range(len(keys) - 1):
            a, b = keys[i], keys[i + 1]
            if a == b:
                continue
            s.adjacency.setdefault(a, set()).add(b)
            s.adjacency.setdefault(b, set()).add(a)
        s.conductor_keys.append(keys)
        s.feeder_edge_count[feeder] = s.feeder_edge_count.get(feeder, 0) + (len(keys) - 1)
        wgs_coords = [list(to_wgs(float(c[0]), float(c[1]))) for c in coords]
        s.conductor_wgs.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": wgs_coords},
            "properties": {"feeder": feeder, "status": "on", "color": "#888"},
        })

    s.nodes = [(k, xy[0], xy[1]) for k, xy in s.node_xy.items()]

    # R4: build cKDTree for nearest-node lookup
    if s.nodes:
        s._kd_keys = [k for k, _, _ in s.nodes]
        arr = np.array([[x, y] for _, x, y in s.nodes], dtype=np.float64)
        s._kd_tree = cKDTree(arr)

    # R6: build a per-feeder cKDTree so CB/switch snapping can prefer
    # nodes that belong to the same FEEDERID. Without this, snapping is
    # purely Euclidean and ~12% of switches end up tagged to the wrong
    # feeder, which makes the energised colouring look wrong on the map.
    from collections import defaultdict as _dd
    by_feeder: dict[str, list[tuple[str, float, float]]] = _dd(list)
    for k, (x, y) in s.node_xy.items():
        f = s.node_feeder.get(k)
        if f:
            by_feeder[f].append((k, x, y))
    for f, arr_f in by_feeder.items():
        if not arr_f:
            continue
        s._feeder_keys[f] = [k for k, _, _ in arr_f]
        s._feeder_kd[f]   = cKDTree(
            np.array([[x, y] for _, x, y in arr_f], dtype=np.float64)
        )

    feeders = sorted(s.feeder_edge_count.keys())
    for i, f in enumerate(feeders):
        s.feeder_color[f] = FEEDER_PALETTE[i % len(FEEDER_PALETTE)]
    for cw in s.conductor_wgs:
        cw["properties"]["color"] = s.feeder_color.get(cw["properties"]["feeder"], "#888")

    # Switches
    for feat in all_dof:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        props = feat.get("properties") or {}
        fid   = str(props.get("FACILITYID", ""))
        if not fid or "S" not in fid.upper():
            continue
        x, y    = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        status  = 0 if int(props.get("PRESENTPOS", 1)) == 0 else 1
        # R6: snap into the switch's declared feeder first; fall back to
        # the global tree only if FEEDERID is missing or that feeder has
        # no nodes yet.
        decl_feeder = str(props.get("FEEDERID", "")) or None
        nearest = find_nearest_in_feeder(s, x, y, decl_feeder)
        if not nearest:
            continue
        feeder  = decl_feeder or s.node_feeder.get(nearest, "UNK")
        subtype = int(props.get("SUBTYPECOD", 0))
        kind    = {5: "Load Break", 3: "Disconnect", 2: "Fuse"}.get(subtype, "Switch")
        lon, lat = to_wgs(x, y)
        s.switches.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": fid, "feeder": feeder, "location": str(props.get("LOCATION", "")),
                "state": "CLOSE" if status == 1 else "OPEN", "status": status, "kind": kind,
            },
        })
        s.switch_node[fid]   = nearest
        s.switch_status[fid] = status

    # Substations (source CBs)
    for feat in pscb_fc.get("features", []):
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        props   = feat.get("properties") or {}
        fid     = str(props.get("FACILITYID", props.get("TAG", "")))
        if not fid:
            continue
        x, y    = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        status  = 0 if int(props.get("PRESENTPOS", 1)) == 0 else 1
        feeder  = str(props.get("FEEDERID", "UNK"))
        # R6: snap CB into its declared feeder. Falls back to global tree
        # if the feeder has no conductors (e.g. PDA0B which is a stub).
        nearest = find_nearest_in_feeder(s, x, y, feeder)
        if not nearest:
            continue
        lon, lat = to_wgs(x, y)
        s.substations.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": fid, "feeder": feeder, "location": str(props.get("LOCATION", "")),
                "state": "CLOSE" if status == 1 else "OPEN", "status": status,
                "tag": str(props.get("TAG", "")), "opVolt": str(props.get("OP_VOLT", "")),
                "virtual": False,
            },
        })
        s.cb_node[fid]   = nearest
        s.cb_feeder[fid] = feeder
        s.cb_status[fid] = status  # R1: honour real PRESENTPOS, do NOT hard-code 1
        s.feeder_cbs.setdefault(feeder, set()).add(fid)

    # R7: Virtual source CBs for feeders that have no real CB in pscb.json.
    # In the real network these feeders are tie-fed from a neighbouring
    # substation (Kuiburi / NA-side bus). Without a seed node, BFS would
    # mark the whole feeder dark and the operator would see lines that
    # don't match the map. The virtual CB is a normal CB record so the
    # operator can switch it OPEN/CLOSE in the UI exactly like a real one.
    for feeder, edge_count in list(s.feeder_edge_count.items()):
        if feeder in s.feeder_cbs or edge_count == 0:
            continue
        keys_in_f = s._feeder_keys.get(feeder, [])
        if not keys_in_f:
            continue
        # Representative node = median X / median Y → snap back to the
        # closest *real* node so the marker sits on conductor geometry.
        xs = sorted(s.node_xy[k][0] for k in keys_in_f)
        ys = sorted(s.node_xy[k][1] for k in keys_in_f)
        cx, cy = xs[len(xs) // 2], ys[len(ys) // 2]
        rep_node = find_nearest_in_feeder(s, cx, cy, feeder, fallback=False)
        if not rep_node:
            continue
        rx, ry   = s.node_xy[rep_node]
        lon, lat = to_wgs(rx, ry)
        vid = f"V-{feeder}"
        s.substations.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": vid, "feeder": feeder,
                "location": f"Tie-feed (virtual) · {feeder}",
                "state": "CLOSE", "status": 1,
                "tag": "VIRTUAL-CB", "opVolt": "",
                "virtual": True,
            },
        })
        s.cb_node[vid]   = rep_node
        s.cb_feeder[vid] = feeder
        s.cb_status[vid] = 1
        s.feeder_cbs.setdefault(feeder, set()).add(vid)

    # Reclosers
    for feat in all_recloser:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        props = feat.get("properties") or {}
        x, y  = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        lon, lat = to_wgs(x, y)
        s.reclosers.append({
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": str(props.get("FACILITYID", props.get("TAG", "RC"))),
                "feeder": str(props.get("FEEDERID", "UNK")),
                "location": str(props.get("LOCATION", "")),
            },
        })

    # Transformers
    for feat in all_trans:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        props = feat.get("properties") or {}
        x, y  = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        lon, lat = to_wgs(x, y)
        s.transformers.append({
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": str(props.get("FACILITYID", "XF")),
                "feeder": str(props.get("FEEDERID", "UNK")),
                "location": str(props.get("LOCATION", "")),
                "rateKva": float(props.get("RATEKVA", 0) or 0),
                "owner": str(props.get("OWNER", "")),
            },
        })

    print(f"  conductors : {len(s.conductor_keys):,}", flush=True)
    print(f"  nodes      : {len(s.nodes):,}", flush=True)
    print(f"  switches   : {len(s.switches):,}", flush=True)
    print(f"  substations: {len(s.substations):,}", flush=True)
    print(f"  CB-less feeders (NA): "
          f"{sum(1 for f in s.feeder_edge_count if f not in s.feeder_cbs):,}", flush=True)
    print(f"  virtual CBs : "
          f"{sum(1 for cb in s.substations if cb['properties'].get('virtual')):,}",
          flush=True)
    return s


def get_state() -> NetworkState:
    global _STATE
    if _STATE is None:
        with _STATE_LOCK:
            if _STATE is None:
                _STATE = build_state()
    return _STATE


# ─────────────────────────────────────────────────────────────────────────────
# SQLite outage history
# ─────────────────────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS outage (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            feeder          TEXT    NOT NULL,
            cause           TEXT    NOT NULL DEFAULT 'Unknown',
            phase           TEXT    NOT NULL DEFAULT 'ALL',
            lat             REAL,
            lon             REAL,
            started_at      REAL    NOT NULL,
            cleared_at      REAL,
            nodes_affected  INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_outage_feeder ON outage(feeder);
        CREATE INDEX IF NOT EXISTS idx_outage_cause  ON outage(cause);
        CREATE INDEX IF NOT EXISTS idx_outage_phase  ON outage(phase);
        CREATE INDEX IF NOT EXISTS idx_outage_open   ON outage(cleared_at);
        """)


# ─────────────────────────────────────────────────────────────────────────────
# Energization (source-aware BFS) — R1 fix on feeder_source_off
# ─────────────────────────────────────────────────────────────────────────────
def compute_energization_ex(
    adjacency:     dict[str, set[str]],
    node_feeder:   dict[str, str],
    cb_node:       dict[str, str],
    cb_feeder:     dict[str, str],
    cb_status:     dict[str, int],
    feeder_cbs:    dict[str, set[str]],
    switch_node:   dict[str, str],
    switch_status: dict[str, int],
    fault_node:    str | None,
) -> set[str]:
    """Core BFS energization. R1: a feeder without any CB is *not* source-off."""
    removed: set[str] = set()
    if fault_node:
        removed.add(fault_node)
    for fid, st in switch_status.items():
        if st == 0 and fid in switch_node:
            removed.add(switch_node[fid])

    # R1 fix: empty cb_set must NOT count as "all open"
    feeder_source_off: set[str] = set()
    for feeder, cb_set in feeder_cbs.items():
        if cb_set and all(cb_status.get(fid, 1) == 0 for fid in cb_set):
            feeder_source_off.add(feeder)

    source_nodes: set[str] = set()
    for fid, node in cb_node.items():
        feeder = cb_feeder.get(fid, "UNK")
        if cb_status.get(fid, 1) == 1 and node not in removed and feeder not in feeder_source_off:
            source_nodes.add(node)

    energized: set[str] = set()
    queue: deque[str]   = deque()
    for n in source_nodes:
        if n not in removed:
            energized.add(n)
            queue.append(n)
    while queue:
        cur = queue.popleft()
        for nb in adjacency.get(cur, set()):
            if nb not in removed and nb not in energized:
                energized.add(nb)
                queue.append(nb)

    # R1: only strip energized nodes whose feeder is in feeder_source_off
    # (NA-side feeders without CBs would have been wrongly stripped before).
    if feeder_source_off:
        for k in list(energized):
            if node_feeder.get(k, "") in feeder_source_off:
                energized.discard(k)
    return energized


def compute_energization(s: NetworkState) -> set[str]:
    return compute_energization_ex(
        s.adjacency, s.node_feeder,
        s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
        s.switch_node, s.switch_status, s.fault_node,
    )


def build_live_conductors(s: NetworkState):
    energized = compute_energization(s)
    feeders_affected: set[str] = set()
    feeders_source_open = sorted(
        feeder for feeder, cb_set in s.feeder_cbs.items()
        if cb_set and all(s.cb_status.get(fid, 1) == 0 for fid in cb_set)
    )
    out = []
    for cw, keys in zip(s.conductor_wgs, s.conductor_keys):
        on = all(k in energized for k in keys)
        if not on:
            feeders_affected.add(cw["properties"]["feeder"])
        out.append({**cw, "properties": {**cw["properties"], "status": "on" if on else "off"}})
    return out, sorted(feeders_affected), feeders_source_open


# ─────────────────────────────────────────────────────────────────────────────
# FISR: switching plan
# ─────────────────────────────────────────────────────────────────────────────
def bfs_island(start, allowed, adjacency, removed) -> set[str]:
    island: set[str] = set()
    if start not in allowed or start in removed:
        return island
    queue = deque([start])
    island.add(start)
    while queue:
        cur = queue.popleft()
        for nb in adjacency.get(cur, set()):
            if nb not in island and nb not in removed and nb in allowed:
                island.add(nb)
                queue.append(nb)
    return island


def generate_switching_plan(s: NetworkState) -> dict:
    if not s.fault_node:
        return {"error": "ไม่มี fault ที่ active กรุณากดปุ่ม Place fault ก่อน"}

    all_nodes  = set(s.adjacency.keys())
    energized0 = compute_energization(s)
    de_nodes0  = all_nodes - energized0

    if not de_nodes0:
        return {
            "steps": [], "faultFeeder": s.fault_feeder,
            "deenergizedNodes": 0, "totalRestorable": 0, "nodesIrrecoverable": 0,
            "summary": "ทุก node มีไฟอยู่แล้ว ไม่ต้องทำ switching",
        }

    removed0: set[str] = set()
    if s.fault_node:
        removed0.add(s.fault_node)
    for fid, st in s.switch_status.items():
        if st == 0 and fid in s.switch_node:
            removed0.add(s.switch_node[fid])

    fault_zone = bfs_island(s.fault_node, de_nodes0 | {s.fault_node},
                            s.adjacency, removed0 - {s.fault_node})

    isolation_candidates: list[str] = []
    for fid, status in s.switch_status.items():
        if status != 1:
            continue
        node = s.switch_node.get(fid)
        if not node:
            continue
        neighbors = s.adjacency.get(node, set())
        in_fault   = node in fault_zone
        near_fault = any(nb in fault_zone for nb in neighbors)
        near_energ = any(nb in energized0 for nb in neighbors)
        if (in_fault or near_fault) and near_energ:
            isolation_candidates.append(fid)

    isolation_candidates.sort(
        key=lambda fid: (s.node_feeder.get(s.switch_node.get(fid, ""), "") != s.fault_feeder,)
    )
    iso_switches = isolation_candidates[:2]

    steps: list[dict] = []
    for fid in iso_switches:
        sw_props = next((sw["properties"] for sw in s.switches if sw["properties"]["id"] == fid), {})
        steps.append({
            "action": "OPEN", "switchId": fid,
            "feeder": sw_props.get("feeder", "?"),
            "location": sw_props.get("location", ""),
            "reason": "แยกจุดฟอลต์ออกจากระบบ (Fault Isolation)",
            "nodesRestored": 0,
        })

    sim_sw = dict(s.switch_status)
    for fid in iso_switches:
        sim_sw[fid] = 0

    energized_iso = compute_energization_ex(
        s.adjacency, s.node_feeder,
        s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
        s.switch_node, sim_sw, s.fault_node,
    )
    de_iso = all_nodes - energized_iso

    removed_iso: set[str] = set()
    if s.fault_node:
        removed_iso.add(s.fault_node)
    for fid, st in sim_sw.items():
        if st == 0 and fid in s.switch_node:
            removed_iso.add(s.switch_node[fid])

    visited: set[str] = set(fault_zone) | removed_iso
    restorable: list[dict] = []

    for start in de_iso:
        if start in visited:
            continue
        island = bfs_island(start, de_iso, s.adjacency, removed_iso)
        if not island:
            continue
        visited.update(island)

        best_sw = None
        for fid, st in sim_sw.items():
            if st != 0:
                continue
            node = s.switch_node.get(fid)
            if not node:
                continue
            neighbors = s.adjacency.get(node, set())
            in_island  = node in island or any(nb in island for nb in neighbors)
            near_energ = any(nb in energized_iso for nb in neighbors)
            if in_island and near_energ:
                if best_sw is None:
                    best_sw = fid
        restorable.append({"island": island, "switch": best_sw, "size": len(island)})

    used_switches: set[str] = set()
    cumulative_sw = dict(sim_sw)
    cumulative_energized = set(energized_iso)

    for item in sorted(restorable, key=lambda x: -x["size"]):
        sw_fid = item["switch"]
        if sw_fid is None or sw_fid in used_switches:
            continue
        used_switches.add(sw_fid)
        cumulative_sw[sw_fid] = 1

        new_energized = compute_energization_ex(
            s.adjacency, s.node_feeder,
            s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
            s.switch_node, cumulative_sw, s.fault_node,
        )
        actually_restored = len(new_energized) - len(cumulative_energized)
        cumulative_energized = new_energized

        sw_props = next((sw["properties"] for sw in s.switches if sw["properties"]["id"] == sw_fid), {})
        steps.append({
            "action": "CLOSE", "switchId": sw_fid,
            "feeder": sw_props.get("feeder", "?"),
            "location": sw_props.get("location", ""),
            "reason": f"คืนไฟให้ {actually_restored:,} nodes (Service Restoration)",
            "nodesRestored": actually_restored,
        })

    for i, step in enumerate(steps):
        step["step"] = i + 1

    total_restorable    = sum(st["nodesRestored"] for st in steps)
    nodes_irrecoverable = len(fault_zone)
    fault_pct = round(nodes_irrecoverable / max(1, len(all_nodes)) * 100, 2)

    return {
        "steps":              steps,
        "faultFeeder":        s.fault_feeder,
        "faultLat":           s.fault_lat,
        "faultLon":           s.fault_lon,
        "faultZoneNodes":     nodes_irrecoverable,
        "faultZonePct":       fault_pct,
        "deenergizedNodes":   len(de_nodes0),
        "totalRestorable":    total_restorable,
        "nodesIrrecoverable": nodes_irrecoverable,
        "summary": (
            f"ดับ {len(de_nodes0):,} nodes | "
            f"fault zone {nodes_irrecoverable:,} nodes ({fault_pct}%) | "
            f"แผน {len(steps)} ขั้นตอน | "
            f"คืนไฟได้ {total_restorable:,} nodes"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Outage polygon — convex hull of de-energized node coordinates
# ─────────────────────────────────────────────────────────────────────────────
def outage_polygon(s: NetworkState) -> dict | None:
    energized = compute_energization(s)
    de_keys   = [k for k in s.adjacency.keys() if k not in energized]
    if len(de_keys) < 3:
        return None
    pts_utm = np.array([s.node_xy[k] for k in de_keys if k in s.node_xy],
                       dtype=np.float64)
    if len(pts_utm) < 3:
        return None
    # Convex hull via scipy
    try:
        from scipy.spatial import ConvexHull
        hull = ConvexHull(pts_utm)
        ring_utm = pts_utm[hull.vertices].tolist()
    except Exception:
        return None
    ring_wgs = [list(to_wgs(x, y)) for x, y in ring_utm]
    if ring_wgs and ring_wgs[0] != ring_wgs[-1]:
        ring_wgs.append(ring_wgs[0])
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring_wgs]},
        "properties": {"nodesAffected": len(de_keys)},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-only-do-not-use-in-prod")
USERNAME = os.environ.get("PEA_USERNAME", "PEAPJK")
PASSWORD = os.environ.get("PEA_PASSWORD", "1234")


@app.teardown_appcontext
def _close_db(exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def _require_login():
    if not session.get("logged_in"):
        return redirect("/login")
    return None


# ── Network read endpoints ──────────────────────────────────────────────────
@app.route("/conductor")
def conductor():
    s = get_state()
    features, _, _ = build_live_conductors(s)
    return jsonify({"type": "FeatureCollection", "features": features})


@app.route("/switches")
def switches():
    s = get_state()
    out = []
    for sw in s.switches:
        fid    = sw["properties"]["id"]
        status = s.switch_status.get(fid, sw["properties"]["status"])
        out.append({**sw, "properties": {**sw["properties"],
                    "status": status, "state": "CLOSE" if status == 1 else "OPEN"}})
    return jsonify({"type": "FeatureCollection", "features": out})


@app.route("/reclosers")
def reclosers():
    return jsonify({"type": "FeatureCollection", "features": get_state().reclosers})


@app.route("/transformers")
def transformers():
    return jsonify({"type": "FeatureCollection", "features": get_state().transformers})


@app.route("/feeders")
def feeders():
    s = get_state()
    return jsonify({"feeders": [
        {
            "id": f, "color": c,
            "edgeCount": s.feeder_edge_count.get(f, 0),
            "hasCb": f in s.feeder_cbs,
        }
        for f, c in sorted(s.feeder_color.items())
    ]})


@app.route("/substations")
def substations():
    s = get_state()

    # Force default CLOSE for every breaker
    for sub in s.substations:
        fid = sub["properties"]["id"]

        if fid not in s.cb_status:
            s.cb_status[fid] = 1

    out = []

    for sub in s.substations:
        fid    = sub["properties"]["id"]
        status = s.cb_status.get(fid, 1)

        out.append({
            **sub,
            "properties": {
                **sub["properties"],
                "status": status,
                "state": "CLOSE" if status == 1 else "OPEN"
            }
        })

    return jsonify({
        "type": "FeatureCollection",
        "features": out
    })


@app.route("/scada")
def scada():
    s = get_state()
    energized = compute_energization(s)
    _, feeders_affected, feeders_source_open = build_live_conductors(s)
    return jsonify({
        "faultActive":       bool(s.fault_node),
        "faultFeeder":       s.fault_feeder,
        "faultLat":          s.fault_lat,        # R5: include for hydration
        "faultLon":          s.fault_lon,        # R5: include for hydration
        "switchOpen":        sum(1 for v in s.switch_status.values() if v == 0),
        "switchTotal":       len(s.switch_status),
        "cbOpen":            sum(1 for v in s.cb_status.values() if v == 0),
        "cbTotal":           len(s.cb_status),
        "nodesOn":           len(energized),
        "nodesOff":          len(s.adjacency) - len(energized),
        "feedersAffected":   feeders_affected,
        "feedersSourceOpen": feeders_source_open,
    })


@app.route("/outage-polygon")
def outage_polygon_route():
    s = get_state()
    poly = outage_polygon(s)
    if poly is None:
        return jsonify({"type": "FeatureCollection", "features": []})
    return jsonify({"type": "FeatureCollection", "features": [poly]})


# ── Write endpoints ─────────────────────────────────────────────────────────
@app.route("/switches/<fid>/toggle", methods=["POST"])
def toggle_switch(fid: str):
    s = get_state()
    if fid not in s.switch_node:
        abort(404)
    nxt = 0 if s.switch_status.get(fid, 1) == 1 else 1
    s.switch_status[fid] = nxt
    return jsonify({"id": fid, "status": nxt, "state": "CLOSE" if nxt == 1 else "OPEN"})


@app.route("/substations/<fid>/toggle", methods=["POST"])
def toggle_substation(fid: str):
    s = get_state()
    if fid not in s.cb_node:
        abort(404)
    nxt = 0 if s.cb_status.get(fid, 1) == 1 else 1
    s.cb_status[fid] = nxt
    return jsonify({"id": fid, "status": nxt, "state": "CLOSE" if nxt == 1 else "OPEN"})


def _take_snapshot(s: NetworkState) -> None:
    if s.snapshot_switch is None:
        s.snapshot_switch = dict(s.switch_status)
        s.snapshot_cb     = dict(s.cb_status)


def _restore_snapshot(s: NetworkState) -> None:
    if s.snapshot_switch is not None:
        s.switch_status = dict(s.snapshot_switch)
    if s.snapshot_cb is not None:
        s.cb_status = dict(s.snapshot_cb)
    s.snapshot_switch = None
    s.snapshot_cb     = None


@app.route("/fault", methods=["POST"])
def set_fault():
    s    = get_state()
    data = request.get_json(force=True) or {}
    lat, lon = float(data["lat"]), float(data["lon"])
    cause = str(data.get("cause", "Unknown"))
    phase = str(data.get("phase", "ALL"))

    xu, yu  = to_utm(lon, lat)
    nearest = find_nearest(s, xu, yu)
    if not nearest:
        return jsonify({"active": False, "feeder": None, "lat": None, "lon": None})

    # Snapshot the pre-fault switching state BEFORE the operator starts
    # isolating / restoring, so /fault DELETE can roll us back cleanly.
    _take_snapshot(s)

    s.fault_node   = nearest
    s.fault_feeder = s.node_feeder.get(nearest, "UNK")
    s.fault_lat    = lat
    s.fault_lon    = lon
    s.fault_started_at = time.time()

    # Record outage in SQLite (real event, no mock data)
    energized = compute_energization(s)
    nodes_off = len(s.adjacency) - len(energized)
    db = get_db()
    cur = db.execute(
        "INSERT INTO outage (feeder, cause, phase, lat, lon, started_at, nodes_affected) "
        "VALUES (?,?,?,?,?,?,?)",
        (s.fault_feeder, cause, phase, lat, lon, s.fault_started_at, nodes_off),
    )
    db.commit()
    s.fault_id = cur.lastrowid

    return jsonify({
        "active": True, "feeder": s.fault_feeder,
        "lat": s.fault_lat, "lon": s.fault_lon,
        "cause": cause, "phase": phase, "outageId": s.fault_id,
    })


@app.route("/fault", methods=["DELETE"])
def clear_fault():
    s = get_state()
    cleared_id = s.fault_id

    # Update outage record with final affected-node count + clear time
    if cleared_id is not None:
        energized = compute_energization(s)
        nodes_off = len(s.adjacency) - len(energized)
        db = get_db()
        db.execute(
            "UPDATE outage SET cleared_at=?, nodes_affected=MAX(nodes_affected,?) "
            "WHERE id=?",
            (time.time(), nodes_off, cleared_id),
        )
        db.commit()

    s.fault_node = s.fault_feeder = s.fault_lat = s.fault_lon = None
    s.fault_id = None
    s.fault_started_at = None

    # Restore pre-switching state (overrides original "open all switches" bug)
    _restore_snapshot(s)

    return jsonify({"active": False, "feeder": None, "lat": None, "lon": None,
                    "outageId": cleared_id})


@app.route("/fault", methods=["GET"])
def get_fault():
    s = get_state()
    return jsonify({"active": bool(s.fault_node), "feeder": s.fault_feeder,
                    "lat": s.fault_lat, "lon": s.fault_lon})


@app.route("/switching-plan", methods=["POST"])
def switching_plan():
    return jsonify(generate_switching_plan(get_state()))


@app.route("/switching-plan/execute/<int:step_idx>", methods=["POST"])
def execute_step(step_idx: int):
    data   = request.get_json(force=True)
    action = data.get("action")
    sw_id  = data.get("switchId")
    s      = get_state()
    if not sw_id:
        abort(400)
    if sw_id in s.switch_node:
        s.switch_status[sw_id] = 1 if action == "CLOSE" else 0
    return jsonify({"ok": True, "switchId": sw_id, "action": action,
                    "newStatus": s.switch_status.get(sw_id)})


# ── Dashboard ───────────────────────────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    redir = _require_login()
    if redir:
        return redir
    return render_template("dashboard.html")


@app.route("/api/outages")
def api_outages():
    db = get_db()
    rows = db.execute(
        "SELECT id, feeder, cause, phase, lat, lon, started_at, cleared_at, "
        "nodes_affected FROM outage ORDER BY started_at DESC"
    ).fetchall()
    def serialise(r):
        dur = None
        if r["cleared_at"] is not None:
            dur = float(r["cleared_at"]) - float(r["started_at"])
        return {
            "id":             r["id"],
            "feeder":         r["feeder"],
            "cause":          r["cause"],
            "phase":          r["phase"],
            "lat":            r["lat"],
            "lon":            r["lon"],
            "startedAt":      datetime.fromtimestamp(r["started_at"], tz=timezone.utc).isoformat(),
            "clearedAt":      (datetime.fromtimestamp(r["cleared_at"], tz=timezone.utc).isoformat()
                               if r["cleared_at"] is not None else None),
            "durationSec":    dur,
            "active":         r["cleared_at"] is None,
            "nodesAffected":  r["nodes_affected"],
        }
    return jsonify({"outages": [serialise(r) for r in rows]})


@app.route("/api/outages/stats")
def api_outages_stats():
    db = get_db()
    def group(field: str):
        rows = db.execute(
            f"SELECT {field} AS k, "
            f"       COUNT(*)                                          AS count, "
            f"       SUM(CASE WHEN cleared_at IS NULL THEN 1 ELSE 0 END) AS active, "
            f"       COALESCE(SUM(nodes_affected),0)                   AS nodes, "
            f"       COALESCE(SUM(COALESCE(cleared_at,?) - started_at),0) AS total_seconds "
            f"FROM outage GROUP BY {field} ORDER BY count DESC",
            (time.time(),)
        ).fetchall()
        return [
            {
                "key":          r["k"],
                "count":        r["count"],
                "active":       r["active"],
                "nodes":        r["nodes"],
                "totalSeconds": r["total_seconds"],
            }
            for r in rows
        ]
    total = db.execute(
        "SELECT COUNT(*) AS c, "
        "       SUM(CASE WHEN cleared_at IS NULL THEN 1 ELSE 0 END) AS a, "
        "       COALESCE(SUM(nodes_affected),0) AS n "
        "FROM outage"
    ).fetchone()
    return jsonify({
        "total": {"count": total["c"], "active": total["a"], "nodes": total["n"]},
        "byFeeder": group("feeder"),
        "byCause":  group("cause"),
        "byPhase":  group("phase"),
    })


# ── Auth ────────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username")
        pw   = request.form.get("password")
        if user == USERNAME and pw == PASSWORD:
            session["logged_in"] = True
            return redirect("/")
        return render_template("login.html", error="LOGIN FAILED")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
def index():
    redir = _require_login()
    if redir:
        return redir
    return render_template("indexpro.html")


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    get_state()
    port = int(os.environ.get("PORT", "5000"))
    print(f"\nSERVER READY → http://0.0.0.0:{port}\n", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

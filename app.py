"""
PEA SPARK — Provincial Electricity Authority · Prachuap Khiri Khan
GIS distribution-network operations dashboard.

Primary runtime (canonical)
---------------------------
* Backend + routes : ``app.py``          → ``python app.py``
* Map / operator UI: ``templates/indexpro.html`` (served at ``/`` after login)

Other files (``apprun.py``, ``templates/indexrun.html``) are optional alternates;
do not treat them as the source of truth when changing behaviour or UI.

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

  R7  Feeders without a source CB in ``cball.json`` get a fallback
      ``V-<feeder>`` only when still unseeded after loading tie-feed CBs.
      Remote tie markers (BVB/CVB, no connecting line in GIS) snap to the
      substation hub or KUA grid interconnect instead of a far-end node.

  +   Pre-switching snapshot/restore on clear-fault.
  +   /outage-polygon — fault-impact zone hull (only when a fault is active).
  +   /dashboard — outage history & stats per feeder / cause / phase
      backed by SQLite (no mock data, only real fault events get logged).
  +   Secrets (SESSION_SECRET, PEA_USERNAME, PEA_PASSWORD) via env.

  R8  Cold start: every source CB (real + virtual) is forced CLOSED via
      ``apply_startup_cb_closed``.  Switches honour GIS ``PRESENTPOS`` from
      ``dofps.json``; ``deviceClass`` splits F-coded dropouts from switches.

  R9  Switching plan: Thai operator brief, per-step ``instructionTh``,
      isolation/restoration sections, fault coords/cause/phase in the plan API.

  R10 Fault placement by typed WGS84 coordinates (Lat/Lon) in addition to map click.

  R11 Consolidated GIS layers (``conducps.json``, ``dofps.json``, ``cball.json``,
      …) driven by ``data/network_config.json`` — one file per asset type.

  R12 ``compute_display_energization``: conductors show the full energised mesh
      before any fault (switch icons still reflect PRESENTPOS); after a fault is
      placed, line status follows real switch/CB topology for on-site accuracy.

  R13 UI layers: Switches (S) vs Dropouts (F) on separate map layers; dropouts
      hidden by default.  Fixed per-feeder colours (``FEEDER_COLOR_MAP``).

  R14 Canonical Thai fault causes (incl. งู) in ``FAULT_CAUSES`` — shared by
      indexpro, dashboard charts, and SQLite via ``/api/fault-causes``.
"""
from __future__ import annotations
import json
import math
import os
import re
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

import numpy as np
from flask import (
    Flask, jsonify, request, abort, session, redirect, render_template, g,
)
from pyproj import Transformer
from scipy.spatial import cKDTree

# ── Paths & network config ───────────────────────────────────────────────────
_HERE    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "data")
DB_PATH  = os.path.join(DATA_DIR, "outages.db")

_DEFAULT_NETWORK_CONFIG: dict = {
    "sourceCrs": "EPSG:32647",
    "nodeKeyDecimals": 1,
    "layers": {
        "conductors":   ["conducps.json"],
        "switches":     ["dofps.json"],
        "reclosers":    ["recloserps.json"],
        "transformers": ["transps.json"],
        "substations":  ["cball.json"],
    },
}


def load_network_config() -> dict:
    """Read ``data/network_config.json`` — layer filenames + source CRS."""
    path = os.path.join(DATA_DIR, "network_config.json")
    if not os.path.exists(path):
        return dict(_DEFAULT_NETWORK_CONFIG)
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    layers = {**_DEFAULT_NETWORK_CONFIG["layers"], **(raw.get("layers") or {})}
    return {
        "sourceCrs":       raw.get("sourceCrs", _DEFAULT_NETWORK_CONFIG["sourceCrs"]),
        "nodeKeyDecimals": int(raw.get("nodeKeyDecimals", _DEFAULT_NETWORK_CONFIG["nodeKeyDecimals"])),
        "cbMaxGeoSnapM":   float(raw.get("cbMaxGeoSnapM", 200)),
        "cbSkipBeyondM":   float(raw.get("cbSkipBeyondM", 8000)),
        "layers":          layers,
    }


def _detect_crs_from_prj() -> str | None:
    for name in ("psconductor.prj", "pscb.prj", "DOF.prj"):
        path = os.path.join(DATA_DIR, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read().upper()
        if "WGS_1984_UTM_ZONE_47" in text or "WGS 84 / UTM ZONE 47" in text:
            return "EPSG:32647"
        if "INDIAN_1975" in text or "EVEREST" in text:
            return "EPSG:24047"
    return None


_NETWORK_CFG = load_network_config()
_SOURCE_CRS  = _NETWORK_CFG.get("sourceCrs") or _detect_crs_from_prj() or "EPSG:32647"
_NODE_DECIMALS = max(0, int(_NETWORK_CFG.get("nodeKeyDecimals", 1)))
_CB_MAX_GEO_SNAP = float(_NETWORK_CFG.get("cbMaxGeoSnapM", 200))
_CB_SKIP_BEYOND  = float(_NETWORK_CFG.get("cbSkipBeyondM", 8000))

# ── Coordinate transforms (must match GIS export CRS) ────────────────────────
_TRANSFORMER     = Transformer.from_crs(_SOURCE_CRS, "EPSG:4326", always_xy=True)
_TRANSFORMER_INV = Transformer.from_crs("EPSG:4326", _SOURCE_CRS, always_xy=True)


def to_wgs(x: float, y: float) -> tuple[float, float]:
    lon, lat = _TRANSFORMER.transform(x, y)
    return lon, lat


def to_utm(lon: float, lat: float) -> tuple[float, float]:
    x, y = _TRANSFORMER_INV.transform(lon, lat)
    return x, y

FEEDER_PALETTE = [
    "#00e5ff","#7c4dff","#ff9100","#00e676","#ff5252","#ffd600",
    "#40c4ff","#b388ff","#ff6e40","#69f0ae","#f06292","#ffab40",
]

# Fixed colours so feeders never share a hue on the map (e.g. PDA10 ≠ KUA01).
FEEDER_COLOR_MAP: dict[str, str] = {
    "KUA01": "#22d3ee",
    "KUA02": "#7c4dff",
    "KUA07": "#ff9100",
    "PDA01": "#00e676",
    "PDA02": "#ff5252",
    "PDA03": "#ffd600",
    "PDA04": "#40c4ff",
    "PDA05": "#b388ff",
    "PDA06": "#ff6e40",
    "PDA07": "#69f0ae",
    "PDA08": "#f06292",
    "PDA09": "#ffab40",
    "PDA10": "#e879f9",
    "PKK-2": "#c4b5fd",
}

TH_MONTH_SHORT = [
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
]

# Canonical fault causes (Thai) — used in indexpro, dashboard, and SQLite records
FAULT_CAUSES: tuple[str, ...] = (
    "สภาพอากาศ",
    "นก",
    "กระรอก",
    "งู",
    "ต้นไม้",
    "ทางมะพร้าว",
    "ไผ่",
    "อุปกรณ์ชำรุด",
    "อุบัติเหตุ",
)

CAUSE_CHART_COLORS: dict[str, str] = {
    "สภาพอากาศ":   "#7c4dff",
    "นก":          "#40c4ff",
    "กระรอก":      "#ff9100",
    "งู":          "#84cc16",
    "ต้นไม้":      "#3fb950",
    "ทางมะพร้าว":  "#00e676",
    "ไผ่":         "#b388ff",
    "อุปกรณ์ชำรุด": "#00e5ff",
    "อุบัติเหตุ":   "#ff5252",
}

# Map legacy English causes (old records) → new Thai labels for charts
CAUSE_LEGACY_MAP: dict[str, str] = {
    "Unknown":    "อุบัติเหตุ",
    "Equipment":  "อุปกรณ์ชำรุด",
    "Vegetation": "ต้นไม้",
    "Weather":    "สภาพอากาศ",
    "Animal":     "นก",
    "Vehicle":    "อุบัติเหตุ",
    "Human":      "อุบัติเหตุ",
}

PHASE_CHART_COLORS: dict[str, str] = {
    "ALL": "#94a3b8",
    "A":   "#f85149",
    "B":   "#d29922",
    "C":   "#3fb950",
    "AB":  "#ff6e40",
    "BC":  "#ffd600",
    "CA":  "#f06292",
}


def normalize_cause(cause: str | None) -> str:
    c = str(cause or "").strip()
    if c in FAULT_CAUSES:
        return c
    if c in CAUSE_LEGACY_MAP:
        return CAUSE_LEGACY_MAP[c]
    return c if c else FAULT_CAUSES[0]


def normalize_phase(phase: str | None) -> str:
    p = str(phase or "ALL").strip().upper()
    return p if p in PHASE_CHART_COLORS else "ALL"


def _feeder_chart_color(feeder: str, index: int) -> str:
    return FEEDER_PALETTE[index % len(FEEDER_PALETTE)]

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
        self.fault_cause:  str | None   = None
        self.fault_phase:  str | None   = None
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


def load_layer_features(layer_key: str) -> list[dict]:
    """Load and merge GeoJSON features listed under ``layers[layer_key]`` in config."""
    cfg = _NETWORK_CFG.get("layers") or _DEFAULT_NETWORK_CONFIG["layers"]
    names = cfg.get(layer_key) or []
    features: list[dict] = []
    for name in names:
        fc = load_json(name)
        features.extend(fc.get("features", []))
    return features


def node_key(x: float, y: float) -> str:
    """Snap endpoints to a grid so T-junctions in GIS connect in the graph."""
    if _NODE_DECIMALS <= 0:
        return f"{round(x)}|{round(y)}"
    factor = 10 ** _NODE_DECIMALS
    return f"{round(x * factor) / factor}|{round(y * factor) / factor}"


def open_switch_nodes(s: NetworkState) -> set[str]:
    return {
        s.switch_node[fid]
        for fid, st in s.switch_status.items()
        if st == 0 and fid in s.switch_node
    }


def _dist2_point_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float,
) -> tuple[float, float, float]:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-12:
        return (px - ax) ** 2 + (py - ay) ** 2, ax, ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    qx, qy = ax + t * dx, ay + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2, qx, qy


def find_nearest_conductor_snap(
    s: NetworkState, x: float, y: float,
) -> tuple[str | None, str | None]:
    """Nearest point on any conductor segment → (feeder, graph node key)."""
    best_d2 = float("inf")
    best_feeder: str | None = None
    best_node: str | None = None

    for keys, cw in zip(s.conductor_keys, s.conductor_wgs):
        feeder = str(cw["properties"].get("feeder", "UNK"))
        for i in range(len(keys)):
            k1 = keys[i]
            x1, y1 = s.node_xy[k1]
            d2, _, _ = _dist2_point_segment(x, y, x1, y1, x1, y1)
            if d2 < best_d2:
                best_d2, best_feeder, best_node = d2, feeder, k1
            if i + 1 < len(keys):
                k2 = keys[i + 1]
                x2, y2 = s.node_xy[k2]
                d2, qx, qy = _dist2_point_segment(x, y, x1, y1, x2, y2)
                if d2 < best_d2:
                    best_d2 = d2
                    best_feeder = feeder
                    near = find_nearest_in_feeder(s, qx, qy, feeder, fallback=False)
                    best_node = near or k1

    return best_feeder, best_node


def find_nearest(s: NetworkState, x: float, y: float) -> str | None:
    """R4: O(log N) nearest via cKDTree (global, feeder-agnostic)."""
    if s._kd_tree is None or not s._kd_keys:
        return None
    _, idx = s._kd_tree.query([x, y], k=1)
    if idx < 0 or idx >= len(s._kd_keys):
        return None
    return s._kd_keys[int(idx)]


def apply_startup_cb_closed(s: NetworkState) -> None:
    """At cold start every source CB (real + virtual) is CLOSED so each feeder
    has an energised seed. GIS ``PRESENTPOS`` is ignored for the initial view;
    toggles and fault snapshots still honour operator actions afterward."""
    for fid in s.cb_status:
        s.cb_status[fid] = 1
    for feat in s.substations:
        p = feat["properties"]
        p["status"] = 1
        p["state"] = "CLOSE"
    s.snapshot_cb = dict(s.cb_status)


def switch_device_class(facility_id: str) -> str:
    """FACILITYID containing ``f`` → dropout (fuse cutout); otherwise switch."""
    return "dropout" if "f" in facility_id.lower() else "switch"


def _add_virtual_source_cb(s: NetworkState, feeder: str) -> bool:
    """Synthesise a tie-feed CB for feeders with conductors but no pscb record."""
    if feeder in s.feeder_cbs or s.feeder_edge_count.get(feeder, 0) == 0:
        return False
    keys_in_f = s._feeder_keys.get(feeder, [])
    if not keys_in_f:
        return False
    xs = sorted(s.node_xy[k][0] for k in keys_in_f)
    ys = sorted(s.node_xy[k][1] for k in keys_in_f)
    cx, cy = xs[len(xs) // 2], ys[len(ys) // 2]
    rep_node = find_nearest_in_feeder(s, cx, cy, feeder, fallback=False)
    if not rep_node:
        rep_node = keys_in_f[len(keys_in_f) // 2]
    rx, ry = s.node_xy[rep_node]
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
    s.cb_node[vid] = rep_node
    s.cb_feeder[vid] = feeder
    s.cb_status[vid] = 1
    s.feeder_cbs.setdefault(feeder, set()).add(vid)
    return True


def ensure_all_feeders_have_source_cb(s: NetworkState) -> int:
    """Second pass: guarantee every feeder with lines has ≥1 CB seed."""
    added = 0
    for feeder in sorted(s.feeder_edge_count):
        if s.feeder_edge_count.get(feeder, 0) == 0:
            continue
        if s.feeder_cbs.get(feeder):
            continue
        if _add_virtual_source_cb(s, feeder):
            added += 1
    return added


def resolve_cb_supply_feeder(
    facility_id: str, declared: str, conductor_feeders: set[str],
) -> str | None:
    """Map a cball record to the feeder it energises on the conductor mesh."""
    decl = (declared or "").strip()
    if decl in conductor_feeders:
        return decl
    fid = facility_id.upper()

    m = re.match(r"^(PDA|KUA)(\d{2})VB", fid)
    if m:
        cand = f"{m.group(1)}{m.group(2)}"
        if cand in conductor_feeders:
            return cand

    # KUA0BVB = bus 0 at the substation → energises KUA01 (not KUA00).
    if fid.startswith("KUA0BVB") and "KUA01" in conductor_feeders:
        return "KUA01"

    m = re.match(r"^KUA(\d)[BC]VB", fid)
    if m:
        n = int(m.group(1))
        if n == 0:
            cand = "KUA01"
        else:
            cand = f"KUA0{n}"
        if cand in conductor_feeders:
            return cand

    m = re.match(r"^KUA(\d)TVB", fid)
    if m:
        cand = f"KUA0{m.group(1)}"
        if cand in conductor_feeders:
            return cand

    if fid.startswith("PDA0BVB") and "PDA05" in conductor_feeders:
        return "PDA05"

    if decl == "PKK-2" and "PKK-2" in conductor_feeders:
        return "PKK-2"

    m = re.match(r"^(PDA|KUA)(\d+)", decl, re.I)
    if m:
        cand = f"{m.group(1).upper()}{int(m.group(2)):02d}"
        if cand in conductor_feeders:
            return cand

    return None


def is_tie_cb_marker(facility_id: str, props: dict) -> bool:
    """True when GIS marks an external / tie-feed source (no tie-line drawn)."""
    if str(props.get("INTERRUPTI", "")).upper() == "V":
        return True
    fid = facility_id.upper()
    return any(tag in fid for tag in ("BVB", "CVB", "TVB"))


def snap_cb_to_feeder(
    s: NetworkState, x: float, y: float, feeder: str,
) -> tuple[str | None, float]:
    """Nearest graph node on ``feeder`` and planar distance in metres (UTM)."""
    node = find_nearest_in_feeder(s, x, y, feeder, fallback=False)
    if not node:
        return None, float("inf")
    nx, ny = s.node_xy[node]
    dist = math.hypot(nx - x, ny - y)
    return node, dist


def _pda_substation_hub_xy(
    s: NetworkState, hub_nodes: dict[str, list[str]],
) -> tuple[float, float] | None:
    """UTM centroid of on-line PDA source CBs (main substation bus)."""
    refs: list[tuple[float, float]] = []
    for feeder in ("PDA05", "PDA07", "PDA10", "PDA02", "PDA01"):
        for node in hub_nodes.get(feeder, []):
            refs.append(s.node_xy[node])
    if not refs:
        return None
    return (
        sum(p[0] for p in refs) / len(refs),
        sum(p[1] for p in refs) / len(refs),
    )


def snap_cb_graph_node(
    s: NetworkState,
    x: float,
    y: float,
    supply: str,
    geo_dist: float,
    hub_nodes: dict[str, list[str]],
) -> str | None:
    """BFS seed for a source CB.

    On-line CBs snap to the nearest conductor node.  Remote tie-feed CBs snap
    to the substation hub when that feeder already has an on-line CB, so power
    enters from the source end — not the far tie-in point.

    KUA feeders with only off-line tie CBs (e.g. KUA01VB 6 km from the mesh)
    seed at the nearest node to the main PDA substation bus instead of the
    remote GIS marker, so the feeder lights from the grid interconnect."""
    if geo_dist <= _CB_MAX_GEO_SNAP:
        node, _ = snap_cb_to_feeder(s, x, y, supply)
        return node
    hubs = hub_nodes.get(supply) or []
    if hubs:
        hx = sum(s.node_xy[n][0] for n in hubs) / len(hubs)
        hy = sum(s.node_xy[n][1] for n in hubs) / len(hubs)
        return find_nearest_in_feeder(s, hx, hy, supply, fallback=False)
    if supply.startswith("KUA"):
        ref = _pda_substation_hub_xy(s, hub_nodes)
        if ref:
            return find_nearest_in_feeder(s, ref[0], ref[1], supply, fallback=False)
    node, _ = snap_cb_to_feeder(s, x, y, supply)
    return node


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
    print(f"  CRS: {_SOURCE_CRS} · node snap: 10^-{_NODE_DECIMALS} m", flush=True)

    all_conductor = load_layer_features("conductors")
    all_dof       = load_layer_features("switches")
    all_recloser  = load_layer_features("reclosers")
    all_trans     = load_layer_features("transformers")
    pscb_fc       = {"features": load_layer_features("substations")}
    s.cb_status = {}
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
        s.feeder_color[f] = FEEDER_COLOR_MAP.get(f) or FEEDER_PALETTE[i % len(FEEDER_PALETTE)]
    for cw in s.conductor_wgs:
        cw["properties"]["color"] = s.feeder_color.get(cw["properties"]["feeder"], "#888")

    # Switches
    for feat in all_dof:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        props = feat.get("properties") or {}
        fid   = str(props.get("FACILITYID", ""))
        if not fid:
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
        device  = switch_device_class(fid)
        subtype = int(props.get("SUBTYPECOD", 0))
        if device == "dropout":
            kind = "Dropout"
        else:
            kind = {5: "Load Break", 3: "Disconnect", 2: "Fuse", 10: "Sectionaliser"}.get(
                subtype, "Switch",
            )
        lon, lat = to_wgs(x, y)
        s.switches.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": fid, "feeder": feeder, "location": str(props.get("LOCATION", "")),
                "state": "CLOSE" if status == 1 else "OPEN", "status": status, "kind": kind,
                "deviceClass": device,
                "presentPos": int(props.get("PRESENTPOS", 1)),
            },
        })
        s.switch_node[fid]   = nearest
        s.switch_status[fid] = status

    # Substations (source CBs) — cball.json may place tie-feeds off the line mesh.
    conductor_feeders = set(s.feeder_edge_count.keys())
    cb_skipped_remote = 0
    cb_pending: list[dict] = []
    for feat in pscb_fc.get("features", []):
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        props  = feat.get("properties") or {}
        fid    = str(props.get("FACILITYID", props.get("TAG", "")))
        if not fid:
            continue
        x, y   = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        status = 0 if int(props.get("PRESENTPOS", 1)) == 0 else 1
        declared = str(props.get("FEEDERID", "") or "").strip()
        supply   = resolve_cb_supply_feeder(fid, declared, conductor_feeders)
        if not supply:
            cb_skipped_remote += 1
            continue
        _, geo_dist = snap_cb_to_feeder(s, x, y, supply)
        if geo_dist > _CB_SKIP_BEYOND:
            cb_skipped_remote += 1
            continue
        cb_pending.append({
            "fid": fid, "x": x, "y": y, "status": status, "supply": supply,
            "geo_dist": geo_dist, "props": props,
        })

    cb_pending.sort(key=lambda r: r["geo_dist"])
    hub_nodes: dict[str, list[str]] = defaultdict(list)
    for row in cb_pending:
        fid, x, y = row["fid"], row["x"], row["y"]
        supply, geo_dist, props, status = (
            row["supply"], row["geo_dist"], row["props"], row["status"],
        )
        graph_node = snap_cb_graph_node(s, x, y, supply, geo_dist, hub_nodes)
        if not graph_node:
            continue
        if geo_dist <= _CB_MAX_GEO_SNAP:
            hub_nodes[supply].append(graph_node)

        tie_marker = is_tie_cb_marker(fid, props)
        logical_tie = geo_dist > _CB_MAX_GEO_SNAP
        virtual = tie_marker or logical_tie

        lon, lat = to_wgs(x, y)
        loc = str(props.get("LOCATION", ""))
        if logical_tie and not loc:
            loc = f"Tie-feed · {supply}"
        s.substations.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": fid, "feeder": supply, "location": loc,
                "state": "CLOSE" if status == 1 else "OPEN", "status": status,
                "tag": str(props.get("TAG", "")), "opVolt": str(props.get("OP_VOLT", "")),
                "virtual": virtual,
                "tieFeed": logical_tie,
            },
        })
        s.cb_node[fid]   = graph_node
        s.cb_feeder[fid] = supply
        s.cb_status[fid] = status  # overwritten by apply_startup_cb_closed()
        s.feeder_cbs.setdefault(supply, set()).add(fid)

    # Fallback: synthesise V-<feeder> only when cball has no seed for that feeder.
    virtual_added = ensure_all_feeders_have_source_cb(s)

    apply_startup_cb_closed(s)
    s.snapshot_switch = dict(s.switch_status)

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
    n_do = sum(1 for sw in s.switches if sw["properties"].get("deviceClass") == "dropout")
    n_sw = len(s.switches) - n_do
    n_open = sum(1 for v in s.switch_status.values() if v == 0)
    print(f"  switches   : {n_sw:,} · dropouts (F): {n_do:,} · open: {n_open:,}", flush=True)
    print(f"  substations: {len(s.substations):,}", flush=True)
    if cb_skipped_remote:
        print(f"  CB skipped (off-map feeders): {cb_skipped_remote}", flush=True)
    print(f"  CB-less feeders: "
          f"{sum(1 for f in s.feeder_edge_count if f not in s.feeder_cbs):,}", flush=True)
    print(f"  virtual CBs : "
          f"{sum(1 for cb in s.substations if cb['properties'].get('virtual')):,}",
          flush=True)
    no_cb = [f for f in s.feeder_edge_count
             if s.feeder_edge_count[f] > 0 and not s.feeder_cbs.get(f)]
    if no_cb:
        print(f"  WARNING feeders still without CB: {no_cb[:8]}", flush=True)
    elif virtual_added:
        print(f"  extra virtual CBs (2nd pass): {virtual_added}", flush=True)
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
            cause           TEXT    NOT NULL DEFAULT 'สภาพอากาศ',
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


def compute_display_energization(s: NetworkState) -> set[str]:
    """Conductor colouring.

    Before any fault: show the full energised mesh (ignore open switches) so
    the map matches the as-built network while switch icons still reflect
    GIS ``PRESENTPOS``.  After a fault is placed, honour real switch/CB
    topology so line status tracks the on-site situation."""
    if s.fault_node:
        return compute_energization(s)
    return compute_energization_ex(
        s.adjacency, s.node_feeder,
        s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
        {}, {}, None,
    )


def build_live_conductors(s: NetworkState):
    energized = compute_display_energization(s)
    affected  = compute_fault_affected_nodes(s) if s.fault_node else set()
    feeders_affected: set[str] = set()
    feeders_source_open = sorted(
        feeder for feeder, cb_set in s.feeder_cbs.items()
        if cb_set and all(s.cb_status.get(fid, 1) == 0 for fid in cb_set)
    )
    out = []
    for cw, keys in zip(s.conductor_wgs, s.conductor_keys):
        if s.fault_node and affected:
            # สายที่โดนผลฟอลต์บางจุด → แสดงดับ (รวมสายแยกในโซนเดียวกัน)
            on = all(k in energized for k in keys) and not any(k in affected for k in keys)
        else:
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


def _format_fault_coords(lat: float | None, lon: float | None) -> str:
    if lat is None or lon is None:
        return "—"
    return f"{lat:.6f}, {lon:.6f}"


def _switch_instruction_th(action: str, switch_id: str, feeder: str, location: str) -> str:
    verb = "เปิด" if action == "OPEN" else "ปิด"
    loc = f" ({location})" if location else ""
    return f"{verb}สวิตช์ {switch_id} · ฟีดเดอร์ {feeder}{loc}"


def generate_switching_plan(s: NetworkState) -> dict:
    if not s.fault_node:
        return {"error": "ไม่มี fault ที่ active กรุณาวางจุดฟอลต์หรือระบุพิกัดก่อน"}

    all_nodes  = set(s.adjacency.keys())
    energized0 = compute_energization(s)
    de_nodes0  = all_nodes - energized0

    if not de_nodes0:
        return {
            "steps": [], "faultFeeder": s.fault_feeder,
            "deenergizedNodes": 0, "totalRestorable": 0, "nodesIrrecoverable": 0,
            "summary": "ทุก node มีไฟอยู่แล้ว ไม่ต้องทำ switching",
        }

    fault_zone = compute_fault_affected_nodes(s)

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
    for iso_idx, fid in enumerate(iso_switches, start=1):
        sw_props = next((sw["properties"] for sw in s.switches if sw["properties"]["id"] == fid), {})
        loc = sw_props.get("location", "")
        feeder = sw_props.get("feeder", "?")
        steps.append({
            "action": "OPEN", "switchId": fid,
            "section": "isolation",
            "feeder": feeder,
            "location": loc,
            "instructionTh": _switch_instruction_th("OPEN", fid, feeder, loc),
            "reason": f"ขั้นที่ {iso_idx} — แยกจุดฟอลต์ (Fault Isolation)",
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
    res_step_no = len(iso_switches)

    for item in sorted(restorable, key=lambda x: -x["size"]):
        sw_fid = item["switch"]
        if sw_fid is None or sw_fid in used_switches:
            continue
        used_switches.add(sw_fid)
        cumulative_sw[sw_fid] = 1
        res_step_no += 1

        new_energized = compute_energization_ex(
            s.adjacency, s.node_feeder,
            s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
            s.switch_node, cumulative_sw, s.fault_node,
        )
        actually_restored = len(new_energized) - len(cumulative_energized)
        cumulative_energized = new_energized

        sw_props = next((sw["properties"] for sw in s.switches if sw["properties"]["id"] == sw_fid), {})
        loc = sw_props.get("location", "")
        feeder = sw_props.get("feeder", "?")
        steps.append({
            "action": "CLOSE", "switchId": sw_fid,
            "section": "restoration",
            "feeder": feeder,
            "location": loc,
            "instructionTh": _switch_instruction_th("CLOSE", sw_fid, feeder, loc),
            "reason": f"ขั้นที่ {res_step_no} — คืนไฟ {actually_restored:,} nodes",
            "nodesRestored": actually_restored,
        })

    for i, step in enumerate(steps):
        step["step"] = i + 1

    total_restorable    = sum(st["nodesRestored"] for st in steps)
    nodes_irrecoverable = len(fault_zone)
    fault_pct = round(nodes_irrecoverable / max(1, len(all_nodes)) * 100, 2)

    iso_count = sum(1 for st in steps if st["action"] == "OPEN")
    res_count = sum(1 for st in steps if st["action"] == "CLOSE")
    coords_txt = _format_fault_coords(s.fault_lat, s.fault_lon)
    cause = normalize_cause(s.fault_cause)
    phase = s.fault_phase or "ALL"
    operator_brief = (
        f"ฟีดเดอร์ {s.fault_feeder or '?'} · พิกัด {coords_txt} · "
        f"สาเหตุ {cause} · เฟส {phase} · "
        f"แยกฟอลต์ {iso_count} ขั้น · คืนไฟ {res_count} ขั้น"
    )
    next_step = steps[0] if steps else None
    next_hint = (
        next_step["instructionTh"]
        if next_step
        else "ไม่มีขั้นตอน — ตรวจสอบสถานะเครือข่าย"
    )

    return {
        "steps":              steps,
        "faultFeeder":        s.fault_feeder,
        "faultLat":           s.fault_lat,
        "faultLon":           s.fault_lon,
        "faultCoords":        coords_txt,
        "faultCause":         cause,
        "faultPhase":         phase,
        "operatorBrief":      operator_brief,
        "nextStepHint":       next_hint,
        "isolationSteps":     iso_count,
        "restorationSteps":   res_count,
        "faultZoneNodes":     nodes_irrecoverable,
        "faultZonePct":       fault_pct,
        "deenergizedNodes":   len(de_nodes0),
        "totalRestorable":    total_restorable,
        "nodesIrrecoverable": nodes_irrecoverable,
        "summary": (
            f"ดับ {len(de_nodes0):,} nodes · "
            f"โซนฟอลต์ {nodes_irrecoverable:,} ({fault_pct}%) · "
            f"แผน {len(steps)} ขั้น (แยก {iso_count} / คืน {res_count}) · "
            f"คืนไฟได้ {total_restorable:,} nodes"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fault-impact polygon — only after an active fault is placed
# ─────────────────────────────────────────────────────────────────────────────
def compute_fault_affected_nodes(s: NetworkState) -> set[str]:
    """โซนดับทั้งหมดที่ต่อจากจุดฟอลต์ผ่านสายที่ไม่มีไฟ (รวมสายแยก) จนถึงสวิตช์เปิด."""
    if not s.fault_node:
        return set()
    energized = compute_energization(s)
    open_sw   = open_switch_nodes(s)
    affected: set[str] = set()
    queue: deque[str] = deque()

    def try_add(n: str) -> None:
        if n in energized or n in open_sw or n in affected:
            return
        affected.add(n)
        queue.append(n)

    try_add(s.fault_node)
    for nb in s.adjacency.get(s.fault_node, set()):
        try_add(nb)

    while queue:
        cur = queue.popleft()
        for nb in s.adjacency.get(cur, set()):
            try_add(nb)

    return affected


def _utm_ring_to_wgs_polygon(ring_utm: list[tuple[float, float]]) -> list[list[float]]:
    ring_wgs = [list(to_wgs(x, y)) for x, y in ring_utm]
    if ring_wgs and ring_wgs[0] != ring_wgs[-1]:
        ring_wgs.append(ring_wgs[0])
    return ring_wgs


def _buffer_ring_utm(cx: float, cy: float, radius_m: float, sides: int = 24) -> list[tuple[float, float]]:
    return [
        (cx + radius_m * math.cos(2 * math.pi * i / sides),
         cy + radius_m * math.sin(2 * math.pi * i / sides))
        for i in range(sides)
    ]


def _polygon_ring_from_utm_points(pts_utm: np.ndarray, min_radius_m: float = 60.0) -> list[list[float]] | None:
    if len(pts_utm) == 0:
        return None
    if len(pts_utm) < 3:
        cx, cy = float(pts_utm[:, 0].mean()), float(pts_utm[:, 1].mean())
        spread = float(np.max(np.linalg.norm(pts_utm - np.array([cx, cy]), axis=1))) if len(pts_utm) > 1 else 0.0
        radius = max(min_radius_m, spread + 40.0)
        ring_utm = _buffer_ring_utm(cx, cy, radius)
        return _utm_ring_to_wgs_polygon(ring_utm)
    try:
        from scipy.spatial import ConvexHull
        hull = ConvexHull(pts_utm)
        ring_utm = pts_utm[hull.vertices].tolist()
    except Exception:
        cx, cy = float(pts_utm[:, 0].mean()), float(pts_utm[:, 1].mean())
        ring_utm = _buffer_ring_utm(cx, cy, min_radius_m * 2)
    return _utm_ring_to_wgs_polygon(ring_utm)


def outage_polygon(s: NetworkState) -> dict | None:
    """Convex hull around nodes impacted by the active fault only."""
    if not s.fault_node:
        return None
    affected = compute_fault_affected_nodes(s)
    if not affected:
        return None
    keys = [k for k in affected if k in s.node_xy]
    if not keys:
        return None
    pts_utm = np.array([s.node_xy[k] for k in keys], dtype=np.float64)
    ring_wgs = _polygon_ring_from_utm_points(pts_utm)
    if not ring_wgs:
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring_wgs]},
        "properties": {
            "nodesAffected": len(keys),
            "faultFeeder":   s.fault_feeder,
            "faultCoords":   _format_fault_coords(s.fault_lat, s.fault_lon),
            "zone":          "fault-impact",
            "includesLaterals": True,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-only-do-not-use-in-prod")
USERNAME = os.environ.get("PEA_USERNAME", "PEAPJK")
PASSWORD = os.environ.get("PEA_PASSWORD", "1234")


@app.route("/api/fault-causes")
def api_fault_causes():
    """Canonical outage causes for indexpro dropdown and dashboard charts."""
    return jsonify({
        "causes":      list(FAULT_CAUSES),
        "causeColors": dict(CAUSE_CHART_COLORS),
    })


@app.route("/api/network-config")
def api_network_config():
    """Expose CRS + layer filenames for operators / debugging."""
    return jsonify({
        "sourceCrs":       _SOURCE_CRS,
        "nodeKeyDecimals": _NODE_DECIMALS,
        "cbMaxGeoSnapM":   _CB_MAX_GEO_SNAP,
        "cbSkipBeyondM":   _CB_SKIP_BEYOND,
        "layers":          _NETWORK_CFG.get("layers"),
        "dataDir":         DATA_DIR,
    })


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
    energized = compute_display_energization(s)
    live, _, _ = build_live_conductors(s)
    seg_on: dict[str, int] = defaultdict(int)
    seg_tot: dict[str, int] = defaultdict(int)
    for seg in live:
        fid = seg["properties"]["feeder"]
        seg_tot[fid] += 1
        if seg["properties"]["status"] == "on":
            seg_on[fid] += 1
    node_tot: dict[str, int] = defaultdict(int)
    node_on: dict[str, int] = defaultdict(int)
    for k, f in s.node_feeder.items():
        node_tot[f] += 1
        if k in energized:
            node_on[f] += 1
    return jsonify({"feeders": [
        {
            "id": f, "color": c,
            "edgeCount": s.feeder_edge_count.get(f, 0),
            "hasCb": f in s.feeder_cbs,
            "nodesOn": node_on.get(f, 0),
            "nodesTotal": node_tot.get(f, 0),
            "segmentsOn": seg_on.get(f, 0),
            "segmentsTotal": seg_tot.get(f, 0),
        }
        for f, c in sorted(s.feeder_color.items())
    ]})


@app.route("/substations")
def substations():
    s = get_state()
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
    energized = compute_display_energization(s)
    _, feeders_affected, feeders_source_open = build_live_conductors(s)
    return jsonify({
        "faultActive":       bool(s.fault_node),
        "lineDisplayFull":   not bool(s.fault_node),
        "faultFeeder":       s.fault_feeder,
        "faultLat":          s.fault_lat,
        "faultLon":          s.fault_lon,
        "faultCoords":       _format_fault_coords(s.fault_lat, s.fault_lon),
        "faultCause":        s.fault_cause,
        "faultPhase":        s.fault_phase,
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
    cause = normalize_cause(str(data.get("cause", FAULT_CAUSES[0])))
    phase = normalize_phase(str(data.get("phase", "ALL")))

    xu, yu = to_utm(lon, lat)
    snap_feeder, snap_node = find_nearest_conductor_snap(s, xu, yu)
    nearest = snap_node or find_nearest(s, xu, yu)
    if snap_feeder and nearest:
        on_feeder = find_nearest_in_feeder(s, xu, yu, snap_feeder, fallback=False)
        if on_feeder:
            nearest = on_feeder
    if not nearest:
        return jsonify({
            "active": False,
            "error": "ไม่พบโหนดเครือข่ายใกล้พิกัดนี้ — ลองเลื่อนพิกัดให้ใกล้สายจำหน่าย",
            "feeder": None, "lat": None, "lon": None,
        })

    # Snapshot the pre-fault switching state BEFORE the operator starts
    # isolating / restoring, so /fault DELETE can roll us back cleanly.
    _take_snapshot(s)

    s.fault_node   = nearest
    s.fault_feeder = snap_feeder or s.node_feeder.get(nearest, "UNK")
    s.fault_lat    = lat
    s.fault_lon    = lon
    s.fault_cause  = cause
    s.fault_phase  = phase
    s.fault_started_at = time.time()

    # Record outage in SQLite (real event, no mock data)
    affected  = compute_fault_affected_nodes(s)
    nodes_off = len(affected) if affected else len(s.adjacency) - len(compute_energization(s))
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
    s.fault_cause = s.fault_phase = None
    s.fault_id = None
    s.fault_started_at = None

    # Restore pre-switching state (overrides original "open all switches" bug)
    _restore_snapshot(s)

    return jsonify({"active": False, "feeder": None, "lat": None, "lon": None,
                    "outageId": cleared_id})


@app.route("/fault", methods=["GET"])
def get_fault():
    s = get_state()
    return jsonify({
        "active": bool(s.fault_node), "feeder": s.fault_feeder,
        "lat": s.fault_lat, "lon": s.fault_lon,
        "coords": _format_fault_coords(s.fault_lat, s.fault_lon),
        "cause": s.fault_cause, "phase": s.fault_phase,
    })


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
def _cause_chart_color(cause: str) -> str:
    return CAUSE_CHART_COLORS.get(normalize_cause(cause), "#64748b")


_TH_TZ = timezone(timedelta(hours=7))


def _format_outage_datetime_th(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=_TH_TZ)
    return f"{dt.day} {TH_MONTH_SHORT[dt.month - 1]} {dt.year + 543} {dt.hour:02d}:{dt.minute:02d}"


@app.route("/api/outages/monthly")
def api_outages_monthly():
    """Monthly outage counts + per-cause breakdown for dashboard charts."""
    db = get_db()
    rows = db.execute(
        "SELECT id, cause, feeder, phase, lat, lon, started_at "
        "FROM outage ORDER BY started_at ASC"
    ).fetchall()

    by_month: dict[str, dict] = defaultdict(
        lambda: {
            "count": 0,
            "byCause": defaultdict(int),
            "byFeeder": defaultdict(int),
            "byPhase": defaultdict(int),
            "events": [],
        }
    )
    for r in rows:
        ts = float(r["started_at"])
        dt = datetime.fromtimestamp(ts, tz=_TH_TZ)
        key = f"{dt.year:04d}-{dt.month:02d}"
        cause  = normalize_cause(r["cause"])
        feeder = str(r["feeder"] or "UNK")
        phase  = normalize_phase(r["phase"])
        lat, lon = r["lat"], r["lon"]
        by_month[key]["count"] += 1
        by_month[key]["byCause"][cause] += 1
        by_month[key]["byFeeder"][feeder] += 1
        by_month[key]["byPhase"][phase] += 1
        by_month[key]["events"].append({
            "id":        r["id"],
            "feeder":    feeder,
            "cause":     cause,
            "phase":     phase,
            "lat":       lat,
            "lon":       lon,
            "coords":    _format_fault_coords(lat, lon) if lat is not None and lon is not None else "—",
            "dateTh":    _format_outage_datetime_th(ts),
            "startedAt": ts,
        })

    all_feeders: set[str] = set()
    months: list[dict] = []
    for key in sorted(by_month.keys()):
        y, m = int(key[:4]), int(key[5:7])
        by_cause  = dict(by_month[key]["byCause"])
        by_feeder = dict(by_month[key]["byFeeder"])
        by_phase  = dict(by_month[key]["byPhase"])
        events    = sorted(by_month[key]["events"], key=lambda e: -e["startedAt"])
        all_feeders.update(by_feeder.keys())
        months.append({
            "key":      key,
            "label":    f"{TH_MONTH_SHORT[m - 1]} {y + 543}",
            "labelEn":  f"{TH_MONTH_SHORT[m - 1]} {y}",
            "year":     y,
            "month":    m,
            "count":    by_month[key]["count"],
            "byCause":  by_cause,
            "byFeeder": by_feeder,
            "byPhase":  by_phase,
            "events":   events,
        })

    feeders_sorted = sorted(all_feeders)
    feeder_colors = {
        f: _feeder_chart_color(f, i) for i, f in enumerate(feeders_sorted)
    }
    all_phases = sorted(
        {p for mo in months for p in mo["byPhase"]},
        key=lambda p: (p != "ALL", p),
    )

    return jsonify({
        "months":        months,
        "causes":        list(FAULT_CAUSES),
        "causeColors":   dict(CAUSE_CHART_COLORS),
        "feeders":       feeders_sorted,
        "feederColors":  feeder_colors,
        "phases":        all_phases,
        "phaseColors":   {p: PHASE_CHART_COLORS.get(p, "#64748b") for p in all_phases},
        "totalOutages":  sum(mo["count"] for mo in months),
    })


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
    """Main operator dashboard — UI lives in templates/indexpro.html."""
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
    print(f"\nSERVER READY → http://0.0.0.0:{port}", flush=True)
    print("  UI: templates/indexpro.html\n", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

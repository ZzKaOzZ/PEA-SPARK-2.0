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

  R15 Outage zone: per-feeder hull from off conductor geometry (all segments
      of a feeder treated as one mesh); only open *tie* switches cut flow;
      pre-fault display still shows every line energised (R12).

  R16 Ring-circuit model after fault: display and switching-plan treat open
      tie switches as non-isolating (both ends fed by neighbour sources).
      Only the local fault section darkens; plan cuts apply to switches
      opened in the plan, not pre-existing open ties.

  R17 Dependent laterals: branch lines with no connection outside the fault
      zone (fed only via main-line taps / reclosers / dropouts inside the
      zone) are included in the outage polygon and conductor-off display.

  R18 Protection-device taps: reclosers and dropouts snap lateral endpoints
      within 50 m into the graph (GIS node-key gaps).  Outage expansion stops
      at *open* tie switches; closed ties block only cross-feeder jumps.

  R19 Directional fault zone: load-side dropout/tie rules for switching display;
      source-side open switches included as zone boundaries (R19).

  R20 Maintenance work zone: start/end coordinates + job name/number for
      planned switching; ``/maintenance`` API and maintenance switching plan.

  R21 Live fault display = topological zone minus physical energization so
      operator switch actions (open tie iso / close cross-feeder) update the
      map immediately.  Switching plan prioritises tie switches and suggests
      closing open cross-feeder ties for back-feed restoration.

  R22 Reclosers toggle open/close like switches for sectionalising isolation
      (``POST /reclosers/<id>/toggle``); switching plan prefers reclosers over
      tie switches when both can isolate the same section.

  R23 Physical display when fault/iso active; open-RC downstream islands cut;
      switching plan starts from main-line, lateral RCs only with back-feed tie;
      isolation ranked by smallest outage / customers (NUMBEROFUS).

  R24 KUA remote source CBs seed at the far line end (opposite PDA interconnect).
      Source CB Open counts active feeders only.

  R25 KUA fault switching assumes supply from line end only; post-repair
      normalization plan restores pre-fault switch / recloser positions.

  R26 Pre-fault display: all conductors energized (100 %) with initial GIS
      switch positions; physical model only when fault or maintenance active.

  R27 KUA fault zone: source/load split uses line-end energization only so
      the dark polygon extends away from the remote end, not toward PDA ties.

  R28 Fault form: pick feeder when multiple lines near field-reported coords.

  R29 Directional outage display: show full topological fault zone until the
      operator opens isolation devices; then subtract load-side back-feed restore.
      Conductor energization uses the logical ring so unrelated open switches do
      not create spurious dark areas far from the fault.

  R30 Compute cache + faster switching-plan ranking; single scroll for norm steps.

  R31 Tie-section isolation prefers tripping main-line reclosers over opening
      two blade switches; multi-tie load transfer ranked by customers restored;
      live physical display after any operator switch/RC change.

  R32 KUA07 tie-feed stub: remote VB CB snapped onto a GIS-disconnected spur
      (12 nodes) while the main mesh sat 1.4 km away — source/load split broke
      and the outage zone bled into PDA03/PDA06.  Bridge stub→main when a
      tie-feed CB sits on a small island; KUA directional traces stay on the
      feeder mesh and stop at PDA-grid interconnect ties (PDA03S-09, …).

  R33 Grid interconnect vs mid-line sectionaliser: switches with ``FEEDERID2``
      (e.g. PDA04S-17 PDA04↔PDA05) are cross-feeder ties only — open normal
      state does not sectionalise the host feeder; isolation plans skip them;
      restoration closes open interconnect ties for back-feed.

  R34 Dependent laterals + source corridor: branch meshes snapped via
      recloser/dropout taps were not graph-adjacent to the main-line core, so
      lateral conductors stayed lit.  Pull in GIS-near branch segments, then
      graph-walk without entering the live source partition.  Source-ward from
      fault, include nodes back to the first open switch/tie on the source path.

  R35 GIS ``ENABLED=0`` switches/reclosers (e.g. retired PDA07S-11) were still
      loaded with ``PRESENTPOS=0`` and treated as open sectionalisers, so the
      main-line display on the source path stopped short of the substation
      despite no live tie breaker.  Decommissioned assets are excluded from
      topology; the source-ward main-line corridor then continues to the CB.

  R36 Large fault zones made ``/conductor`` and ``/outage-polygon`` scan every
      segment × every affected node (minutes of CPU, blank map).  Zone proximity
      uses a cKDTree; outage hulls merge per feeder when off segments exceed
      a threshold so the overlay appears immediately after placing a fault.

  R37 Operator outage rules (PDA + KUA): load-side BFS is complete until open
      tie/RC; source corridor is the shortest path toward the source CB and
      stops at the first open device on that path (else reaches the CB); every
      lateral graph-connected to the dark main (excluding the still-live source
      partition) is included.

  R38 KUA outage boundary: KUA faults darken load-ward to the PDA grid-tie and
      include the source-ward main-line corridor back to the line-end CB (same
      rule as PDA ``_source_corridor_to_open_device``).  Never into the PDA
      mesh.  Tie markers cap traces; laterals on the dark main are included.

  R39 Operator-selected feeder scope: outage polygon, conductor-off display, and
      fault-zone nodes apply only to ``fault_feeders`` (multi-select).  Parallel
      KUA corridors that were not selected stay energised on the map even when
      geographically close.  Multiple feeders at one coordinate each get an
      independent directional zone unioned into the display.

  R40 PDA fault zone: source/load hop-count and load-side BFS stay on the feeder
      mesh (no bleed into neighbouring feeders at the substation).  GIS-near stub
      endpoints bridge onto the mesh when no switch/dropout/RC blocks.  Outage
      polygons always use per-segment corridor buffers — never the wide hull.

  R41 PDA load-side traces shortest-path corridors to every line-end past the
      fault, then BFS + hop-island merge.  Conductor vertices that GIS-snap to
      the dark zone are pulled in so dependent laterals de-energise with the main.

  R42 PDA colocated-node merge, chain-gap bridges, protection-device branch
      expansion.  SCADA Energized % from affected nodes (not logical ring 100%).

  R48 Live display trim: after operator switch/RC/back-feed, outage polygons and
      conductor-off shading use only nodes still physically dark within the fault/
      maintenance feeder scope — restored areas lose their polygons immediately.
      SCADA Energized % follows physical supply once topology changes.

  R49 Live map matches switching-plan energization: open grid interconnects block
      until closed; KUA merges line-end + cross-feeder supply; after isolation
      only (e.g. RC trip) the topological polygon stays until a restoration step
      (tie CLOSE / sectional OPEN) restores load — then polygons trim, conductors
      tint with the actual source-feeder colour, and Energized reflects live load.

  R43 PDA source corridor: fault → CB (or nearest open device) on hop-strict
      source-side mesh only — fixes “stops before CB with no open switch” without
      ring bleed through the load-side (R42 had disabled all source extension).

  R44 Full feeder mesh bridges (all feeders, not only PDA) plus GIS-zone lateral
      expansion so branch lines inside the main outage envelope de-energise fully.

  R45 PDA line-end corridors on full feeder mesh (not hop-only islands) so
      branches from PDA04R-01 / PDA04F-044 and similar RC/dropout taps reach
      physical line ends on meshed ring feeders.

  R46 Switching-plan operator rules (supersedes R22/R31 tie-vs-RC priority):
      tie switches first — dropouts never appear in the plan; lateral reclosers
      only when line-end or cross-feeder back-feed is possible (otherwise skip
      RC); isolation ranked by smallest collateral outage; low-customer restoration
      steps deferred so large-system back-feed runs first.

  R47 KUA↔PDA grid ties (``ENABLED=0`` in GIS but operated in field — e.g.
      PDA02S-08, PDA10S-08, PDA03S-09) load onto the map and into interconnect
      logic.  KUA line-end energization for switching plans treats tripped RCs as
      graph barriers only — not ``_open_recloser_forced_dark`` — so RC isolation
      + sectionaliser open (e.g. PDA10R-01 + PDA10S-13) back-feeds correctly.
      Switching-plan energization blocks open grid interconnects until the
      operator closes them; after RC trip, mandatory CLOSE steps for reachable
      KUA↔PDA ties (PDA02 before PDA10 when both apply).  After sectional OPEN
      (e.g. PDA10S-13), a NOTE step confirms line-end back-feed before repair.

  R50 Recloser bypass ties (``ENABLED=0`` in GIS, normally ``PRESENTPOS=0`` open —
      e.g. KUA01S-15, PDA03S-16 beside each RC) load back onto the map after R35
      had dropped all disabled switches.  They are excluded from mid-line
      sectionalising so an open bypass does not truncate the main-line display.

  R51 Operator map refresh: ``/live-refresh`` bundles conductor + SCADA + outage
      + switches + reclosers + substations in one cached single-pass build
      (``live_map_bundle``); browser polls at 15–30 s with in-flight guard.

  R52 KUA01 mainline preset switching: faults between PDA10S-08↔PDA10S-13,
      PDA10S-13↔PDA10S-14, or PDA10S-14↔KUA01R-04 use operator-defined step
      sequences (RC/tie/sectionaliser) instead of the generic FISR planner;
      other feeders and out-of-range KUA01 faults keep the existing planner.

  R53 KUA line-end map display waits for operator NOTE ack (step 3) after
      isolation opens a sectionaliser; tie CLOSE then shows neighbour-feeder
      colours.  Plan execute tracks steps on server state and refreshes live map.
      RC bypass blades (e.g. KUA01S-15) no longer block conductor ON display
      during KUA line-end restoration; open bypass at a closed RC (e.g. KUA01R-04)
      must not truncate line-end energization tracing (R53).  Line-end display no
      longer trims hop-0 seed when a sectionaliser is opened for restoration (R54).

  R55 Tripped isolation RCs no longer block conductor paint during back-feed;
      supply map extends through conductor spans; PDA02 CB seeds colour segments
      past PDA10R-01 after PDA02S-08 closes.

  R56 KUA line-end-only restore (step 3 NOTE ack, tie still open) trims mesh
      bleed past tripped RCs and caps hop at the open restoration sectionaliser
      so supply colours flow from the remote line end (e.g. KUA01R-04 → PDA10S-13)
      not substation-ward from PDA10S-08; PDA02 stays dark until PDA02S-08 closes.

  R57 PDA interconnect back-feed corridor (PDA02S-08 → PDA10R-01) walks the mesh
      bidirectionally within the tie↔RC hop band so ring paths energise and tint
      PDA02; supply overwrite uses the same corridor for map colour + outage trim.

  R58 Supply BFS overwrite no longer re-queues settled nodes — fixes hang on step 4.

  R59 PDA interconnect back-feed stops at open isolation RCs (e.g. PDA10R-01):
      no load-side energization/colour past the RC; open RCs block conductor paint
      (RC bypass blades still ignored). PDA02 tint only tie → RC corridor.

  R60 Foreign PDA supply tint cannot inherit or extend along the KUA mesh past the
      tie→RC paint zone — fixes purple bleed on KUA01/KUA07 mainline.

  R61 Tie→RC corridor uses hop-cap graph walk (not hop-band); line-end + PDA
      back-feed split so KUA01 lights only past the open sectional, PDA02 corridor
      wins supply colour; processing bar during live-refresh.

  R62 Isolation envelope: source corridors union paths to every open tie/RC (not
      only the nearest) so main-line polygons stay when a lateral RC and a main-line
      tie are both opened.  Live restoration trim keeps the operator-blocked section
      dark until ties/RCs are reclosed for system restoration.

  R63 Step-4 back-feed display: conductor span extension is used only for supply
      tinting — OFF state and outage polygons use actual node energization so the
      S-08 / R-01 / S-13 block stays shaded after PDA02 tie CLOSE until full restore.

  R64 Step-4 line-end + PDA back-feed: live energization unions capped line-end
      supply past the open sectional with the tie→RC corridor; outage polygons and
      OFF conductors never extend past PDA10S-13 toward the KUA line end.

  R65 Step-4 map paint: substation-ward force-OFF (open sectional floor) must not
      darken the PDA interconnect corridor — segments already live from tie→RC
      back-feed stay ON with PDA02 supply colour; residual outage remains only in
      the S-08 / R-01 / S-13 isolation block.

  R66 KUA multi-sectional isolation (e.g. PDA10S-13 + PDA10S-14): line-end
      supply floor uses the outermost open sectional (max hop), not the innermost;
      open sectionals always block interconnect back-feed so the fault band between
      two opened sectionalisers stays dark with outage polygons after restoration.

  R67 KUA live energization stays on the KUA mesh (no unbounded adjacency flood
      into PDA feeders). Interconnect back-feed hop-cap includes open sectionals
      so PDA10 tint covers S-08→S-14 laterals only; unrelated feeders keep native
      GIS colours during restoration (no KUA01 paint across the whole map).

  R68 Fault behind a recloser (all feeders): auto-OPEN the nearest upstream
      closed RC and limit the initial outage corridor so darkness only reaches
      back to that RC — not past it toward the CB/source.

  R69 Lateral RC (e.g. PDA07R-01): outage behind the RC is the load-side island
      only (hop ≥ RC, reachable from RC load taps) — must not paint the main
      line past the tap using a feeder-wide hop floor.  Lit main-line segments
      adjacent to the RC stay ON; 45 m outage buffers / open-tie discs must not
      GIS-bleed across the tap onto the trunk.

  R70 PDA↔PDA grid interconnects with GIS ``ENABLED=0`` (field-operated N/O ties
      e.g. PDA05S-11, PDA05S-15 between PDA05↔PDA07) load onto the map like
      KUA↔PDA ties — previously skipped so they vanished from the operator view.

  R71 PDA07R-01 lateral preset (PDA07 only): fault between RC↔PDA07S-12 opens
      PDA07S-12 then closes PDA05S-15 (+ repair); fault load-side of PDA07S-12
      opens PDA07S-12 then closes PDA05S-11.  Closed PDA05 interconnect paints
      PDA05 supply colour up to the open sectional; open-RC forced-dark must not
      strip that legitimate back-feed.

  R72 Lateral RC island uses hop-tree load side (source-ward hits RC): mesh must
      not pull the main line past the tap into the outage.  Open-lateral forced-dark
      only darkens that island — never the CB/mainline side.  PDA interconnect
      restore walks stay off the CB-side of open lateral RCs.

  R73 KUA line-end restoration sectionals must not apply on PDA feeders: opening
      PDA07S-12 was ignored as a paint/supply barrier (treated like KUA S-13),
      so PDA07 GIS colour leaked onto the PDA05S-15 back-feed corridor.

  R74 PDA interconnect restore: force back-feed tint on every ON segment that
      touches ``back_paint_zone`` (e.g. coastal spur past PDA05S-15).  Execute
      step returns ``liveMap`` so the UI paints immediately without losing a
      race to a stale ``/live-refresh`` poll.

  R75 Execute must not block on full ``liveMap`` rebuild: embedding the map in
      ``/switching-plan/execute`` made step 1 (e.g. OPEN PDA07S-12) appear stuck
      because the switch status response waited for a multi-minute map pass.
      Status returns immediately; map refresh stays on ``/live-refresh``.

  R76 PDA interconnect back-feed corridor: mesh walk from closed tie on the
      faulted feeder (not clipped to live-display ``phys``) so forced-dark nodes
      on the tie→open-sectional highway stay lit; map off-check uses
      ``paint_energized`` and keeps approach legs ON at the open sectional.
      Outage polygons from fault-side OFF legs must not GIS-bleed onto the
      restored corridor (45 m buffers across the open sectional / closed tie).
      Map layer order keeps conductors above outage fill at PDA05S-15.
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
_KUA_STUB_BRIDGE_MAX_M = float(_NETWORK_CFG.get("kuaStubBridgeMaxM", 5000))

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
_LATERAL_SNAP_M = 50.0  # GIS tap gap at recloser / dropout lateral branches
_RC_BYPASS_SNAP_M = 15.0  # GIS bypass blade colocated with a recloser (R50)
_PDA_STUB_BRIDGE_MAX_M = 75.0  # wider chain-gap bridge (PDA09/10, all feeders R44)
_FEEDER_STUB_BRIDGE_WIDE_M = 75.0  # alias — second-pass stub snap (R44)
_PDA_COLOCATE_M = 1.5  # merge duplicate GIS coords on same feeder (R42/R44)
_LATERAL_SEGMENT_MAX_KEYS = 48  # GIS-zone lateral pull (R44)
_PDA_RING_DIP_SLACK = 8  # hop slack for meshed ring line-end paths (R45)
_OUTAGE_HULL_SEGMENT_THRESHOLD = 350  # per-feeder hull when zone is large (R36)
_FAULT_COORD_SNAP_M = 20.0       # typed field coords (road beside line)
_FAULT_MAP_CLICK_SNAP_M = 200.0  # map click — pixel pick can be off the GIS segment
# R46 — defer tie/sectionalising steps that restore very few customers
_LOW_IMPACT_RESTORE_CUSTOMERS = 10
_LOW_IMPACT_RESTORE_RATIO = 0.08

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
        self.tie_switch_ids: set[str]        = set()  # non-dropout switches
        self.interconnect_switch_ids: set[str] = set()  # FEEDERID2 cross-feeder ties
        self.rc_bypass_switch_ids: set[str] = set()  # open bypass blade at RC tap (R50)
        # KUA↔PDA grid ties (incl. ENABLED=0) — outage walls only (R38)
        self.kua_pda_boundary_ids: set[str] = set()
        self.kua_pda_boundary_nodes: set[str] = set()
        self.kua_pda_boundary_by_feeder: dict[str, set[str]] = defaultdict(set)

        self.substations:  list[dict]        = []
        self.cb_node:      dict[str, str]    = {}
        self.cb_feeder:    dict[str, str]    = {}
        self.cb_status:    dict[str, int]    = {}
        self.feeder_cbs:   dict[str, set[str]] = {}

        self.reclosers:    list[dict]        = []
        self.recloser_node: dict[str, str]   = {}   # FACILITYID → graph node
        self.recloser_status: dict[str, int] = {}  # 1=closed 0=open/tripped
        self.recloser_customers: dict[str, int] = {}  # GIS NUMBEROFUS
        self.switch_customers: dict[str, int] = {}    # dropout NUMBEROFUS (R42)
        self.transformers: list[dict]        = []

        self.feeder_color:      dict[str, str] = {}
        self.feeder_edge_count: dict[str, int] = {}

        self.fault_node:   str | None   = None
        self.fault_feeder: str | None   = None   # primary (snap / switching plan)
        self.fault_feeders: list[str]   = []     # operator-selected scope (R39)
        self.fault_lat:    float | None = None
        self.fault_lon:    float | None = None
        self.fault_cause:  str | None   = None
        self.fault_phase:  str | None   = None
        self.fault_id:     int | None   = None
        self.fault_started_at: float | None = None

        # Pre-switching snapshot (for clear-fault restoration)
        self.snapshot_switch:  dict[str, int] | None = None
        self.snapshot_cb:      dict[str, int] | None = None
        self.snapshot_recloser: dict[str, int] | None = None

        # Active switching-plan runtime (operator execute progress — R53)
        self.switching_plan_steps: list[dict] = []
        self.switching_plan_executed: int = 0
        self.kua_line_end_display_ack: bool = False

        # Maintenance work zone (R20)
        self.maint_active:     bool = False
        self.maint_start_lat:  float | None = None
        self.maint_start_lon:  float | None = None
        self.maint_end_lat:    float | None = None
        self.maint_end_lon:    float | None = None
        self.maint_start_node: str | None = None
        self.maint_end_node:   str | None = None
        self.maint_feeder:     str | None = None
        self.maint_job_name:   str | None = None
        self.maint_job_number: str | None = None

        self._cc_ver:   int = 0
        self._cc_store: dict = {}

_STATE: NetworkState | None = None
_STATE_LOCK = Lock()


def _invalidate_compute_cache(s: NetworkState) -> None:
    s._cc_ver += 1


def _cc_get(s: NetworkState, key: str, factory):
    """Versioned compute cache — never store a result built across an invalidate.

    Without the version check, a slow ``live_refresh`` started before ``/fault``
    can finish after invalidate and poison the cache with a no-fault payload,
    leaving FAULT FEEDER=none and Generate Plan disabled (R76)."""
    if s._cc_store.get("_ver") != s._cc_ver:
        s._cc_store.clear()
        s._cc_store["_ver"] = s._cc_ver
    if key in s._cc_store:
        return s._cc_store[key]
    ver_before = s._cc_ver
    value = factory()
    if s._cc_ver != ver_before:
        # Topology changed mid-compute — recompute once against current version.
        if s._cc_store.get("_ver") != s._cc_ver:
            s._cc_store.clear()
            s._cc_store["_ver"] = s._cc_ver
        if key in s._cc_store:
            return s._cc_store[key]
        ver_retry = s._cc_ver
        value = factory()
        if s._cc_ver != ver_retry:
            return value
    if s._cc_store.get("_ver") != s._cc_ver:
        s._cc_store.clear()
        s._cc_store["_ver"] = s._cc_ver
    s._cc_store[key] = value
    return value


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
    """Open sectionalising switches — excludes RC bypass blades (R50)."""
    return {
        s.switch_node[fid]
        for fid, st in s.switch_status.items()
        if (
            st == 0
            and fid in s.switch_node
            and fid not in s.rc_bypass_switch_ids
        )
    }


def open_recloser_nodes(s: NetworkState) -> set[str]:
    """Graph nodes of open (tripped) reclosers."""
    return {
        s.recloser_node[fid]
        for fid, st in s.recloser_status.items()
        if st == 0 and fid in s.recloser_node
    }


def open_isolation_nodes(s: NetworkState) -> set[str]:
    """Open switches + open reclosers — sectionalising cuts for fault tracing."""
    return open_switch_nodes(s) | open_recloser_nodes(s)


def open_tie_switch_nodes(s: NetworkState) -> set[str]:
    """Nodes of open *sectionalising* switches (excludes grid interconnect ties)."""
    return open_sectionalizing_switch_nodes(s)


def open_sectionalizing_switch_nodes(s: NetworkState) -> set[str]:
    """Open mid-line / sectionalising switches — these cut feeder energization."""
    sec = _sectionalizing_switch_ids(s)
    return {
        s.switch_node[fid]
        for fid in sec
        if s.switch_status.get(fid, 1) == 0 and fid in s.switch_node
    }


def open_interconnect_switch_nodes(s: NetworkState) -> set[str]:
    """Open cross-feeder interconnect switches (normal standby at grid ties)."""
    return {
        s.switch_node[fid]
        for fid in s.interconnect_switch_ids
        if s.switch_status.get(fid, 1) == 0 and fid in s.switch_node
    }


def _sectionalizing_switch_ids(s: NetworkState) -> frozenset[str]:
    """Blade switches that sectionalise one feeder — not grid ties or RC bypass."""
    return frozenset(
        s.tie_switch_ids - s.interconnect_switch_ids - s.rc_bypass_switch_ids,
    )


def _link_protection_device_taps(s: NetworkState) -> int:
    """Wire GIS-near lateral endpoints onto recloser/dropout graph nodes (R18)."""
    anchors: list[tuple[str, str, float, float]] = []
    seen_anchor: set[tuple[str, str]] = set()

    def add_anchor(feeder: str, node: str, x: float, y: float) -> None:
        key = (feeder, node)
        if key in seen_anchor:
            return
        seen_anchor.add(key)
        anchors.append((feeder, node, x, y))

    for rc in s.reclosers:
        props = rc["properties"]
        fid = props["id"]
        feeder = props["feeder"]
        lon, lat = rc["geometry"]["coordinates"]
        x, y = to_utm(lon, lat)
        node = find_nearest_in_feeder(s, x, y, feeder, fallback=True)
        if not node:
            continue
        s.recloser_node[fid] = node
        ax, ay = s.node_xy.get(node, (x, y))
        add_anchor(feeder, node, ax, ay)

    for sw in s.switches:
        props = sw["properties"]
        if props.get("deviceClass") != "dropout":
            continue
        fid = props["id"]
        node = s.switch_node.get(fid)
        if not node or node not in s.node_xy:
            continue
        feeder = props.get("feeder") or s.node_feeder.get(node, "UNK")
        ax, ay = s.node_xy[node]
        add_anchor(feeder, node, ax, ay)

    lateral_endpoints: set[str] = set()
    for i, keys in enumerate(s.conductor_keys):
        feeder_tag = str(s.conductor_wgs[i]["properties"].get("feeder", "UNK"))
        for k in keys:
            same = sum(
                1 for nb in s.adjacency.get(k, set())
                if s.node_feeder.get(nb) == feeder_tag
            )
            if same <= 2:
                lateral_endpoints.add(k)

    snap2 = _LATERAL_SNAP_M * _LATERAL_SNAP_M
    links = 0
    linked: set[tuple[str, str]] = set()
    for feeder, anchor, ax, ay in anchors:
        for k in s._feeder_keys.get(feeder, []):
            if k == anchor or k not in s.node_xy:
                continue
            if k not in lateral_endpoints:
                continue
            x, y = s.node_xy[k]
            if (x - ax) ** 2 + (y - ay) ** 2 > snap2:
                continue
            pair = (anchor, k) if anchor < k else (k, anchor)
            if pair in linked:
                continue
            linked.add(pair)
            s.adjacency.setdefault(anchor, set()).add(k)
            s.adjacency.setdefault(k, set()).add(anchor)
            links += 1
    return links


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


def find_conductor_snaps_near(
    s: NetworkState,
    x: float,
    y: float,
    *,
    max_dist_m: float = 500.0,
    limit: int = 12,
    feeder_filter: str | None = None,
) -> list[dict]:
    """Feeders with conductor segments within ``max_dist_m`` of ``(x,y)`` UTM."""
    best: dict[str, tuple[float, str]] = {}

    for keys, cw in zip(s.conductor_keys, s.conductor_wgs):
        feeder = str(cw["properties"].get("feeder", "UNK"))
        if feeder_filter and feeder != feeder_filter:
            continue
        for i in range(len(keys)):
            k1 = keys[i]
            x1, y1 = s.node_xy[k1]
            d2, _, _ = _dist2_point_segment(x, y, x1, y1, x1, y1)
            if d2 < best.get(feeder, (float("inf"), ""))[0]:
                best[feeder] = (d2, k1)
            if i + 1 < len(keys):
                k2 = keys[i + 1]
                x2, y2 = s.node_xy[k2]
                d2, qx, qy = _dist2_point_segment(x, y, x1, y1, x2, y2)
                if d2 < best.get(feeder, (float("inf"), ""))[0]:
                    near = find_nearest_in_feeder(s, qx, qy, feeder, fallback=False)
                    best[feeder] = (d2, near or k1)

    out: list[dict] = []
    for feeder, (d2, node) in best.items():
        dist_m = math.sqrt(d2)
        if dist_m <= max_dist_m:
            out.append({
                "feeder": feeder,
                "node": node,
                "distM": round(dist_m, 1),
            })
    out.sort(key=lambda r: (r["distM"], r["feeder"]))
    return out[:limit]


def find_nearest_conductor_snap(
    s: NetworkState, x: float, y: float,
    feeder: str | None = None,
) -> tuple[str | None, str | None]:
    """Nearest point on a conductor segment → (feeder, graph node key)."""
    if feeder:
        snaps = find_conductor_snaps_near(
            s, x, y, max_dist_m=5000.0, limit=1, feeder_filter=feeder,
        )
        if snaps:
            return snaps[0]["feeder"], snaps[0]["node"]
        node = find_nearest_in_feeder(s, x, y, feeder, fallback=False)
        return feeder if node else None, node

    snaps = find_conductor_snaps_near(s, x, y, max_dist_m=5000.0, limit=1)
    if snaps:
        return snaps[0]["feeder"], snaps[0]["node"]

    best_d2 = float("inf")
    best_feeder: str | None = None
    best_node: str | None = None

    for keys, cw in zip(s.conductor_keys, s.conductor_wgs):
        fdr = str(cw["properties"].get("feeder", "UNK"))
        for i in range(len(keys)):
            k1 = keys[i]
            x1, y1 = s.node_xy[k1]
            d2, _, _ = _dist2_point_segment(x, y, x1, y1, x1, y1)
            if d2 < best_d2:
                best_d2, best_feeder, best_node = d2, fdr, k1
            if i + 1 < len(keys):
                k2 = keys[i + 1]
                x2, y2 = s.node_xy[k2]
                d2, qx, qy = _dist2_point_segment(x, y, x1, y1, x2, y2)
                if d2 < best_d2:
                    best_d2 = d2
                    best_feeder = fdr
                    near = find_nearest_in_feeder(s, qx, qy, fdr, fallback=False)
                    best_node = near or k1

    return best_feeder, best_node


def snap_fault_to_network(
    s: NetworkState,
    x: float,
    y: float,
    *,
    feeder_hint: str | None = None,
    max_dist_m: float | None = None,
) -> tuple[str | None, str | None, float | None]:
    """Snap reported coords to the nearest on-line graph node within ``max_dist_m``."""
    limit_m = max_dist_m if max_dist_m is not None else _FAULT_COORD_SNAP_M
    snaps = find_conductor_snaps_near(
        s, x, y,
        max_dist_m=limit_m,
        limit=1,
        feeder_filter=feeder_hint,
    )
    if not snaps:
        if feeder_hint:
            return None, None, None
        snaps = find_conductor_snaps_near(
            s, x, y, max_dist_m=limit_m, limit=1,
        )
    if not snaps:
        return None, None, None
    rec = snaps[0]
    feeder = str(rec["feeder"])
    node = str(rec["node"])
    on_feeder = find_nearest_in_feeder(s, x, y, feeder, fallback=False)
    if on_feeder:
        node = on_feeder
    return feeder, node, float(rec["distM"])


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


def is_grid_interconnect_switch(props: dict) -> bool:
    """True when GIS marks a cross-feeder tie (``FEEDERID2`` ≠ ``FEEDERID``).

    Examples: PDA04S-17 (PDA04↔PDA05), PDA03S-09 (KUA07↔PDA03).  These are
    grid interconnects — not mid-line sectionalisers on the host feeder."""
    feeder = str(props.get("FEEDERID", "") or props.get("feeder", "")).strip()
    feeder2 = str(props.get("FEEDERID2", "") or props.get("feeder2", "")).strip()
    return bool(feeder2 and feeder2 != feeder)


def is_kua_pda_interconnect(props: dict) -> bool:
    """True when ``FEEDERID`` / ``FEEDERID2`` join a KUA feeder to a PDA feeder."""
    f1 = str(props.get("FEEDERID", "") or props.get("feeder", "")).strip()
    f2 = str(props.get("FEEDERID2", "") or props.get("feeder2", "")).strip()
    if not f2 or f2 == f1:
        return False
    ku = f1.startswith("KUA") or f2.startswith("KUA")
    pd = f1.startswith("PDA") or f2.startswith("PDA")
    return ku and pd


def _register_kua_pda_boundary_markers(
    s: NetworkState, dof_features: list,
) -> None:
    """Register KUA↔PDA tie graph nodes as outage boundary markers (R38).

    Loaded even when ``ENABLED=0`` — the switches stay out of energization
    logic but their snapped nodes cap KUA directional outage traces."""
    for feat in dof_features:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        props = feat.get("properties") or {}
        if not is_kua_pda_interconnect(props):
            continue
        fid = str(props.get("FACILITYID", ""))
        if not fid or fid in s.kua_pda_boundary_ids:
            continue
        x, y = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        f1 = str(props.get("FEEDERID", "")).strip()
        f2 = str(props.get("FEEDERID2", "")).strip()
        kua_f = f1 if f1.startswith("KUA") else f2
        nearest = find_nearest_in_feeder(s, x, y, kua_f) or find_nearest(s, x, y)
        if not nearest:
            continue
        s.kua_pda_boundary_ids.add(fid)
        s.kua_pda_boundary_nodes.add(nearest)
        s.kua_pda_boundary_by_feeder[kua_f].add(nearest)
        for nb in s.adjacency.get(nearest, set()):
            nf = s.node_feeder.get(nearest, "")
            nbf = s.node_feeder.get(nb, "")
            if nf.startswith("KUA") and nbf.startswith("PDA"):
                s.kua_pda_boundary_nodes.add(nearest)
                s.kua_pda_boundary_by_feeder[nf].add(nearest)
            elif nbf.startswith("KUA") and nf.startswith("PDA"):
                s.kua_pda_boundary_nodes.add(nb)
                s.kua_pda_boundary_by_feeder[nbf].add(nb)


def gis_device_enabled(props: dict) -> bool:
    """True when GIS marks the asset in service (``ENABLED`` ≠ 0).

    Retired records often keep ``PRESENTPOS=0``; they must not sectionalise
    feeders or truncate fault corridors (R35)."""
    if "ENABLED" not in props:
        return True
    raw = props.get("ENABLED")
    if raw is None or raw == "":
        return True
    return int(raw) != 0


def _recloser_gis_points(recloser_features: list) -> list[tuple[float, float]]:
    """UTM coordinates of recloser points for bypass-tie proximity (R50)."""
    out: list[tuple[float, float]] = []
    for feat in recloser_features:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        out.append((float(coords[0]), float(coords[1])))
    return out


def is_recloser_bypass_switch(
    props: dict,
    xy: tuple[float, float] | None,
    rc_points: list[tuple[float, float]],
) -> bool:
    """``ENABLED=0`` bypass blade at a recloser — map only, not main-line iso (R50)."""
    if gis_device_enabled(props):
        return False
    if is_kua_pda_interconnect(props):
        return False
    loc = str(props.get("LOCATION", "") or "")
    if "bypass" in loc.lower():
        return True
    feeder = str(props.get("FEEDERID", "") or props.get("feeder", "")).strip()
    feeder2 = str(props.get("FEEDERID2", "") or props.get("feeder2", "")).strip()
    if feeder2 and feeder2 != feeder:
        return False
    if not xy or not rc_points:
        return False
    x, y = xy
    if not any(
        math.hypot(x - rx, y - ry) <= _RC_BYPASS_SNAP_M for rx, ry in rc_points
    ):
        return False
    present = int(props.get("PRESENTPOS", 1))
    normal = int(props.get("NORMALSTAT", present))
    # Normally open bypass; some GIS rows (e.g. PDA04S-15) mark NORMALSTAT=0
    # but PRESENTPOS=1 — still the RC bypass blade.
    return present == 0 or normal == 0


def _gis_switch_status(props: dict, *, rc_bypass: bool) -> int:
    """Map GIS switch position — honour NORMALSTAT for mismarked bypass blades."""
    present = int(props.get("PRESENTPOS", 1))
    normal = int(props.get("NORMALSTAT", present))
    if rc_bypass and not gis_device_enabled(props) and normal == 0 and present != 0:
        return 0
    return 0 if present == 0 else 1


def gis_switch_loadable(
    props: dict,
    *,
    xy: tuple[float, float] | None = None,
    rc_points: list[tuple[float, float]] | None = None,
) -> bool:
    """Load switch onto map/topology — grid ties + RC bypass blades (R47/R50/R70).

    GIS ``ENABLED=0`` still loads when the asset is a cross-feeder interconnect
    (KUA↔PDA or PDA↔PDA) or an RC bypass blade operated in the field."""
    if gis_device_enabled(props):
        return True
    if is_grid_interconnect_switch(props):
        return True
    return is_recloser_bypass_switch(props, xy, rc_points or [])


def tie_switch_counts(s: NetworkState) -> tuple[int, int]:
    """Open/total for tie switches only (excludes F-coded dropouts)."""
    tie_ids = [
        sw["properties"]["id"]
        for sw in s.switches
        if sw["properties"].get("deviceClass") != "dropout"
    ]
    open_n = sum(1 for fid in tie_ids if s.switch_status.get(fid, 1) == 0)
    return open_n, len(tie_ids)


def _add_virtual_source_cb(s: NetworkState, feeder: str) -> bool:
    """Synthesise a tie-feed CB for feeders with conductors but no pscb record."""
    if feeder in s.feeder_cbs or s.feeder_edge_count.get(feeder, 0) == 0:
        return False
    if feeder.startswith("KUA"):
        rep_node = _kua_source_seed_node(s, feeder)
        if not rep_node:
            return False
    else:
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


def _pda_substation_hub_xy_from_state(s: NetworkState) -> tuple[float, float] | None:
    """PDA bus centroid from snapped on-line CB graph nodes."""
    refs: list[tuple[float, float]] = []
    for fid, node in s.cb_node.items():
        feeder = s.cb_feeder.get(fid, "")
        if not feeder.startswith("PDA"):
            continue
        props = next(
            (f["properties"] for f in s.substations if f["properties"]["id"] == fid),
            {},
        )
        if props.get("tieFeed"):
            continue
        refs.append(s.node_xy[node])
    if not refs:
        return None
    return (
        sum(p[0] for p in refs) / len(refs),
        sum(p[1] for p in refs) / len(refs),
    )


def _feeder_mesh_nodes(s: NetworkState, feeder: str) -> set[str]:
    """All graph nodes tagged to ``feeder`` in the conductor mesh."""
    return set(s._feeder_keys.get(feeder, []))


def _isolation_barrier_nodes(s: NetworkState) -> set[str]:
    """Graph nodes where a switch, dropout, or recloser is snapped (R40)."""
    nodes = set(s.recloser_node.values())
    nodes |= set(s.switch_node.values())
    return nodes


def _feeder_endpoint_nodes(s: NetworkState, feeder: str) -> list[str]:
    """Dead-end / stub nodes on ``feeder`` (≤1 same-feeder neighbour)."""
    mesh = _feeder_mesh_nodes(s, feeder)
    out: list[str] = []
    for k in mesh:
        same = sum(
            1 for nb in s.adjacency.get(k, set())
            if s.node_feeder.get(nb) == feeder
        )
        if same <= 1:
            out.append(k)
    return out


def _feeders_for_mesh_bridges(s: NetworkState) -> list[str]:
    """Feeders that have a conductor node mesh (R44 — all mapped feeders)."""
    return [f for f in s.feeder_edge_count if s._feeder_keys.get(f)]


def _bridge_colocated_feeder_nodes(s: NetworkState, max_m: float = _PDA_COLOCATE_M) -> int:
    """Merge duplicate GIS coordinates on the same feeder (R42/R44).

    Uses union-find then star-links each duplicate cluster to one hub — avoids
    O(n²) cliques that distort hop distances and load-side tracing."""
    max2 = max_m * max_m
    links = 0
    linked: set[tuple[str, str]] = set()

    def _link_pair(a: str, b: str) -> None:
        nonlocal links
        if b in s.adjacency.get(a, set()):
            return
        pair = (a, b) if a < b else (b, a)
        if pair in linked:
            return
        linked.add(pair)
        s.adjacency.setdefault(a, set()).add(b)
        s.adjacency.setdefault(b, set()).add(a)
        links += 1

    for feeder in _feeders_for_mesh_bridges(s):
        keys = s._feeder_keys.get(feeder, [])
        if len(keys) < 2:
            continue
        parent = {k: k for k in keys}

        def find(k: str) -> str:
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        def unite(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i, a in enumerate(keys):
            ax, ay = s.node_xy[a]
            for b in keys[i + 1:]:
                bx, by = s.node_xy[b]
                if (ax - bx) ** 2 + (ay - by) ** 2 <= max2:
                    unite(a, b)

        groups: dict[str, list[str]] = defaultdict(list)
        for k in keys:
            groups[find(k)].append(k)

        for members in groups.values():
            if len(members) < 2:
                continue
            hub = min(members, key=lambda k: len(s.adjacency.get(k, set())))
            for other in members:
                if other != hub:
                    _link_pair(hub, other)
    return links


def _bridge_conductor_endpoint_gaps(
    s: NetworkState, snap_m: float = _FEEDER_STUB_BRIDGE_WIDE_M,
) -> int:
    """Wire broken conductor-chain endpoints per feeder (R42/R44).

    Links segment ends within ``snap_m`` when no switch/dropout/RC sits on either
    endpoint — covers interior chain gaps not caught by dead-end stub bridging."""
    iso = _isolation_barrier_nodes(s)
    snap2 = snap_m * snap_m
    links = 0
    linked: set[tuple[str, str]] = set()
    for feeder in _feeders_for_mesh_bridges(s):
        mesh = s._feeder_keys.get(feeder, [])
        if not mesh:
            continue
        mesh_set = set(mesh)
        endpoints: list[str] = []
        for i, keys in enumerate(s.conductor_keys):
            if str(s.conductor_wgs[i]["properties"].get("feeder", "")) != feeder:
                continue
            if keys:
                endpoints.extend((keys[0], keys[-1]))
        seen_ep: set[str] = set()
        for k in endpoints:
            if k in seen_ep or k not in mesh_set or k in iso:
                continue
            seen_ep.add(k)
            x, y = s.node_xy[k]
            best: tuple[float, str] | None = None
            for other in mesh:
                if other == k or other in iso:
                    continue
                if other in s.adjacency.get(k, set()):
                    continue
                ox, oy = s.node_xy[other]
                d2 = (x - ox) ** 2 + (y - oy) ** 2
                if d2 > snap2:
                    continue
                if best is None or d2 < best[0]:
                    best = (d2, other)
            if not best:
                continue
            a, b = k, best[1]
            pair = (a, b) if a < b else (b, a)
            if pair in linked:
                continue
            linked.add(pair)
            s.adjacency.setdefault(a, set()).add(b)
            s.adjacency.setdefault(b, set()).add(a)
            links += 1
    return links


def _bridge_feeder_stub_gaps(s: NetworkState) -> int:
    """Wire GIS-near stub endpoints onto each feeder's mesh (R40/R41/R44).

    Connects dead-end conductor nodes within ``_LATERAL_SNAP_M`` (then a wider
    second pass) when neither endpoint carries a switch, dropout, or recloser."""
    iso = _isolation_barrier_nodes(s)
    snap2 = _LATERAL_SNAP_M * _LATERAL_SNAP_M
    links = 0
    linked: set[tuple[str, str]] = set()
    for feeder in _feeders_for_mesh_bridges(s):
        mesh = s._feeder_keys.get(feeder, [])
        if not mesh:
            continue
        main_taps = [
            k for k in mesh
            if sum(
                1 for nb in s.adjacency.get(k, set())
                if s.node_feeder.get(nb) == feeder
            ) >= 3
        ]
        search_nodes = main_taps if main_taps else mesh
        for k in _feeder_endpoint_nodes(s, feeder):
            if k in iso:
                continue
            x, y = s.node_xy[k]
            best: tuple[float, str] | None = None
            for other in search_nodes:
                if other == k or other in iso:
                    continue
                if other in s.adjacency.get(k, set()):
                    continue
                ox, oy = s.node_xy[other]
                d2 = (x - ox) ** 2 + (y - oy) ** 2
                if d2 > snap2:
                    continue
                if best is None or d2 < best[0]:
                    best = (d2, other)
            if not best:
                for other in mesh:
                    if other == k or other in iso:
                        continue
                    if other in s.adjacency.get(k, set()):
                        continue
                    ox, oy = s.node_xy[other]
                    d2 = (x - ox) ** 2 + (y - oy) ** 2
                    if d2 > snap2:
                        continue
                    if best is None or d2 < best[0]:
                        best = (d2, other)
            if not best:
                continue
            a, b = k, best[1]
            pair = (a, b) if a < b else (b, a)
            if pair in linked:
                continue
            linked.add(pair)
            s.adjacency.setdefault(a, set()).add(b)
            s.adjacency.setdefault(b, set()).add(a)
            links += 1

    # Second pass — wider snap for remaining chain gaps.
    wide2 = _FEEDER_STUB_BRIDGE_WIDE_M * _FEEDER_STUB_BRIDGE_WIDE_M
    for feeder in _feeders_for_mesh_bridges(s):
        mesh = s._feeder_keys.get(feeder, [])
        if not mesh:
            continue
        for k in _feeder_endpoint_nodes(s, feeder):
            if k in iso:
                continue
            x, y = s.node_xy[k]
            best: tuple[float, str] | None = None
            for other in mesh:
                if other == k or other in iso:
                    continue
                if other in s.adjacency.get(k, set()):
                    continue
                ox, oy = s.node_xy[other]
                d2 = (x - ox) ** 2 + (y - oy) ** 2
                if d2 <= snap2 or d2 > wide2:
                    continue
                if best is None or d2 < best[0]:
                    best = (d2, other)
            if not best:
                continue
            a, b = k, best[1]
            pair = (a, b) if a < b else (b, a)
            if pair in linked:
                continue
            linked.add(pair)
            s.adjacency.setdefault(a, set()).add(b)
            s.adjacency.setdefault(b, set()).add(a)
            links += 1
    return links


def _bridge_conductor_intra_segment_links(s: NetworkState) -> int:
    """Ensure consecutive vertices in each GIS conductor chain are graph-linked (R45).

    ``conducps.json`` sometimes omits adjacency between keys on the same
    LineString; without these links, load-side traces stop before the physical
    line end (e.g. PDA04F-044 lateral)."""
    links = 0
    linked: set[tuple[str, str]] = set()
    for keys in s.conductor_keys:
        for j in range(len(keys) - 1):
            a, b = keys[j], keys[j + 1]
            if b in s.adjacency.get(a, set()):
                continue
            pair = (a, b) if a < b else (b, a)
            if pair in linked:
                continue
            linked.add(pair)
            s.adjacency.setdefault(a, set()).add(b)
            s.adjacency.setdefault(b, set()).add(a)
            links += 1
    return links


def _feeder_connected_components(s: NetworkState, feeder: str) -> list[set[str]]:
    """Connected components of the conductor graph restricted to ``feeder``."""
    remaining = set(s._feeder_keys.get(feeder, []))
    components: list[set[str]] = []
    while remaining:
        start = next(iter(remaining))
        comp: set[str] = {start}
        queue: deque[str] = deque([start])
        remaining.discard(start)
        while queue:
            cur = queue.popleft()
            for nb in s.adjacency.get(cur, set()):
                if s.node_feeder.get(nb) != feeder or nb not in remaining:
                    continue
                remaining.discard(nb)
                comp.add(nb)
                queue.append(nb)
        components.append(comp)
    return components


def _bridge_feeder_component_islands(
    s: NetworkState, max_m: float = _FEEDER_STUB_BRIDGE_WIDE_M,
) -> int:
    """Join isolated feeder components when GIS gap ≤ ``max_m`` and no iso device (R44)."""
    iso = _isolation_barrier_nodes(s)
    max2 = max_m * max_m
    links = 0
    linked: set[tuple[str, str]] = set()

    for feeder in _feeders_for_mesh_bridges(s):
        components = _feeder_connected_components(s, feeder)
        if len(components) <= 1:
            continue
        main = max(components, key=len)
        islands = [c for c in components if c is not main]
        for comp in islands:
            best: tuple[float, str, str] | None = None
            for a in comp:
                if a in iso:
                    continue
                ax, ay = s.node_xy[a]
                for b in main:
                    if b in iso:
                        continue
                    d2 = (ax - s.node_xy[b][0]) ** 2 + (ay - s.node_xy[b][1]) ** 2
                    if d2 > max2:
                        continue
                    if best is None or d2 < best[0]:
                        best = (d2, a, b)
            if not best:
                continue
            a, b = best[1], best[2]
            pair = (a, b) if a < b else (b, a)
            if pair in linked:
                continue
            linked.add(pair)
            s.adjacency.setdefault(a, set()).add(b)
            s.adjacency.setdefault(b, set()).add(a)
            links += 1
    return links


def _bridge_kua_tie_feed_stubs(s: NetworkState) -> int:
    """Wire GIS-disconnected KUA spur islands to the main mesh (R32).

    Remote tie-feed CBs (e.g. KUA07VB) often snap onto a short spur that is
    not connected to the rest of the feeder in ``conducps.json``."""
    links = 0
    for feeder in s.feeder_edge_count:
        if not feeder.startswith("KUA"):
            continue
        components = _feeder_connected_components(s, feeder)
        if len(components) <= 1:
            continue
        main = max(components, key=len)
        cb_nodes = {
            s.cb_node[fid]
            for fid in s.feeder_cbs.get(feeder, set())
            if fid in s.cb_node
        }
        for comp in components:
            if comp is main or not (cb_nodes & comp):
                continue
            best: tuple[float, str, str] | None = None
            for a in comp:
                ax, ay = s.node_xy[a]
                for b in main:
                    d = math.hypot(ax - s.node_xy[b][0], ay - s.node_xy[b][1])
                    if best is None or d < best[0]:
                        best = (d, a, b)
            if not best or best[0] > _KUA_STUB_BRIDGE_MAX_M:
                continue
            a, b = best[1], best[2]
            s.adjacency.setdefault(a, set()).add(b)
            s.adjacency.setdefault(b, set()).add(a)
            links += 1
    return links


def _feeder_grid_interconnect_nodes(s: NetworkState, feeder: str) -> list[str]:
    """Graph nodes of cross-feeder interconnect switches touching ``feeder``."""
    out: list[str] = []
    seen: set[str] = set()
    for node in s.kua_pda_boundary_by_feeder.get(feeder, ()):
        if node not in seen:
            seen.add(node)
            out.append(node)
    for fid in s.interconnect_switch_ids:
        node = s.switch_node.get(fid)
        if not node or node in seen:
            continue
        props = next(
            (sw["properties"] for sw in s.switches if sw["properties"]["id"] == fid),
            {},
        )
        sw_f = str(props.get("feeder", "")).strip()
        feeder2 = str(props.get("feeder2", "")).strip()
        involved = {sw_f, feeder2} - {""}
        involved |= {
            s.node_feeder.get(nb, "")
            for nb in s.adjacency.get(node, set())
        } - {""}
        if feeder not in involved:
            continue
        seen.add(node)
        out.append(node)
    return out


def _interconnect_graph_nodes(s: NetworkState) -> frozenset[str]:
    return frozenset(
        s.switch_node[fid]
        for fid in s.interconnect_switch_ids
        if fid in s.switch_node
    )


def _is_kua_pda_boundary_hop(s: NetworkState, cur: str, nb: str) -> bool:
    """True when ``cur``/``nb`` sit on opposite sides of a KUA↔PDA mesh join (R38)."""
    f1 = s.node_feeder.get(cur, "")
    f2 = s.node_feeder.get(nb, "")
    return (f1.startswith("KUA") and f2.startswith("PDA")) or (
        f2.startswith("KUA") and f1.startswith("PDA")
    )


def _blocks_interconnect_cross_feeder(s: NetworkState, cur: str, nb: str) -> bool:
    """Block outage / directional walks onto a neighbour feeder at a grid tie."""
    if _is_kua_pda_boundary_hop(s, cur, nb):
        return True
    if _is_cross_feeder_tie_hop(s, cur, nb):
        return True
    ic_nodes = _interconnect_graph_nodes(s)
    if cur in ic_nodes or nb in ic_nodes:
        cur_f = s.node_feeder.get(cur, "")
        nb_f = s.node_feeder.get(nb, "")
        if cur_f and nb_f and cur_f != nb_f:
            return True
    return False


def _is_kua_feeder(feeder: str | None) -> bool:
    return bool(feeder and feeder.startswith("KUA"))


def _kua_grid_tie_nodes(s: NetworkState, feeder: str) -> frozenset[str]:
    return frozenset(_feeder_grid_interconnect_nodes(s, feeder))


def _kua_trace_may_enter(
    s: NetworkState, nb: str, feeder: str, grid_ties: frozenset[str],
) -> bool:
    """KUA directional traces stay on the feeder mesh plus grid-tie endpoints."""
    if s.node_feeder.get(nb, "") == feeder:
        return True
    return nb in grid_ties


def _kua_source_seed_node(s: NetworkState, feeder: str) -> str | None:
    """BFS seed for KUA feeders — far line end, opposite from PDA interconnect."""
    keys = s._feeder_keys.get(feeder, [])
    if not keys:
        return None
    ties = _feeder_grid_interconnect_nodes(s, feeder)
    if ties:
        ref_x = sum(s.node_xy[n][0] for n in ties) / len(ties)
        ref_y = sum(s.node_xy[n][1] for n in ties) / len(ties)
        return max(
            keys,
            key=lambda k: math.hypot(
                s.node_xy[k][0] - ref_x, s.node_xy[k][1] - ref_y,
            ),
        )
    ref = _pda_substation_hub_xy_from_state(s)
    if ref:
        return max(
            keys,
            key=lambda k: math.hypot(
                s.node_xy[k][0] - ref[0], s.node_xy[k][1] - ref[1],
            ),
        )
    return keys[len(keys) // 2]


def _tripped_isolation_rc_ids(s: NetworkState) -> frozenset[str]:
    """Reclosers opened/tripped since the pre-fault snapshot."""
    snap_rc = s.snapshot_recloser or {}
    return frozenset(
        fid for fid, st in s.recloser_status.items()
        if st == 0 and snap_rc.get(fid, 1) == 1 and fid in s.recloser_node
    )


def _compute_protection_hop_distance(
    s: NetworkState, feeder: str,
) -> dict[str, int]:
    """Topological hop from feeder source ignoring live open devices (R68).

    Protection geometry must stay stable after the protecting RC trips — PDA
    CB-hop maps otherwise omit the open RC node and the trim floor disappears."""
    if _is_kua_feeder(feeder):
        seed = _kua_source_seed_node(s, feeder)
        if not seed:
            return {}
        mesh = _kua_mesh_allowed(s, feeder)
        dist: dict[str, int] = {seed: 0}
        queue: deque[str] = deque([seed])
        while queue:
            cur = queue.popleft()
            for nb in s.adjacency.get(cur, set()):
                if nb in dist or nb not in mesh:
                    continue
                dist[nb] = dist[cur] + 1
                queue.append(nb)
        return dist

    cb_nodes = _feeder_active_cb_nodes(s, feeder)
    if not cb_nodes:
        return {}
    mesh = _feeder_mesh_nodes(s, feeder)
    dist: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque((n, 0) for n in cb_nodes)
    while queue:
        cur, d = queue.popleft()
        if cur in dist or cur not in mesh:
            continue
        dist[cur] = d
        for nb in s.adjacency.get(cur, set()):
            if nb in dist or nb not in mesh:
                continue
            if _blocks_interconnect_cross_feeder(s, cur, nb):
                continue
            if _is_cross_feeder_tie_hop(s, cur, nb):
                continue
            queue.append((nb, d + 1))
    return dist


def _feeder_protection_hop_map(s: NetworkState, feeder: str) -> dict[str, int]:
    """Hop from the feeder source — lower hop = closer to CB / PDA-side seed."""
    if not feeder:
        return {}
    return _cc_get(
        s, f"prot_hops_{feeder}",
        lambda: _compute_protection_hop_distance(s, feeder),
    )


def _recloser_on_feeder(s: NetworkState, fid: str, feeder: str) -> bool:
    """True when recloser ``fid`` belongs to ``feeder`` (GIS tag or snapped node)."""
    node = s.recloser_node.get(fid)
    if not node:
        return False
    if s.node_feeder.get(node) == feeder:
        return True
    props, _ = _device_meta(s, fid)
    return str(props.get("feeder", "")) == feeder


def _upstream_reachable_to_rc(
    s: NetworkState,
    fault: str,
    rc_node: str,
    hop: dict[str, int],
    mesh: set[str],
) -> bool:
    """True when ``rc_node`` lies on a source-ward walk from ``fault`` (R68)."""
    fault_hop = hop.get(fault)
    rc_hop = hop.get(rc_node)
    if fault_hop is None or rc_hop is None or rc_hop >= fault_hop:
        return False
    if fault == rc_node:
        return True
    seen: set[str] = {fault}
    queue: deque[str] = deque([fault])
    while queue:
        cur = queue.popleft()
        for nb in s.adjacency.get(cur, set()):
            if nb in seen or nb not in mesh:
                continue
            nh = hop.get(nb)
            if nh is None or nh > fault_hop:
                continue
            if nb == rc_node:
                return True
            seen.add(nb)
            queue.append(nb)
    return False


def _protecting_recloser_ids_for_fault(
    s: NetworkState,
    fault: str,
    feeder: str,
) -> list[str]:
    """Nearest closed upstream recloser(s) protecting a load-side fault (R68).

    Among closed RCs on ``feeder`` with hop < fault hop and a source-ward path
    to the fault, pick those with the largest hop (closest to the fault)."""
    hop = _feeder_protection_hop_map(s, feeder)
    fault_hop = hop.get(fault)
    if fault_hop is None:
        return []
    mesh = (
        _kua_mesh_allowed(s, feeder) if _is_kua_feeder(feeder)
        else _feeder_mesh_nodes(s, feeder)
    )
    candidates: list[tuple[int, str]] = []
    for fid, node in s.recloser_node.items():
        if s.recloser_status.get(fid, 1) != 1:
            continue
        if not _recloser_on_feeder(s, fid, feeder):
            continue
        rc_hop = hop.get(node)
        if rc_hop is None or rc_hop >= fault_hop:
            continue
        if not _upstream_reachable_to_rc(s, fault, node, hop, mesh):
            continue
        candidates.append((rc_hop, fid))
    if not candidates:
        return []
    best_hop = max(h for h, _ in candidates)
    return sorted(fid for h, fid in candidates if h == best_hop)


def _auto_trip_protecting_reclosers(s: NetworkState) -> list[str]:
    """OPEN nearest upstream RC for each faulted feeder when fault is behind it."""
    if not s.fault_node:
        return []
    tripped: list[str] = []
    for feeder in sorted(_fault_target_feeders(s)):
        fault = _fault_node_on_feeder(s, feeder) or s.fault_node
        if not fault:
            continue
        for fid in _protecting_recloser_ids_for_fault(s, fault, feeder):
            if s.recloser_status.get(fid, 1) != 1:
                continue
            s.recloser_status[fid] = 0
            tripped.append(fid)
            for rc in s.reclosers:
                if rc["properties"].get("id") == fid:
                    rc["properties"]["status"] = 0
                    rc["properties"]["state"] = "OPEN"
                    break
    return tripped


def _recloser_is_lateral(s: NetworkState, fid: str) -> bool:
    """True for lateral / spur reclosers (GIS OPERATIONT=L)."""
    for rc in s.reclosers:
        if rc["properties"].get("id") != fid:
            continue
        props = rc["properties"]
        if str(props.get("lineKind", "")).lower() == "lateral":
            return True
        return str(props.get("operationType", "")).upper() == "L"
    props, _ = _device_meta(s, fid)
    return str(props.get("operationType", props.get("OPERATIONT", ""))).upper() == "L"


def _sourceward_reaches_target(
    s: NetworkState,
    start: str,
    target: str,
    hop: dict[str, int],
    mesh: set[str],
    *,
    min_hop: int,
) -> bool:
    """True when walking only to lower-hop neighbours can reach ``target``.

    Stops if hop falls below ``min_hop`` without hitting ``target`` — that path
    bypassed the device on the main/source corridor (R72)."""
    if start == target:
        return True
    seen: set[str] = {start}
    queue: deque[str] = deque([start])
    while queue:
        cur = queue.popleft()
        cur_hop = hop.get(cur)
        if cur_hop is None:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb not in mesh or nb in seen:
                continue
            nb_hop = hop.get(nb)
            if nb_hop is None or nb_hop >= cur_hop:
                continue
            if nb == target:
                return True
            if nb_hop < min_hop:
                continue
            seen.add(nb)
            queue.append(nb)
    return False


def _rc_load_side_island(
    s: NetworkState,
    rc_fid: str,
    feeder: str,
) -> set[str]:
    """Nodes behind a recloser on its load taps (R69/R72).

    A node is on the load side when a source-ward (strictly decreasing hop)
    walk that stays at hop ≥ RC can hit the RC — i.e. its hop-tree path to
    the CB goes through the RC.  Main-line nodes past the tap typically walk
    source-ward down the trunk without hitting the lateral RC, so they stay
    out even when mesh links share hop ≥ RC.
    """
    rc_node = s.recloser_node.get(rc_fid)
    if not rc_node:
        return set()
    hop = _feeder_protection_hop_map(s, feeder)
    rc_hop = hop.get(rc_node)
    if rc_hop is None:
        return {rc_node}
    mesh = (
        _kua_mesh_allowed(s, feeder) if _is_kua_feeder(feeder)
        else _feeder_mesh_nodes(s, feeder)
    )
    island: set[str] = {rc_node}
    for node, node_hop in hop.items():
        if node not in mesh or node == rc_node:
            continue
        if node_hop <= rc_hop:
            continue
        if _sourceward_reaches_target(
            s, node, rc_node, hop, mesh, min_hop=rc_hop,
        ):
            island.add(node)
    return island


def _open_lateral_rc_source_side(
    s: NetworkState,
    rc_status: dict[str, int] | None = None,
) -> set[str]:
    """Feeder nodes NOT on the load island of any open lateral RC (R72)."""
    rc_st = rc_status if rc_status is not None else s.recloser_status
    blocked: set[str] = set()
    for fid, st in rc_st.items():
        if st != 0 or fid not in s.recloser_node:
            continue
        if not _recloser_is_lateral(s, fid):
            continue
        props, _ = _device_meta(s, fid)
        feeder = str(props.get("feeder", "") or "")
        if not feeder:
            feeder = str(s.node_feeder.get(s.recloser_node[fid], "") or "")
        if not feeder:
            continue
        island = _rc_load_side_island(s, fid, feeder)
        mesh = (
            _kua_mesh_allowed(s, feeder) if _is_kua_feeder(feeder)
            else _feeder_mesh_nodes(s, feeder)
        )
        blocked |= mesh - island
    return blocked


def _fault_component_in_island(
    s: NetworkState, fault: str, island: set[str],
) -> set[str]:
    """Connected component of ``fault`` inside ``island``."""
    if fault not in island:
        return set()
    seen: set[str] = {fault}
    queue: deque[str] = deque([fault])
    while queue:
        cur = queue.popleft()
        for nb in s.adjacency.get(cur, set()):
            if nb in island and nb not in seen:
                seen.add(nb)
                queue.append(nb)
    return seen


def _protecting_lateral_rc_mainline_guard(s: NetworkState) -> set[str]:
    """Source-side (main-line) nodes at open protecting lateral RCs (R69).

    Outage polygons from the lateral island must not 45 m-bleed across the tap
    onto these trunk nodes — darkness stops at the RC.
    """
    if not s.fault_node:
        return set()
    guard: set[str] = set()
    snap_rc = s.snapshot_recloser or {}
    for feeder in sorted(_fault_target_feeders(s)):
        fault = _fault_node_on_feeder(s, feeder) or s.fault_node
        if not fault:
            continue
        hop = _feeder_protection_hop_map(s, feeder)
        fault_hop = hop.get(fault)
        if fault_hop is None:
            continue
        for fid, st in s.recloser_status.items():
            if st != 0 or snap_rc.get(fid, 1) != 1:
                continue
            if not _recloser_on_feeder(s, fid, feeder):
                continue
            if not _recloser_is_lateral(s, fid):
                continue
            rc_node = s.recloser_node.get(fid)
            if not rc_node:
                continue
            rc_hop = hop.get(rc_node)
            if rc_hop is None or rc_hop >= fault_hop:
                continue
            island = _rc_load_side_island(s, fid, feeder)
            for nb in s.adjacency.get(rc_node, set()):
                if nb not in island:
                    guard.add(nb)
                    # One hop further on the trunk so 45 m buffers stay off main.
                    for nb2 in s.adjacency.get(nb, set()):
                        if nb2 not in island and nb2 != rc_node:
                            guard.add(nb2)
    return guard


def _trim_zone_at_protecting_reclosers(
    s: NetworkState,
    zone: set[str],
    feeder: str,
    fault: str,
) -> set[str]:
    """Drop nodes on the source side of a tripped protecting RC (R68/R69).

    * Mainline RC: hop floor (mesh rings can bypass the open RC node).
    * Lateral RC: keep only the load-side island behind the RC — never the
      main line past the tap.
    """
    hop = _feeder_protection_hop_map(s, feeder)
    fault_hop = hop.get(fault)
    if fault_hop is None:
        return zone

    snap_rc = s.snapshot_recloser or {}
    protecting: list[tuple[int, str, str]] = []  # hop, fid, node
    for fid, st in s.recloser_status.items():
        if st != 0 or snap_rc.get(fid, 1) != 1:
            continue
        if not _recloser_on_feeder(s, fid, feeder):
            continue
        node = s.recloser_node.get(fid)
        if not node:
            continue
        rc_hop = hop.get(node)
        if rc_hop is None or rc_hop >= fault_hop:
            continue
        protecting.append((rc_hop, fid, node))
    if not protecting:
        return zone

    # Prefer the nearest upstream RC (largest hop < fault).
    protecting.sort(key=lambda item: item[0], reverse=True)
    _rh, best_fid, best_node = protecting[0]

    if _recloser_is_lateral(s, best_fid):
        island = _rc_load_side_island(s, best_fid, feeder)
        if fault in island:
            return _fault_component_in_island(s, fault, island) | {best_node}
        # Fault outside island geometry — fall back to intersection.
        return (zone & island) | {best_node, fault}

    floor_h = max(h for h, _, _ in protecting)
    rc_nodes = {node for _, _, node in protecting}
    trimmed = {
        n for n in zone
        if n == fault or hop.get(n, -1) >= floor_h
    } | rc_nodes | {fault}
    if not trimmed:
        trimmed = {fault} | rc_nodes
    return trimmed


def _kua_line_end_restoration_sectional_ids(
    s: NetworkState,
    sw_status: dict[str, int] | None = None,
) -> frozenset[str]:
    """Sectionalisers opened since snapshot for KUA line-end back-feed (R47/R49/R73).

    PDA feeders must not use this set — otherwise an isolation sectional such as
    PDA07S-12 is skipped as a colour/energization barrier and neighbour-feeder
    back-feed keeps the native GIS colour.
    """
    primary = s.fault_feeder or s.maint_feeder or ""
    if not _is_kua_feeder(primary):
        return frozenset()
    snap_sw = s.snapshot_switch or {}
    sw_st = sw_status if sw_status is not None else s.switch_status
    return frozenset(
        fid for fid in _sectionalizing_switch_ids(s)
        if sw_st.get(fid, 1) == 0
        and snap_sw.get(fid, 1) == 1
        and fid in s.switch_node
    )


def _kua_feeder_energization_ex(
    s: NetworkState,
    feeder: str,
    *,
    sw_status: dict[str, int] | None = None,
    rc_status: dict[str, int] | None = None,
    line_end_restore: bool = False,
) -> set[str]:
    """Energized nodes when KUA supply is assumed from the far line end only.

    Used for KUA fault switching plans so the live side is always traced
    from the remote end — not from the PDA-grid interconnect direction.

    When ``line_end_restore`` is True, sectional switches opened for line-end
    back-feed (e.g. PDA10S-13) do not block the trace — they were opened to
    allow load-side restoration from the remote end, not to isolate it."""
    seed = _kua_source_seed_node(s, feeder)
    if not seed:
        return set()
    sw_st = sw_status if sw_status is not None else s.switch_status
    rc_st = rc_status if rc_status is not None else s.recloser_status
    skip_sectionals = (
        _kua_line_end_restoration_sectional_ids(s, sw_st)
        if line_end_restore else frozenset()
    )
    removed: set[str] = set()
    if s.fault_node:
        removed.add(s.fault_node)
    for fid, st in sw_st.items():
        if st == 0 and fid in s.switch_node:
            if fid in s.interconnect_switch_ids:
                continue
            if fid in s.rc_bypass_switch_ids:
                continue  # open bypass parallel to closed RC — main path still conducts (R53)
            if fid in skip_sectionals:
                continue
            removed.add(s.switch_node[fid])
    for fid, st in rc_st.items():
        if st == 0 and fid in s.recloser_node:
            removed.add(s.recloser_node[fid])
    hop = _kua_restoration_hop_from_seed(s, feeder, sw_st)
    if line_end_restore and hop:
        cap_hops = [
            hop[s.switch_node[fid]]
            for fid in skip_sectionals
            if fid in s.switch_node and s.switch_node[fid] in hop
        ]
        floor_h = max(cap_hops) if cap_hops else 0
        mesh = _kua_mesh_allowed(s, feeder)
        remote_seeds = {
            n for n, h in hop.items()
            if h >= floor_h and n not in removed and n in mesh
        }
        if not remote_seeds:
            remote_seeds.add(seed)
        energized = set(remote_seeds)
        queue: deque[str] = deque(remote_seeds)
        while queue:
            cur = queue.popleft()
            for nb in s.adjacency.get(cur, set()):
                if nb in removed or nb in energized or nb not in mesh:
                    continue
                nb_h = hop.get(nb)
                if nb_h is None or nb_h < floor_h:
                    continue
                energized.add(nb)
                queue.append(nb)
        for fid in skip_sectionals:
            node = s.switch_node.get(fid)
            if node:
                energized.add(node)
        return energized
    # R67: stay on the KUA mesh — unbounded adjacency would paint every PDA feeder.
    mesh = _kua_mesh_allowed(s, feeder)
    if seed not in mesh:
        return set()
    energized: set[str] = {seed}
    queue: deque[str] = deque([seed])
    while queue:
        cur = queue.popleft()
        for nb in s.adjacency.get(cur, set()):
            if nb in removed or nb in energized or nb not in mesh:
                continue
            energized.add(nb)
            queue.append(nb)
    return energized


def _kua_backfeed_barrier_hop_cap(
    s: NetworkState,
    hop: dict[str, int],
    sw_status: dict[str, int] | None = None,
) -> int | None:
    """Nearest open RC/sectional hop that caps interconnect back-feed (R67)."""
    sw_st = sw_status if sw_status is not None else s.switch_status
    barriers: list[int] = []
    for fid in _tripped_isolation_rc_ids(s):
        node = s.recloser_node.get(fid)
        if node and node in hop:
            barriers.append(hop[node])
    snap_sw = s.snapshot_switch or {}
    for fid in _sectionalizing_switch_ids(s):
        if sw_st.get(fid, 1) == 0 and snap_sw.get(fid, 1) == 1:
            node = s.switch_node.get(fid)
            if node and node in hop:
                barriers.append(hop[node])
    return min(barriers) if barriers else None


def _kua_tie_to_rc_corridor(
    s: NetworkState,
    feeder: str,
    start: str,
    hop: dict[str, int],
    removed: set[str],
) -> set[str]:
    """Mesh corridor from a closed interconnect tie up to open isolation barriers (R61/R67).

    Walks the graph toward the nearest open RC/sectional hop cap — not a
    directional hop-band — so ring paths and laterals are included."""
    rc_nodes = {
        s.recloser_node[rc_fid]
        for rc_fid in _tripped_isolation_rc_ids(s)
        if rc_fid in s.recloser_node
    }
    cap = _kua_backfeed_barrier_hop_cap(s, hop)
    mesh = _kua_mesh_allowed(s, feeder)
    corridor: set[str] = {start}
    queue: deque[str] = deque([start])
    while queue:
        cur = queue.popleft()
        for nb in s.adjacency.get(cur, set()):
            if nb in removed or nb in corridor or nb in rc_nodes:
                continue
            if nb not in mesh:
                continue
            nh = hop.get(nb)
            if cap is not None and (nh is None or nh > cap):
                continue
            corridor.add(nb)
            queue.append(nb)
    return corridor


def _kua_backfeed_trace_removed(
    s: NetworkState,
    sw_status: dict[str, int] | None = None,
) -> set[str]:
    """Barriers for PDA interconnect back-feed corridor tracing."""
    sw_st = sw_status if sw_status is not None else s.switch_status
    removed: set[str] = set()
    if s.fault_node:
        removed.add(s.fault_node)
    for fid in _tripped_isolation_rc_ids(s):
        node = s.recloser_node.get(fid)
        if node:
            removed.add(node)
    for fid in s.interconnect_switch_ids:
        if sw_st.get(fid, 1) == 0 and fid in s.switch_node:
            removed.add(s.switch_node[fid])
    for fid in _sectionalizing_switch_ids(s):
        if sw_st.get(fid, 1) == 0 and fid in s.switch_node:
            # R66: every open sectional is a hard barrier for interconnect
            # back-feed (isolation S-13 must stop PDA10S-08 feed into S-13↔S-14).
            removed.add(s.switch_node[fid])
    return removed


def _kua_line_end_high_hop_nodes(
    s: NetworkState,
    feeder: str,
    line_on: set[str],
    hop: dict[str, int],
) -> set[str]:
    """Line-end restoration nodes at/line-end-ward of open sectionalisers (R61)."""
    sectionals = _kua_line_end_restoration_sectional_ids(s)
    cap_hops = [
        hop[s.switch_node[fid]]
        for fid in sectionals
        if fid in s.switch_node and s.switch_node[fid] in hop
    ]
    if not cap_hops:
        return line_on
    floor_h = max(cap_hops)
    high = {n for n in line_on if hop.get(n, 0) >= floor_h}
    for fid in sectionals:
        node = s.switch_node.get(fid)
        if node and hop.get(node, -1) >= floor_h:
            high.add(node)
    return high


def _live_supply_removed_nodes(s: NetworkState) -> set[str]:
    """Open switches/reclosers that block supply tracing on the live map."""
    removed: set[str] = set()
    if s.fault_node:
        removed.add(s.fault_node)
    cut = _live_display_cut_ids(s)
    restore_sectionals = _kua_line_end_restoration_sectional_ids(s)
    for fid, st in s.switch_status.items():
        if st == 0 and fid in s.switch_node and fid in cut:
            if fid in restore_sectionals or fid in s.rc_bypass_switch_ids:
                continue
            removed.add(s.switch_node[fid])
    for fid, st in s.recloser_status.items():
        if st == 0 and fid in s.recloser_node:
            removed.add(s.recloser_node[fid])
    return removed


def _kua_pda_backfeed_paint_zone(
    s: NetworkState,
    primary: str,
    *,
    hop: dict[str, int],
    removed: set[str] | None = None,
) -> set[str]:
    """KUA mesh nodes allowed to show PDA interconnect supply (tie → open RC only)."""
    trace_removed = removed if removed is not None else _kua_backfeed_trace_removed(s)
    snap_sw = s.snapshot_switch or {}
    zone: set[str] = set()
    for fid in s.interconnect_switch_ids:
        if s.switch_status.get(fid, 1) != 1 or snap_sw.get(fid, 1) != 0:
            continue
        props, _ = _device_meta(s, fid)
        f1 = str(props.get("feeder", ""))
        f2 = str(props.get("feeder2", ""))
        if primary not in (f1, f2):
            continue
        tie_node = s.switch_node.get(fid)
        if tie_node:
            zone |= _kua_tie_to_rc_corridor(
                s, primary, tie_node, hop, trace_removed,
            )
    rc_hops = [
        hop[s.recloser_node[rc_fid]]
        for rc_fid in _tripped_isolation_rc_ids(s)
        if rc_fid in s.recloser_node and s.recloser_node[rc_fid] in hop
    ]
    cap = _kua_backfeed_barrier_hop_cap(s, hop)
    if cap is not None:
        zone = {n for n in zone if n in hop and hop[n] <= cap}
    elif rc_hops:
        cap_rc = min(rc_hops)
        zone = {n for n in zone if n in hop and hop[n] <= cap_rc}
    return zone


def _kua_interconnect_backfeed_nodes(
    s: NetworkState,
    feeder: str,
    *,
    sw_status: dict[str, int] | None = None,
) -> set[str]:
    """Nodes energised from closed KUA↔PDA interconnect ties (PDA02S-08 …).

    Meshed rings bypass open reclosers when only the RC graph node is removed.
    Back-feed is therefore capped at the tie hop — it cannot continue source-
    ward toward the KUA line-end past an open isolation RC."""
    snap_sw = s.snapshot_switch or {}
    sw_st = sw_status if sw_status is not None else s.switch_status
    # Restoration hop keeps open sectionals visible for the back-feed hop cap (R67).
    hop = _kua_restoration_hop_from_seed(s, feeder, sw_st)
    if not hop:
        return set()

    removed = _kua_backfeed_trace_removed(s, sw_st)

    energized: set[str] = set()
    for fid in s.interconnect_switch_ids:
        if sw_st.get(fid, 1) != 1 or snap_sw.get(fid, 1) != 0:
            continue
        props, _ = _device_meta(s, fid)
        f1 = str(props.get("feeder", ""))
        f2 = str(props.get("feeder2", ""))
        if feeder not in (f1, f2):
            continue
        start = s.switch_node.get(fid)
        if not start or start in removed:
            continue
        corridor = _kua_tie_to_rc_corridor(s, feeder, start, hop, removed)
        energized |= corridor
    return energized


def _plan_energization_for_context(
    s: NetworkState, plan_open: set[str], primary_feeder: str,
) -> set[str]:
    """Simulate energization after opening devices in a switching plan."""
    sw_status = dict(s.switch_status)
    rc_status = dict(s.recloser_status)
    for fid in plan_open:
        if fid in sw_status:
            sw_status[fid] = 0
        if fid in rc_status:
            rc_status[fid] = 0
    if _is_kua_feeder(primary_feeder):
        return _kua_feeder_energization_ex(
            s, primary_feeder, sw_status=sw_status, rc_status=rc_status,
        )
    cut = frozenset(plan_open) | _sectionalizing_switch_ids(s)
    energized = compute_energization_ex(
        s.adjacency, s.node_feeder,
        s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
        s.switch_node, sw_status, s.fault_node,
        cut,
        s.recloser_node, rc_status,
    )
    energized -= _open_recloser_forced_dark(s, rc_status)
    return energized


def _active_feeders_with_cb(s: NetworkState) -> list[str]:
    """Feeders with conductor mesh and at least one source CB."""
    return sorted(
        f for f in s.feeder_edge_count
        if s.feeder_edge_count.get(f, 0) > 0 and s.feeder_cbs.get(f)
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
    seed at the far line end — opposite from the PDA-grid interconnect — so
    energization direction differs from PDA feeders."""
    if geo_dist <= _CB_MAX_GEO_SNAP:
        node, _ = snap_cb_to_feeder(s, x, y, supply)
        return node
    if supply.startswith("KUA"):
        kua_seed = _kua_source_seed_node(s, supply)
        if kua_seed:
            return kua_seed
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
    rc_gis_points = _recloser_gis_points(all_recloser)
    sw_skipped_disabled = 0
    for feat in all_dof:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        props = feat.get("properties") or {}
        x, y = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        if not gis_switch_loadable(props, xy=(x, y), rc_points=rc_gis_points):
            sw_skipped_disabled += 1
            continue
        fid   = str(props.get("FACILITYID", ""))
        if not fid:
            continue
        gis_props = {**props, "feeder": str(props.get("FEEDERID", "") or "").strip()}
        rc_bypass = is_recloser_bypass_switch(gis_props, (x, y), rc_gis_points)
        status  = _gis_switch_status(props, rc_bypass=rc_bypass)
        # R6: snap into the switch's declared feeder first; fall back to
        # the global tree only if FEEDERID is missing or that feeder has
        # no nodes yet.
        decl_feeder = str(props.get("FEEDERID", "")) or None
        nearest = find_nearest_in_feeder(s, x, y, decl_feeder)
        if not nearest:
            continue
        feeder  = decl_feeder or s.node_feeder.get(nearest, "UNK")
        feeder2 = str(props.get("FEEDERID2", "") or "").strip()
        gis_props = {**props, "feeder": feeder, "feeder2": feeder2}
        interconnect = is_grid_interconnect_switch(gis_props)
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
                "id": fid, "feeder": feeder, "feeder2": feeder2,
                "location": str(props.get("LOCATION", "")),
                "state": "CLOSE" if status == 1 else "OPEN", "status": status, "kind": kind,
                "deviceClass": device,
                "isInterconnect": interconnect,
                "isRcBypass": rc_bypass,
                "presentPos": int(props.get("PRESENTPOS", 1)),
            },
        })
        s.switch_node[fid]   = nearest
        s.switch_status[fid] = status
        if device == "dropout":
            s.switch_customers[fid] = int(props.get("NUMBEROFUS", 0) or 0)
        if device != "dropout":
            s.tie_switch_ids.add(fid)
            if interconnect:
                s.interconnect_switch_ids.add(fid)
            if rc_bypass:
                s.rc_bypass_switch_ids.add(fid)

    _register_kua_pda_boundary_markers(s, all_dof)

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
    s.snapshot_recloser = dict(s.recloser_status)

    # Reclosers
    rc_skipped_disabled = 0
    for feat in all_recloser:
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        props = feat.get("properties") or {}
        if not gis_device_enabled(props):
            rc_skipped_disabled += 1
            continue
        x, y  = float(geom["coordinates"][0]), float(geom["coordinates"][1])
        lon, lat = to_wgs(x, y)
        rc_id = str(props.get("FACILITYID", props.get("TAG", "RC")))
        rc_pos = int(props.get("NORMALPOSI", props.get("PRESENTPOS", 1)) or 1)
        rc_cust = int(props.get("NUMBEROFUS", 0) or 0)
        rc_op = str(props.get("OPERATIONT", "L")).upper()
        s.recloser_status[rc_id] = 1 if rc_pos != 0 else 0
        s.recloser_customers[rc_id] = rc_cust
        s.reclosers.append({
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": rc_id,
                "feeder": str(props.get("FEEDERID", "UNK")),
                "location": str(props.get("LOCATION", "")),
                "status": s.recloser_status[rc_id],
                "state": "CLOSE" if s.recloser_status[rc_id] == 1 else "OPEN",
                "customers": rc_cust,
                "operationType": rc_op,
                "lineKind": "mainline" if rc_op in ("R", "M") else "lateral",
            },
        })

    stub_links = _bridge_kua_tie_feed_stubs(s)
    if stub_links:
        print(
            f"  KUA stub bridges: {stub_links:,} virtual links (tie-feed CB gaps)",
            flush=True,
        )

    intra_links = _bridge_conductor_intra_segment_links(s)
    if intra_links:
        print(f"  chain links   : {intra_links:,} virtual links (in-segment keys)", flush=True)

    tap_links = _link_protection_device_taps(s)
    if tap_links:
        print(f"  lateral taps : {tap_links:,} virtual links (recloser/dropout)", flush=True)

    colocate_links = _bridge_colocated_feeder_nodes(s)
    if colocate_links:
        print(f"  mesh colocate  : {colocate_links:,} virtual links (duplicate coords)", flush=True)

    stub_links = _bridge_feeder_stub_gaps(s)
    if stub_links:
        print(f"  feeder stubs  : {stub_links:,} virtual links (GIS tap gaps)", flush=True)

    chain_links = _bridge_conductor_endpoint_gaps(s)
    if chain_links:
        print(f"  chain gaps    : {chain_links:,} virtual links (segment endpoints)", flush=True)

    island_links = _bridge_feeder_component_islands(s)
    if island_links:
        print(f"  mesh islands  : {island_links:,} virtual links (component joins)", flush=True)

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

    if sw_skipped_disabled or rc_skipped_disabled:
        print(
            f"  GIS disabled (skipped): switches {sw_skipped_disabled:,}"
            f" · reclosers {rc_skipped_disabled:,}",
            flush=True,
        )
    print(f"  conductors : {len(s.conductor_keys):,}", flush=True)
    print(f"  nodes      : {len(s.nodes):,}", flush=True)
    n_do = sum(1 for sw in s.switches if sw["properties"].get("deviceClass") == "dropout")
    n_sw = len(s.switches) - n_do
    n_open, _ = tie_switch_counts(s)
    n_ic = len(s.interconnect_switch_ids)
    n_bypass = len(s.rc_bypass_switch_ids)
    print(
        f"  tie switches: {n_sw:,} · grid interconnect: {n_ic:,} · "
        f"RC bypass: {n_bypass:,} · "
        f"KUA↔PDA boundaries: {len(s.kua_pda_boundary_ids):,} · "
        f"dropouts (F): {n_do:,} · open: {n_open:,}",
        flush=True,
    )
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
    cut_switch_ids: set[str] | frozenset[str] | None = None,
    recloser_node:  dict[str, str] | None = None,
    recloser_status: dict[str, int] | None = None,
) -> set[str]:
    """Core BFS energization. R1: a feeder without any CB is *not* source-off.

    ``cut_switch_ids``: open switches that block flow (tie switches only in
    production).  Pass ``frozenset()`` to ignore all switch cuts.
    Open reclosers (``recloser_status``=0) always sectionalise when supplied."""
    removed: set[str] = set()
    if fault_node:
        removed.add(fault_node)
    for fid, st in switch_status.items():
        if st == 0 and fid in switch_node:
            if cut_switch_ids is None or fid in cut_switch_ids:
                removed.add(switch_node[fid])
    rc_node   = recloser_node or {}
    rc_status = recloser_status or {}
    for fid, st in rc_status.items():
        if st == 0 and fid in rc_node:
            removed.add(rc_node[fid])

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


def _any_isolation_device_open(s: NetworkState) -> bool:
    if any(st == 0 for st in s.recloser_status.values()):
        return True
    return bool(open_tie_switch_nodes(s))


def _energization_ex_call(s: NetworkState, rc_status: dict[str, int] | None = None) -> set[str]:
    return compute_energization_ex(
        s.adjacency, s.node_feeder,
        s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
        s.switch_node, s.switch_status, s.fault_node,
        _sectionalizing_switch_ids(s),
        s.recloser_node, rc_status if rc_status is not None else s.recloser_status,
    )


def _downstream_island(s: NetworkState, start: str, barrier: set[str]) -> set[str]:
    """Nodes reachable from ``start`` without entering ``barrier``."""
    all_n = set(s.adjacency.keys())
    return bfs_island(start, all_n, s.adjacency, barrier)


def _open_recloser_forced_dark(
    s: NetworkState,
    rc_status: dict[str, int] | None = None,
) -> set[str]:
    """Nodes that must be dark while a recloser is open (incl. dead-end laterals).

    Lateral RCs (R72): only the load-side island is forced dark — never the
    CB/mainline component (mesh around the RC node would otherwise darken the
    whole feeder)."""
    rc_st = rc_status if rc_status is not None else s.recloser_status
    forced: set[str] = set()
    for fid, st in rc_st.items():
        if st != 0 or fid not in s.recloser_node:
            continue
        rc = s.recloser_node[fid]
        if _recloser_is_lateral(s, fid):
            props, _ = _device_meta(s, fid)
            feeder = str(props.get("feeder", "") or "")
            if not feeder:
                feeder = str(s.node_feeder.get(rc, "") or "")
            if feeder:
                island = _rc_load_side_island(s, fid, feeder)
                energized = _energization_ex_call(s, rc_st)
                forced |= island & energized
            continue
        rc_closed = dict(rc_st)
        rc_closed[fid] = 1
        sup_if_closed = _energization_ex_call(s, rc_closed)
        energized = _energization_ex_call(s, rc_st)
        for nb in s.adjacency.get(rc, set()):
            isl = _downstream_island(s, nb, {rc})
            if not isl:
                continue
            if isl & sup_if_closed:
                wrongly_on = isl & energized
                if wrongly_on:
                    forced |= wrongly_on
            else:
                forced |= isl
    return forced


def compute_energization(s: NetworkState, *, planning: bool = False) -> set[str]:
    """Physical topology — open tie switches and open reclosers sectionalise."""
    if not planning:
        return _cc_get(
            s, "phys",
            lambda: _energization_ex_call(s) - _open_recloser_forced_dark(s),
        )
    return _energization_ex_call(s)


def compute_logical_energization(s: NetworkState) -> set[str]:
    """Ring/mesh model — every closed source CB feeds; open ties do not cut.

    Both ends of a line are assumed supplied from neighbouring sources so
    unrelated sections stay energised for display and switching-plan work."""
    return compute_energization_ex(
        s.adjacency, s.node_feeder,
        s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
        {}, {}, s.fault_node, frozenset(),
    )


def _plan_energization(s: NetworkState, plan_open: set[str]) -> set[str]:
    """Physical energization with switches/reclosers opened in the plan."""
    sw_status = dict(s.switch_status)
    rc_status = dict(s.recloser_status)
    for fid in plan_open:
        if fid in sw_status:
            sw_status[fid] = 0
        if fid in rc_status:
            rc_status[fid] = 0
    cut = frozenset(plan_open) | _sectionalizing_switch_ids(s)
    energized = compute_energization_ex(
        s.adjacency, s.node_feeder,
        s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
        s.switch_node, sw_status, s.fault_node,
        cut,
        s.recloser_node, rc_status,
    )
    energized -= _open_recloser_forced_dark(s, rc_status)
    return energized


def compute_display_energization(s: NetworkState) -> set[str]:
    """Logical ring pre-switching; live supply after restoration back-feed (R49)."""
    if _display_restoration_live(s):
        return compute_live_energization(s)
    return _cc_get(s, "logical_on", lambda: compute_logical_energization(s))


def _segment_barred_by_open_device(
    s: NetworkState,
    keys: list[str],
    *,
    ignore_switch_ids: frozenset[str] | None = None,
    ignore_recloser_ids: frozenset[str] | None = None,
) -> bool:
    """True when an open switch/recloser sits on a conductor segment endpoint."""
    ignore_sw = ignore_switch_ids or frozenset()
    ignore_rc = ignore_recloser_ids or frozenset()
    key_set = set(keys)
    for fid, st in s.switch_status.items():
        if st == 0 and fid not in ignore_sw:
            node = s.switch_node.get(fid)
            if node and node in key_set:
                return True
    for fid, st in s.recloser_status.items():
        if st == 0 and fid not in ignore_rc:
            node = s.recloser_node.get(fid)
            if node and node in key_set:
                return True
    return False


def _display_barred_ignore_recloser_ids(s: NetworkState) -> frozenset[str]:
    """Open reclosers always sectionalise map display — never bypassed (R59).

    RC bypass *switches* are handled in ``_display_barred_ignore_switch_ids``."""
    return frozenset()


def _display_barred_ignore_switch_ids(s: NetworkState) -> frozenset[str]:
    """Open switches ignored when painting conductors during KUA restoration (R53).

    RC bypass blades stay open in GIS but must not force the whole feeder dark;
    line-end restoration sectionalisers are open for back-feed, not a map barrier
    on the load-side past them."""
    if not _display_restoration_live(s):
        return frozenset()
    ignore = set(s.rc_bypass_switch_ids)
    ignore |= _kua_line_end_restoration_sectional_ids(s)
    return frozenset(ignore)


def _extend_energized_through_conductors(
    s: NetworkState, energized: set[str],
) -> set[str]:
    """Promote energization across conductor spans with no open device at endpoints."""
    bar_ignore = _display_barred_ignore_switch_ids(s)
    bar_rc = _display_barred_ignore_recloser_ids(s)
    extended = set(energized)
    changed = True
    while changed:
        changed = False
        for keys in s.conductor_keys:
            if not keys or _segment_barred_by_open_device(
                s, keys,
                ignore_switch_ids=bar_ignore,
                ignore_recloser_ids=bar_rc,
            ):
                continue
            if any(k in extended for k in keys):
                before = len(extended)
                extended.update(keys)
                if len(extended) > before:
                    changed = True
    return extended


def _extend_supply_map_through_conductors(
    s: NetworkState,
    supply: dict[str, str],
    energized: set[str],
) -> dict[str, str]:
    """Paint supply feeder colour across conductor spans (R55/R60)."""
    bar_sw = _display_barred_ignore_switch_ids(s)
    bar_rc = _display_barred_ignore_recloser_ids(s)
    primary = s.fault_feeder or s.maint_feeder or ""
    back_sources = set(_active_backfeed_source_feeders(s))
    back_paint_zone: set[str] = set()
    if _display_restoration_live(s) and back_sources:
        if _is_kua_feeder(primary):
            hop = _kua_feeder_hop_from_seed(s, primary)
            if hop:
                back_paint_zone = _kua_pda_backfeed_paint_zone(
                    s, primary, hop=hop, removed=_kua_backfeed_trace_removed(s),
                )
        else:
            # R71: PDA↔PDA restored corridor (e.g. PDA05→PDA07 past closed tie).
            back_paint_zone = _pda_interconnect_restored_nodes(s, energized)
    out = dict(supply)
    changed = True
    while changed:
        changed = False
        for keys in s.conductor_keys:
            if not keys:
                continue
            if _segment_barred_by_open_device(
                s, keys, ignore_switch_ids=bar_sw, ignore_recloser_ids=bar_rc,
            ):
                continue
            srcs = {out[k] for k in keys if k in out}
            if len(srcs) != 1:
                continue
            src = next(iter(srcs))
            if not any(k in energized for k in keys):
                continue
            if src in back_sources and any(
                str(s.node_feeder.get(k, "")).startswith("KUA") for k in keys
            ):
                for k in keys:
                    if k not in out and k in back_paint_zone:
                        out[k] = src
                        changed = True
                continue
            # R71: PDA back-feed colour may extend onto the faulted feeder GIS
            # within the restored interconnect corridor.
            if src in back_sources and back_paint_zone and not _is_kua_feeder(primary):
                for k in keys:
                    if k in out or k not in energized:
                        continue
                    if k not in back_paint_zone:
                        continue
                    key_feeder = str(s.node_feeder.get(k, ""))
                    if key_feeder and key_feeder not in (primary, src):
                        continue
                    out[k] = src
                    changed = True
                continue
            # R67: native feeder supply may extend only within the same GIS feeder.
            for k in keys:
                if k in out:
                    continue
                key_feeder = str(s.node_feeder.get(k, ""))
                if src == primary and key_feeder and key_feeder != primary:
                    continue
                if (
                    primary
                    and src not in back_sources
                    and key_feeder
                    and key_feeder != src
                    and not (
                        str(src).startswith("KUA")
                        and key_feeder.startswith("KUA")
                    )
                ):
                    continue
                out[k] = src
                changed = True
    return out


def _conductor_segment_off(
    keys: list[str],
    energized: set[str],
    affected: set[str],
    *,
    s: NetworkState | None = None,
    zone_xy: list[tuple[float, float]] | None = None,
    zone_index: tuple[cKDTree | None, tuple[float, float, float, float] | None]
    | None = None,
    physical: bool = False,
    back_paint_zone: set[str] | None = None,
) -> bool:
    """True when a conductor segment should render as de-energised."""
    if physical and keys:
        if all(k in energized for k in keys):
            return False
        # R76: back-feed highway stays ON up to an open isolation sectional
        # (one endpoint may be the open switch graph node).
        if back_paint_zone:
            in_zone = [k for k in keys if k in back_paint_zone]
            lit = [k for k in keys if k in energized]
            if in_zone and lit and len(lit) >= max(1, len(keys) - 1):
                return False
    if any(k in affected for k in keys):
        if physical:
            if all(k in energized for k in keys):
                return False
            if back_paint_zone:
                in_zone = [k for k in keys if k in back_paint_zone]
                lit = [k for k in keys if k in energized]
                if in_zone and lit and len(lit) >= max(1, len(keys) - 1):
                    return False
            return True
        return True
    if (
        not physical
        and s is not None
        and affected
        and keys
        and _segment_touches_zone(
            s, keys, affected, zone_xy, zone_index=zone_index,
        )
    ):
        # R69/R72: main-line at a lateral RC tap is graph-adjacent to the RC
        # (in the affected island) but stays energised — do not GIS/adjacency
        # bleed the outage onto those lit trunk segments.
        if all(k in energized for k in keys):
            return False
        return True
    return not all(k in energized for k in keys)


# build_live_conductors — defined after fault/maintenance zone helpers (below)


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


def _recloser_instruction_th(action: str, rc_id: str, feeder: str, location: str) -> str:
    verb = "ปลด" if action == "OPEN" else "ปิด"
    loc = f" ({location})" if location else ""
    return f"{verb} Recloser {rc_id} · ฟีดเดอร์ {feeder}{loc}"


def _device_meta(s: NetworkState, fid: str) -> tuple[dict, str]:
    """Return (properties, kind) where kind is ``switch`` | ``recloser``."""
    for sw in s.switches:
        if sw["properties"]["id"] == fid:
            return sw["properties"], "switch"
    for rc in s.reclosers:
        if rc["properties"]["id"] == fid:
            return rc["properties"], "recloser"
    return {}, "switch"


def _step_instruction_th(s: NetworkState, action: str, fid: str) -> str:
    props, kind = _device_meta(s, fid)
    loc = props.get("location", "")
    feeder = props.get("feeder", "?")
    if kind == "recloser":
        return _recloser_instruction_th(action, fid, feeder, loc)
    return _switch_instruction_th(action, fid, feeder, loc)


_KUA01_MAINLINE_BOUND_PAIRS: tuple[tuple[str, str], ...] = (
    ("PDA10S-08", "PDA10S-13"),
    ("PDA10S-13", "PDA10S-14"),
    ("PDA10S-14", "KUA01R-04"),
)

_KUA01_SEGMENT_LABELS: dict[int, str] = {
    1: "PDA10S-08 ↔ PDA10S-13",
    2: "PDA10S-13 ↔ PDA10S-14",
    3: "PDA10S-14 ↔ KUA01R-04",
}

# PDA07 lateral behind PDA07R-01 — operator preset (R71), not KUA.
_PDA07_R01_RC = "PDA07R-01"
_PDA07_R01_SECTIONAL = "PDA07S-12"
_PDA07_R01_TIE_BETWEEN = "PDA05S-15"  # restore load-side of S-12
_PDA07_R01_TIE_AFTER = "PDA05S-11"    # restore further lateral / spur
_PDA07_R01_SEGMENT_LABELS: dict[int, str] = {
    1: "PDA07R-01 ↔ PDA07S-12",
    2: "หลัง PDA07S-12",
}


def _kua01_device_hop(s: NetworkState, fid: str) -> int | None:
    """Hop from KUA01 line-end seed to a mainline device node."""
    hop = _kua_feeder_hop_from_seed(s, "KUA01")
    node = s.switch_node.get(fid) or s.recloser_node.get(fid)
    if not node:
        return None
    return hop.get(node)


def _kua01_mainline_segment(s: NetworkState) -> int | None:
    """Return 1|2|3 for a KUA01 mainline fault in a preset zone, else None (R52)."""
    if s.fault_feeder != "KUA01" or not s.fault_node:
        return None
    hop = _kua_feeder_hop_from_seed(s, "KUA01")
    fault_hop = hop.get(s.fault_node)
    if fault_hop is None:
        return None
    bounds: list[tuple[int, int]] = []
    for lo_fid, hi_fid in _KUA01_MAINLINE_BOUND_PAIRS:
        lo_hop = _kua01_device_hop(s, lo_fid)
        hi_hop = _kua01_device_hop(s, hi_fid)
        if lo_hop is None or hi_hop is None:
            return None
        bounds.append((lo_hop, hi_hop))
    h08, h13 = bounds[0]
    _, h14 = bounds[1]
    _, h04 = bounds[2]
    if h08 < fault_hop <= h13:
        return 1
    if h13 < fault_hop <= h14:
        return 2
    if h14 < fault_hop <= h04:
        return 3
    return None


def _kua01_preset_step_specs(segment: int) -> list[dict]:
    """Operator-defined KUA01 mainline switching sequence per segment (R52)."""
    if segment == 1:
        return [
            {
                "action": "OPEN", "fid": "PDA10R-01", "section": "isolation",
                "reason": "ปลด PDA10R-01 แยกโซนฟอลท์",
            },
            {
                "action": "OPEN", "fid": "PDA10S-13", "section": "isolation",
                "reason": "ปลด PDA10S-13 แยกโซนฟอลท์",
            },
            {
                "action": "NOTE", "fid": None, "section": "restoration",
                "reason": "line_end_to:PDA10S-13",
            },
            {
                "action": "CLOSE", "fid": "PDA02S-08", "section": "restoration",
                "reason": (
                    "ปิด tie PDA02S-08 จ่ายไฟมาชน PDA10R-01 "
                    "เพื่อให้ทั้งหมดหลัง PDA10R-01 ใช้ไฟได้"
                ),
            },
            {
                "action": "NOTE", "fid": None, "section": "restoration",
                "reason": "repair",
            },
        ]
    if segment == 2:
        return [
            {
                "action": "OPEN", "fid": "PDA10S-13", "section": "isolation",
                "reason": "ปลด PDA10S-13 แยกโซนฟอลท์",
            },
            {
                "action": "CLOSE", "fid": "PDA10S-08", "section": "restoration",
                "reason": "ปิด PDA10S-08 จ่ายไฟมาชน PDA10S-13",
            },
            {
                "action": "OPEN", "fid": "PDA10S-14", "section": "restoration",
                "reason": "เปิด PDA10S-14 เพื่อบล็อกโซนฟอลท์",
            },
            {
                "action": "NOTE", "fid": None, "section": "restoration",
                "reason": "line_end_to:PDA10S-14",
            },
            {
                "action": "NOTE", "fid": None, "section": "restoration",
                "reason": "repair",
            },
        ]
    if segment == 3:
        return [
            {
                "action": "OPEN", "fid": "KUA01R-04", "section": "isolation",
                "reason": "ปลด KUA01R-04 แยกโซนฟอลท์",
            },
            {
                "action": "OPEN", "fid": "PDA10S-14", "section": "isolation",
                "reason": "ปลด PDA10S-14 แยกโซนฟอลท์",
            },
            {
                "action": "CLOSE", "fid": "PDA10S-08", "section": "restoration",
                "reason": "ปิด PDA10S-08 จ่ายไฟมาชน PDA10S-14",
            },
            {
                "action": "NOTE", "fid": None, "section": "restoration",
                "reason": "repair",
            },
        ]
    return []


def _kua01_line_end_note_reason(
    s: NetworkState,
    work_zone: set[str],
    plan_open: set[str],
    target_fid: str,
) -> tuple[str, int]:
    """NOTE text confirming KUA line-end back-feed to a sectionaliser."""
    back_n, back_c = _line_end_backfeed_summary(s, work_zone, "KUA01", plan_open)
    cust_txt = f" · ~{back_c:,} ลูกค้า" if back_c else ""
    reason = (
        f"ยืนยัน: จ่ายไฟจาก KUA01 (ปลายสาย) มาชน {target_fid} แล้ว "
        f"(~{back_n:,} nodes{cust_txt}) — เริ่มซ่อมจุดฟอลท์เมื่อพร้อม"
    )
    return reason, back_n


def _kua01_preset_switching_plan(
    s: NetworkState,
    work_zone: set[str],
    *,
    context_label: str,
    meta: dict,
    segment: int,
) -> dict:
    """Build the fixed KUA01 mainline switching plan for segment 1|2|3 (R52)."""
    if not work_zone:
        return {"error": "ไม่พบโซนปฏิบัติงาน — ตรวจสอบพิกัดหรือจุดฟอลต์"}

    primary_feeder = "KUA01"
    all_nodes = set(s.adjacency.keys())
    energized0 = _kua_feeder_energization_ex(s, primary_feeder)
    de_nodes0 = all_nodes - energized0

    steps: list[dict] = []
    plan_open: set[str] = set()
    plan_closed: set[str] = set()
    step_no = 0
    cumulative_energized = energized0

    for spec in _kua01_preset_step_specs(segment):
        action = spec["action"]
        fid = spec.get("fid")
        section = spec["section"]
        raw_reason = spec["reason"]
        nodes_restored = 0

        if action == "NOTE":
            step_no += 1
            if raw_reason.startswith("line_end_to:"):
                target = raw_reason.split(":", 1)[1]
                reason, nodes_restored = _kua01_line_end_note_reason(
                    s, work_zone, plan_open, target,
                )
                note_effect = "kuaLineEndAck"
                note_target = target
            elif raw_reason == "repair":
                reason = (
                    "ซ่อมแซมจุดฟอลท์ — ยืนยันพื้นที่ปลอดภัยก่อนดำเนินการคืนระบบ"
                )
                note_effect = None
                note_target = None
            else:
                reason = raw_reason
                note_effect = None
                note_target = None
            note_step: dict = {
                "action": "NOTE",
                "switchId": None,
                "deviceType": "note",
                "section": section,
                "feeder": primary_feeder,
                "location": "",
                "instructionTh": reason,
                "reason": f"ขั้นที่ {step_no} — {reason}",
                "nodesRestored": nodes_restored,
            }
            if note_effect:
                note_step["planEffect"] = note_effect
            if note_target:
                note_step["planEffectTarget"] = note_target
            steps.append(note_step)
            continue

        step_no += 1
        props, kind = _device_meta(s, fid)
        if action == "OPEN":
            plan_open.add(fid)
        elif action == "CLOSE":
            baseline = cumulative_energized
            plan_closed.add(fid)
            cumulative_energized = _combined_plan_energized(
                s, primary_feeder, plan_open, plan_closed,
            )
            gained = cumulative_energized - baseline
            nodes_restored = len(gained)
            gained_c = _customers_in_nodes(s, gained) or nodes_restored
            if gained_c and "ลูกค้า" not in raw_reason:
                raw_reason = f"{raw_reason} (+{nodes_restored:,} nodes · ~{gained_c:,} ลูกค้า)"

        steps.append({
            "action": action,
            "switchId": fid,
            "deviceType": kind,
            "section": section,
            "feeder": props.get("feeder", primary_feeder),
            "location": props.get("location", ""),
            "instructionTh": _step_instruction_th(s, action, fid),
            "reason": f"ขั้นที่ {step_no} — {raw_reason}",
            "nodesRestored": nodes_restored,
        })

    for i, step in enumerate(steps):
        step["step"] = i + 1

    de_iso = all_nodes - _combined_plan_energized(
        s, primary_feeder, plan_open, plan_closed,
    )
    total_restorable = sum(st["nodesRestored"] for st in steps)
    nodes_irrecoverable = len(work_zone)
    fault_pct = round(nodes_irrecoverable / max(1, len(all_nodes)) * 100, 2)
    iso_count = sum(1 for st in steps if st.get("section") == "isolation")
    res_count = sum(1 for st in steps if st.get("section") == "restoration")
    seg_label = _KUA01_SEGMENT_LABELS.get(segment, "?")
    next_step = steps[0] if steps else None
    next_hint = (
        next_step["instructionTh"]
        if next_step
        else "ไม่มีขั้นตอน — ตรวจสอบสถานะเครือข่าย"
    )
    operator_brief = (
        f"{meta.get('operatorBrief', context_label)} · "
        f"KUA01 แผนกำหนดโซน {segment} ({seg_label})"
    )

    return {
        "steps":              steps,
        "operatorBrief":      operator_brief,
        "nextStepHint":       next_hint,
        "isolationSteps":     iso_count,
        "restorationSteps":   res_count,
        "faultZoneNodes":     nodes_irrecoverable,
        "faultZonePct":       fault_pct,
        "deenergizedNodes":   len(de_nodes0),
        "totalRestorable":    total_restorable,
        "nodesIrrecoverable": nodes_irrecoverable,
        "kua01PresetSegment": segment,
        "kua01PresetLabel":   seg_label,
        "kuaLineEndSource":   True,
        "summary": (
            f"ดับ {len(de_nodes0):,} nodes · "
            f"โซนปฏิบัติงาน {nodes_irrecoverable:,} ({fault_pct}%) · "
            f"แผนกำหนด KUA01 โซน {segment} {len(steps)} ขั้น "
            f"(แยก {iso_count} / คืน {res_count}) · "
            f"คืนไฟได้ {total_restorable:,} nodes"
        ),
        **meta,
    }


def _pda07_r01_segment(s: NetworkState) -> int | None:
    """Return 1|2 for a PDA07R-01 lateral fault, else None (R71).

    1 = between PDA07R-01 and PDA07S-12 (inclusive of S-12 hop)
    2 = load-side of PDA07S-12 (hop > S-12)
    """
    if s.fault_feeder != "PDA07" or not s.fault_node:
        return None
    if _PDA07_R01_RC not in s.recloser_node:
        return None
    if _PDA07_R01_SECTIONAL not in s.switch_node:
        return None
    island = _rc_load_side_island(s, _PDA07_R01_RC, "PDA07")
    if s.fault_node not in island:
        return None
    hop = _feeder_protection_hop_map(s, "PDA07")
    rc_node = s.recloser_node[_PDA07_R01_RC]
    s12_node = s.switch_node[_PDA07_R01_SECTIONAL]
    fault_hop = hop.get(s.fault_node)
    rc_hop = hop.get(rc_node)
    s12_hop = hop.get(s12_node)
    if fault_hop is None or rc_hop is None or s12_hop is None:
        return None
    if rc_hop < fault_hop <= s12_hop:
        return 1
    if fault_hop > s12_hop:
        return 2
    return None


def _pda07_r01_preset_step_specs(segment: int) -> list[dict]:
    """Operator-defined PDA07R-01 lateral switching sequence (R71)."""
    if segment == 1:
        return [
            {
                "action": "OPEN", "fid": _PDA07_R01_SECTIONAL, "section": "isolation",
                "reason": "ปลด PDA07S-12 แยกโซนฟอลท์ระหว่าง PDA07R-01 กับ PDA07S-12",
            },
            {
                "action": "CLOSE", "fid": _PDA07_R01_TIE_BETWEEN, "section": "restoration",
                "reason": (
                    "ปิด tie PDA05S-15 จ่ายไฟจาก PDA05 มาชน PDA07S-12 "
                    "เพื่อคืนไฟฝั่งโหลดหลังสวิตช์ที่เปิด"
                ),
            },
            {
                "action": "NOTE", "fid": None, "section": "restoration",
                "reason": "repair",
            },
        ]
    if segment == 2:
        return [
            {
                "action": "OPEN", "fid": _PDA07_R01_SECTIONAL, "section": "isolation",
                "reason": "ปลด PDA07S-12 แยกโซนฟอลท์หลัง PDA07S-12",
            },
            {
                "action": "CLOSE", "fid": _PDA07_R01_TIE_AFTER, "section": "restoration",
                "reason": (
                    "ปิด tie PDA05S-11 จ่ายไฟจาก PDA05 "
                    "จนถึงสวิตช์ PDA07S-12 ที่เปิดอยู่"
                ),
            },
            {
                "action": "NOTE", "fid": None, "section": "restoration",
                "reason": "repair",
            },
        ]
    return []


def _pda07_r01_preset_switching_plan(
    s: NetworkState,
    work_zone: set[str],
    *,
    context_label: str,
    meta: dict,
    segment: int,
) -> dict:
    """Fixed PDA07R-01 lateral switching plan for segment 1|2 (R71)."""
    if not work_zone:
        return {"error": "ไม่พบโซนปฏิบัติงาน — ตรวจสอบพิกัดหรือจุดฟอลต์"}

    primary_feeder = "PDA07"
    all_nodes = set(s.adjacency.keys())
    energized0 = compute_energization(s, planning=True)
    de_nodes0 = all_nodes - energized0

    steps: list[dict] = []
    plan_open: set[str] = set()
    plan_closed: set[str] = set()
    # Auto-tripped protecting RC is already open — keep it in the cut set.
    for fid, st in s.recloser_status.items():
        if st == 0:
            plan_open.add(fid)
    step_no = 0
    cumulative_energized = _energization_under_plan(s, plan_open, plan_closed)

    for spec in _pda07_r01_preset_step_specs(segment):
        action = spec["action"]
        fid = spec.get("fid")
        section = spec["section"]
        raw_reason = spec["reason"]
        nodes_restored = 0

        if action == "NOTE":
            step_no += 1
            if raw_reason == "repair":
                reason = (
                    "ซ่อมแซมจุดฟอลท์ — ยืนยันพื้นที่ปลอดภัยก่อนดำเนินการคืนระบบ"
                )
            else:
                reason = raw_reason
            steps.append({
                "action": "NOTE",
                "switchId": None,
                "deviceType": "note",
                "section": section,
                "feeder": primary_feeder,
                "location": "",
                "instructionTh": reason,
                "reason": f"ขั้นที่ {step_no} — {reason}",
                "nodesRestored": 0,
            })
            continue

        step_no += 1
        props, kind = _device_meta(s, fid)
        if action == "OPEN":
            plan_open.add(fid)
        elif action == "CLOSE":
            baseline = cumulative_energized
            plan_closed.add(fid)
            cumulative_energized = _energization_under_plan(
                s, plan_open, plan_closed,
            )
            gained = cumulative_energized - baseline
            nodes_restored = len(gained)
            gained_c = _customers_in_nodes(s, gained) or nodes_restored
            if gained_c and "ลูกค้า" not in raw_reason:
                raw_reason = (
                    f"{raw_reason} (+{nodes_restored:,} nodes · ~{gained_c:,} ลูกค้า)"
                )

        steps.append({
            "action": action,
            "switchId": fid,
            "deviceType": kind,
            "section": section,
            "feeder": props.get("feeder", primary_feeder),
            "location": props.get("location", ""),
            "instructionTh": _step_instruction_th(s, action, fid),
            "reason": f"ขั้นที่ {step_no} — {raw_reason}",
            "nodesRestored": nodes_restored,
        })

    for i, step in enumerate(steps):
        step["step"] = i + 1

    de_iso = all_nodes - _energization_under_plan(s, plan_open, plan_closed)
    total_restorable = sum(st["nodesRestored"] for st in steps)
    nodes_irrecoverable = len(work_zone)
    fault_pct = round(nodes_irrecoverable / max(1, len(all_nodes)) * 100, 2)
    iso_count = sum(1 for st in steps if st.get("section") == "isolation")
    res_count = sum(1 for st in steps if st.get("section") == "restoration")
    seg_label = _PDA07_R01_SEGMENT_LABELS.get(segment, "?")
    next_step = steps[0] if steps else None
    next_hint = (
        next_step["instructionTh"]
        if next_step
        else "ไม่มีขั้นตอน — ตรวจสอบสถานะเครือข่าย"
    )
    operator_brief = (
        f"{meta.get('operatorBrief', context_label)} · "
        f"PDA07 แผนกำหนดโซนหลัง {_PDA07_R01_RC} · {seg_label}"
    )

    return {
        "steps":              steps,
        "operatorBrief":      operator_brief,
        "nextStepHint":       next_hint,
        "isolationSteps":     iso_count,
        "restorationSteps":   res_count,
        "faultZoneNodes":     nodes_irrecoverable,
        "faultZonePct":       fault_pct,
        "deenergizedNodes":   len(de_nodes0),
        "residualDarkNodes":  len(de_iso),
        "totalRestorable":    total_restorable,
        "nodesIrrecoverable": nodes_irrecoverable,
        "pda07R01PresetSegment": segment,
        "pda07R01PresetLabel":   seg_label,
        "summary": (
            f"ดับ {len(de_nodes0):,} nodes · "
            f"โซนปฏิบัติงาน {nodes_irrecoverable:,} ({fault_pct}%) · "
            f"แผนกำหนด PDA07 {_PDA07_R01_RC} โซน {segment} {len(steps)} ขั้น "
            f"(แยก {iso_count} / คืน {res_count}) · "
            f"คืนไฟได้ {total_restorable:,} nodes"
        ),
        **meta,
    }


def generate_switching_plan(s: NetworkState) -> dict:
    if not s.fault_node:
        return {"error": "ไม่มี fault ที่ active กรุณาวางจุดฟอลต์หรือระบุพิกัดก่อน"}

    fault_zone = _cc_get(s, "fault_topo", lambda: compute_fault_affected_nodes(s))
    coords_txt = _format_fault_coords(s.fault_lat, s.fault_lon)
    cause = normalize_cause(s.fault_cause)
    phase = s.fault_phase or "ALL"
    plan_meta = {
        "planType":    "fault",
        "feeder":      s.fault_feeder,
        "faultFeeder": s.fault_feeder,
        "faultLat":    s.fault_lat,
        "faultLon":    s.fault_lon,
        "faultCoords": coords_txt,
        "faultCause":  cause,
        "faultPhase":  phase,
        "operatorBrief": (
            f"ฟีดเดอร์ {s.fault_feeder or '?'} · พิกัด {coords_txt} · "
            f"สาเหตุ {cause} · เฟส {phase}"
        ),
    }
    kua01_segment = (
        _kua01_mainline_segment(s)
        if _is_kua_feeder(s.fault_feeder) else None
    )
    pda07_r01_segment = (
        _pda07_r01_segment(s)
        if s.fault_feeder == "PDA07" else None
    )
    if kua01_segment is not None:
        result = _kua01_preset_switching_plan(
            s, fault_zone,
            context_label="จุดฟอลต์ (Fault Isolation)",
            meta=plan_meta,
            segment=kua01_segment,
        )
    elif pda07_r01_segment is not None:
        result = _pda07_r01_preset_switching_plan(
            s, fault_zone,
            context_label="จุดฟอลต์ (Fault Isolation)",
            meta=plan_meta,
            segment=pda07_r01_segment,
        )
    else:
        result = _switching_plan_for_zone(
            s, fault_zone,
            context_label="จุดฟอลต์ (Fault Isolation)",
            meta=plan_meta,
        )
    if result.get("error"):
        return result
    _store_switching_plan_runtime(s, result.get("steps", []))
    norm = generate_normalization_plan(s, result.get("steps", []))
    result["normalizationSteps"] = norm.get("steps", [])
    result["normalizationCount"] = len(result["normalizationSteps"])
    if _is_kua_feeder(s.fault_feeder):
        result["kuaLineEndSource"] = True
        result["operatorBrief"] = (
            f"{result.get('operatorBrief', '')} · "
            "KUA: สมมติกระแสจากปลายสาย"
        )
    result.update(_switching_plan_runtime_payload(s))
    return result


def _switching_plan_runtime_payload(s: NetworkState) -> dict:
    """Operator plan-execute progress for API + UI sync (R53)."""
    return {
        "switchingPlanExecuted": s.switching_plan_executed,
        "kuaLineEndAck": s.kua_line_end_display_ack,
        "lineDisplayPhysical": _display_restoration_live(s),
    }


def _switches_geojson(s: NetworkState) -> list[dict]:
    out = []
    for sw in s.switches:
        fid = sw["properties"]["id"]
        status = s.switch_status.get(fid, sw["properties"]["status"])
        out.append({**sw, "properties": {**sw["properties"],
                    "status": status, "state": "CLOSE" if status == 1 else "OPEN"}})
    return out


def _reclosers_geojson(s: NetworkState) -> list[dict]:
    out = []
    for rc in s.reclosers:
        fid = rc["properties"]["id"]
        status = s.recloser_status.get(fid, rc["properties"].get("status", 1))
        out.append({**rc, "properties": {**rc["properties"],
                    "status": status, "state": "CLOSE" if status == 1 else "OPEN"}})
    return out


def generate_normalization_plan(
    s: NetworkState,
    fault_steps: list[dict] | None = None,
) -> dict:
    """Post-repair plan — restore switches/reclosers to pre-fault positions."""
    if not s.fault_node:
        return {"error": "ไม่มี fault ที่ active"}
    if s.snapshot_switch is None and s.snapshot_recloser is None:
        return {"error": "ไม่มี snapshot สถานะก่อนฟอลต์"}

    snap_sw = s.snapshot_switch or {}
    snap_rc = s.snapshot_recloser or {}
    steps: list[dict] = []
    step_no = 0

    step_no += 1
    steps.append({
        "action":      "NOTE",
        "switchId":    None,
        "deviceType":  "note",
        "section":     "normalization",
        "feeder":      s.fault_feeder or "?",
        "location":    "",
        "instructionTh": (
            "ยืนยันซ่อมแซมจุดฟอลต์เสร็จและพื้นที่ปลอดภัย — "
            "จากนั้นดำเนินขั้นตอนคืนระบบเดิมด้านล่าง"
        ),
        "reason": f"ขั้นที่ {step_no} — ตรวจสอบก่อนคืนระบบ",
        "nodesRestored": 0,
    })

    planned_ids: set[str] = set()
    if fault_steps:
        for st in reversed(fault_steps):
            if st.get("section") != "restoration":
                continue
            fid = st.get("switchId")
            if not fid or fid in planned_ids:
                continue
            normal = snap_sw.get(fid, 1)
            if normal != 0:
                continue
            planned_ids.add(fid)
            step_no += 1
            props, kind = _device_meta(s, fid)
            steps.append({
                "action":      "OPEN",
                "switchId":    fid,
                "deviceType":  kind,
                "section":     "normalization",
                "feeder":      props.get("feeder", "?"),
                "location":    props.get("location", ""),
                "instructionTh": _step_instruction_th(s, "OPEN", fid),
                "reason": (
                    f"ขั้นที่ {step_no} — เปิด tie กลับสถานะปกติ "
                    f"(เดิม OPEN)"
                ),
                "nodesRestored": 0,
            })

        for st in reversed(fault_steps):
            if st.get("section") != "isolation":
                continue
            fid = st.get("switchId")
            if not fid or fid in planned_ids:
                continue
            normal = snap_sw.get(fid, snap_rc.get(fid, 1))
            if normal != 1:
                continue
            planned_ids.add(fid)
            step_no += 1
            props, kind = _device_meta(s, fid)
            steps.append({
                "action":      "CLOSE",
                "switchId":    fid,
                "deviceType":  kind,
                "section":     "normalization",
                "feeder":      props.get("feeder", "?"),
                "location":    props.get("location", ""),
                "instructionTh": _step_instruction_th(s, "CLOSE", fid),
                "reason": (
                    f"ขั้นที่ {step_no} — ปิดกลับสถานะปกติหลังซ่อม"
                ),
                "nodesRestored": 0,
            })

    for fid, normal in snap_sw.items():
        if fid in planned_ids:
            continue
        current = s.switch_status.get(fid)
        if current == normal:
            continue
        action = "CLOSE" if normal == 1 else "OPEN"
        step_no += 1
        props, kind = _device_meta(s, fid)
        steps.append({
            "action":      action,
            "switchId":    fid,
            "deviceType":  kind,
            "section":     "normalization",
            "feeder":      props.get("feeder", "?"),
            "location":    props.get("location", ""),
            "instructionTh": _step_instruction_th(s, action, fid),
            "reason": f"ขั้นที่ {step_no} — คืนสวิตช์กลับสถานะก่อนฟอลต์",
            "nodesRestored": 0,
        })
        planned_ids.add(fid)

    for fid, normal in snap_rc.items():
        if fid in planned_ids:
            continue
        current = s.recloser_status.get(fid)
        if current == normal:
            continue
        action = "CLOSE" if normal == 1 else "OPEN"
        step_no += 1
        props, kind = _device_meta(s, fid)
        steps.append({
            "action":      action,
            "switchId":    fid,
            "deviceType":  kind,
            "section":     "normalization",
            "feeder":      props.get("feeder", "?"),
            "location":    props.get("location", ""),
            "instructionTh": _step_instruction_th(s, action, fid),
            "reason": f"ขั้นที่ {step_no} — คืน Recloser กลับสถานะก่อนฟอลต์",
            "nodesRestored": 0,
        })
        planned_ids.add(fid)

    for i, step in enumerate(steps):
        step["step"] = i + 1

    return {
        "steps":           steps,
        "normalizationCount": len(steps),
        "summary": (
            f"คืนระบบเดิม {max(0, len(steps) - 1)} ขั้น "
            f"(หลังซ่อมแซมจุดฟอลต์)"
        ),
        "faultFeeder":     s.fault_feeder,
        "faultCoords":     _format_fault_coords(s.fault_lat, s.fault_lon),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fault-impact polygon — only after an active fault is placed
# ─────────────────────────────────────────────────────────────────────────────
def _tie_boundary_nodes(s: NetworkState) -> set[str]:
    return {
        s.switch_node[fid]
        for fid in s.tie_switch_ids
        if fid in s.switch_node
    }


def _outage_zone_barrier(s: NetworkState, cur: str, nb: str) -> bool:
    """True when ``nb`` must not be entered from ``cur`` during outage BFS (R18)."""
    if nb in open_sectionalizing_switch_nodes(s):
        return True
    if _blocks_interconnect_cross_feeder(s, cur, nb):
        return True
    if nb in _tie_boundary_nodes(s):
        cur_f = s.node_feeder.get(cur, "")
        nb_f = s.node_feeder.get(nb, "")
        if cur_f != nb_f:
            return True
    return False


def _reachable_outside_zone(
    s: NetworkState,
    start: str,
    zone_wall: set[str],
    tie_nodes: set[str],
    outside: set[str],
) -> bool:
    """True when ``start`` can reach supply outside ``zone_wall`` without
    crossing the wall or open tie sectionalisers."""
    if start in zone_wall or start in tie_nodes:
        return False
    if start in outside:
        return True
    seen: set[str] = {start}
    queue: deque[str] = deque([start])
    while queue:
        cur = queue.popleft()
        if cur in outside:
            return True
        for nb in s.adjacency.get(cur, set()):
            if nb in seen or nb in zone_wall or nb in tie_nodes:
                continue
            seen.add(nb)
            queue.append(nb)
    return False


def _make_zone_snap_index(
    zone_xy: list[tuple[float, float]],
    snap_m: float = _LATERAL_SNAP_M,
) -> tuple[cKDTree | None, tuple[float, float, float, float] | None]:
    """cKDTree + padded bbox for O(log N) lateral-tap proximity (R36)."""
    if not zone_xy:
        return None, None
    arr = np.array(zone_xy, dtype=np.float64)
    pad = snap_m
    bbox = (
        float(arr[:, 0].min()) - pad,
        float(arr[:, 1].min()) - pad,
        float(arr[:, 0].max()) + pad,
        float(arr[:, 1].max()) + pad,
    )
    return cKDTree(arr), bbox


def _segment_near_nodes(
    s: NetworkState,
    keys: list[str],
    nodes: set[str],
    *,
    snap_m: float = 100.0,
    zone_index: tuple[cKDTree | None, tuple[float, float, float, float] | None]
    | None = None,
) -> bool:
    """True when a conductor key is GIS-near any node in ``nodes`` (R76 bleed)."""
    if not keys or not nodes:
        return False
    if any(k in nodes for k in keys):
        return True
    if zone_index is None:
        zone_xy = [s.node_xy[k] for k in nodes if k in s.node_xy]
        zone_index = _make_zone_snap_index(zone_xy, snap_m)
    tree, bbox = zone_index
    if tree is None or bbox is None:
        return False
    minx, miny, maxx, maxy = bbox
    for k in keys:
        if k not in s.node_xy:
            continue
        x, y = s.node_xy[k]
        if x < minx or x > maxx or y < miny or y > maxy:
            continue
        dist, _ = tree.query([x, y], k=1)
        if float(dist) <= snap_m:
            return True
    return False


def _segment_touches_zone(
    s: NetworkState,
    keys: list[str],
    zone: set[str],
    zone_xy: list[tuple[float, float]] | None = None,
    snap_m: float = _LATERAL_SNAP_M,
    zone_index: tuple[cKDTree | None, tuple[float, float, float, float] | None]
    | None = None,
) -> bool:
    """Graph edge or GIS-near tap (recloser/dropout) to the outage zone."""
    if any(k in zone for k in keys):
        return True
    if any(
        nb in zone
        for k in keys
        for nb in s.adjacency.get(k, set())
    ):
        return True
    if zone_index is None:
        if zone_xy is None:
            zone_xy = [s.node_xy[k] for k in zone if k in s.node_xy]
        zone_index = _make_zone_snap_index(zone_xy, snap_m)
    tree, bbox = zone_index
    if tree is None or bbox is None:
        return False
    minx, miny, maxx, maxy = bbox
    for k in keys:
        if k not in s.node_xy:
            continue
        x, y = s.node_xy[k]
        if x < minx or x > maxx or y < miny or y > maxy:
            continue
        dist, _ = tree.query([x, y], k=1)
        if dist <= snap_m:
            return True
    return False


def _nodes_with_outside_supply(
    s: NetworkState,
    core: set[str],
    open_tie: set[str],
    outside: set[str],
) -> set[str]:
    """All nodes that can reach ``outside`` without crossing ``core`` or open ties."""
    supplied = set(outside)
    queue: deque[str] = deque(outside)
    while queue:
        cur = queue.popleft()
        for nb in s.adjacency.get(cur, set()):
            if nb in supplied or nb in core or nb in open_tie:
                continue
            supplied.add(nb)
            queue.append(nb)
    return supplied


def _shortest_path_in_zone(
    s: NetworkState,
    start: str,
    targets: set[str],
    allowed: set[str],
    *,
    open_barrier: set[str] | None = None,
) -> set[str]:
    """Shortest-path node set from ``start`` to any of ``targets`` within ``allowed``."""
    if start in targets:
        return {start}
    barrier = open_barrier or set()
    parent: dict[str, str] = {}
    queue: deque[str] = deque([start])
    seen: set[str] = {start}
    hit: str | None = None
    while queue:
        cur = queue.popleft()
        if cur in barrier and cur != start:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb not in allowed or nb in seen:
                continue
            if _blocks_interconnect_cross_feeder(s, cur, nb):
                continue
            seen.add(nb)
            parent[nb] = cur
            if nb in targets:
                hit = nb
                break
            queue.append(nb)
        if hit is not None:
            break
    if hit is None:
        return {start}
    path: set[str] = {hit}
    walk = hit
    while walk != start:
        walk = parent[walk]
        path.add(walk)
    return path


def _source_corridor_allowed_sets(
    s: NetworkState, fault: str, feeder: str,
) -> tuple[list[set[str]], set[str], set[str]]:
    """``(allowed_sets, cb_nodes, mesh_allowed)`` for source-corridor tracing."""
    mesh_allowed = set(s._feeder_keys.get(feeder, []))
    cb_nodes = _feeder_active_cb_nodes(s, feeder)
    if _is_kua_feeder(feeder):
        hop_allowed = _kua_source_side_nodes(s, fault, feeder)
        allowed_sets: list[set[str]] = []
        if hop_allowed:
            allowed_sets.append(hop_allowed)
        if mesh_allowed - hop_allowed:
            allowed_sets.append(mesh_allowed)
        return allowed_sets, cb_nodes, mesh_allowed
    hop_allowed = _source_closer_than_fault(s, fault, feeder) | {fault}
    allowed_sets = []
    if hop_allowed:
        allowed_sets.append(hop_allowed)
    if mesh_allowed - hop_allowed:
        allowed_sets.append(mesh_allowed)
    return allowed_sets, cb_nodes, mesh_allowed


def _paths_to_open_targets(
    s: NetworkState,
    fault: str,
    targets: set[str],
    allowed_sets: list[set[str]],
    *,
    open_barrier: set[str] | None = None,
) -> set[str]:
    """Union shortest-path corridors from ``fault`` to each open target (R62)."""
    zone: set[str] = {fault}
    barrier = open_barrier or set()
    for allowed in allowed_sets:
        for target in targets:
            if target == fault or target not in allowed:
                continue
            path = _shortest_path_in_zone(
                s, fault, {target}, allowed, open_barrier=barrier,
            )
            if len(path) > 1:
                zone |= path
    return zone


def _operator_open_isolation_graph_nodes(s: NetworkState) -> set[str]:
    """Graph nodes of switches/reclosers the operator opened since fault snapshot."""
    if not s.fault_node:
        return set()
    snap_sw = s.snapshot_switch or {}
    snap_rc = s.snapshot_recloser or {}
    nodes: set[str] = set()
    for fid, st in s.switch_status.items():
        if st == 0 and snap_sw.get(fid, 1) == 1:
            node = s.switch_node.get(fid)
            if node:
                nodes.add(node)
    for fid, st in s.recloser_status.items():
        if st == 0 and snap_rc.get(fid, 1) == 1:
            node = s.recloser_node.get(fid)
            if node:
                nodes.add(node)
    return nodes


def _isolation_envelope_nodes(s: NetworkState, fault: str) -> set[str]:
    """Blocked section: fault to every operator-opened iso device (R62).

    When both a main-line tie and a lateral RC are opened for isolation, the
    outage polygon must cover the full main-line corridor — not only the path
    to the nearest open device."""
    targets = _operator_open_isolation_graph_nodes(s)
    if not targets:
        return {fault}
    feeder = s.fault_feeder or s.node_feeder.get(fault, "")
    open_sw = open_isolation_nodes(s)
    allowed_sets, _, mesh = _source_corridor_allowed_sets(s, fault, feeder)
    extra_sets: list[set[str]] = list(allowed_sets)
    if feeder.startswith("PDA"):
        mesh_f = _feeder_mesh_nodes(s, feeder)
        dist = _feeder_cb_hop_distance(s, feeder)
        fh = dist.get(fault, 0)
        load_allowed = {n for n in mesh_f if dist.get(n, 0) > fh} | {fault}
        extra_sets.extend([load_allowed, mesh_f])
    elif _is_kua_feeder(feeder):
        extra_sets.extend([
            _kua_load_side_nodes(s, fault, feeder) | {fault},
            _kua_mesh_allowed(s, feeder),
        ])
    else:
        extra_sets.append(mesh)
    return _paths_to_open_targets(
        s, fault, targets, extra_sets, open_barrier=open_sw,
    )


def _kua_residual_outage_nodes(s: NetworkState, feeder: str) -> set[str]:
    """KUA mesh still dark between isolation barriers after back-feed (R63/R66).

    * Zone1 (RC + sectional): supply reaches the open isolation RC (PDA10R-01)
      but not past it; hop band up to the open sectional stays dark.
    * Zone2 (two sectionals): after PDA10S-08 CLOSE + line-end NOTE, the band
      between PDA10S-13 and PDA10S-14 stays dark with outage polygons."""
    if not _is_kua_feeder(feeder) or not _active_backfeed_source_feeders(s):
        return set()
    live = compute_live_energization(s)
    hop = _kua_restoration_hop_from_seed(s, feeder)
    if not hop:
        return set()

    rc_hops: list[int] = []
    for fid in _tripped_isolation_rc_ids(s):
        node = s.recloser_node.get(fid)
        if node and node in hop:
            rc_hops.append(hop[node])

    sec_hops: list[int] = []
    snap_sw = s.snapshot_switch or {}
    for fid in _sectionalizing_switch_ids(s):
        if s.switch_status.get(fid, 1) == 0 and snap_sw.get(fid, 1) == 1:
            node = s.switch_node.get(fid)
            if node and node in hop:
                sec_hops.append(hop[node])

    if rc_hops:
        lo = min(rc_hops)
        hi = min(sec_hops) if sec_hops else lo
    elif len(sec_hops) >= 2:
        lo, hi = min(sec_hops), max(sec_hops)
    else:
        return set()
    mesh = _kua_mesh_allowed(s, feeder)
    return {
        n for n in mesh
        if lo <= hop.get(n, hi + 1) <= hi and n not in live
    }


def _source_corridor_to_open_device(s: NetworkState, fault: str) -> set[str]:
    """Source-ward corridors toward CB and every open tie/RC on source paths (R62).

    * No open tie/RC on the path → extend to the CB (CB node stays source-lit).
    * Open tie/RC on the path → include a corridor to each such device."""
    feeder = s.fault_feeder or s.node_feeder.get(fault, "")
    allowed_sets, cb_nodes, mesh_allowed = _source_corridor_allowed_sets(
        s, fault, feeder,
    )
    open_sw = open_isolation_nodes(s)
    if not cb_nodes:
        return {fault}

    zone: set[str] = {fault}
    for allowed in allowed_sets:
        path_to_cb = _shortest_path_in_zone(
            s, fault, cb_nodes, allowed, open_barrier=open_sw,
        )
        if path_to_cb & cb_nodes:
            zone |= path_to_cb - cb_nodes

    open_targets = (open_sw & mesh_allowed) - {fault}
    if open_targets:
        zone |= _paths_to_open_targets(
            s, fault, open_targets, allowed_sets, open_barrier=open_sw,
        )
    return zone if len(zone) > 1 else {fault}


def _fault_target_feeders(s: NetworkState) -> frozenset[str]:
    """Feeders the operator chose for outage display (R39)."""
    if s.fault_feeders:
        return frozenset(s.fault_feeders)
    if s.fault_feeder:
        return frozenset({s.fault_feeder})
    return frozenset()


def _fault_node_on_feeder(
    s: NetworkState, feeder: str, fault: str | None = None,
) -> str | None:
    """Best graph node for ``feeder`` at the fault location."""
    fault = fault or s.fault_node
    if not fault:
        return None
    if fault in s._feeder_keys.get(feeder, []):
        return fault
    if fault in s.node_xy:
        x, y = s.node_xy[fault]
        return find_nearest_in_feeder(s, x, y, feeder, fallback=False)
    return None


def _filter_nodes_to_feeders(
    s: NetworkState, nodes: set[str], scope: frozenset[str],
) -> set[str]:
    if not scope:
        return nodes
    return {n for n in nodes if s.node_feeder.get(n, "") in scope}


def _expand_zone_conductor_nodes(
    s: NetworkState,
    zone: set[str],
    feeders: set[str],
    forbidden: set[str],
) -> set[str]:
    """Pull conductor vertices that GIS-snap to ``zone`` (R41).

    Iterates until stable so laterals chained off a newly-added tap are included."""
    if not zone or not feeders:
        return zone
    expanded = set(zone)
    for _ in range(8):
        zone_xy = [s.node_xy[k] for k in expanded if k in s.node_xy]
        if not zone_xy:
            break
        zone_index = _make_zone_snap_index(zone_xy)
        added = False
        for i, keys in enumerate(s.conductor_keys):
            feeder = str(s.conductor_wgs[i]["properties"].get("feeder", ""))
            if feeder not in feeders:
                continue
            if not _segment_touches_zone(
                s, keys, expanded, zone_xy, zone_index=zone_index,
            ):
                continue
            for k in keys:
                if k in forbidden or k in expanded:
                    continue
                expanded.add(k)
                added = True
        if not added:
            break
    return expanded


def _expand_gis_zone_lateral_segments(
    s: NetworkState,
    expanded: set[str],
    feeders: set[str],
) -> set[str]:
    """Pull short lateral conductor chains inside the GIS outage envelope (R44).

    Branch lines can GIS-overlap the dark main corridor while their graph nodes
    sit on the live source partition (``forbidden``); short segments touching
    the zone are included so PDA05/PDA07 laterals de-energise with the main."""
    if not expanded or not feeders:
        return expanded
    open_sw = open_isolation_nodes(s)
    out = set(expanded)
    for _ in range(12):
        zone_xy = [s.node_xy[k] for k in out if k in s.node_xy]
        if not zone_xy:
            break
        zone_index = _make_zone_snap_index(zone_xy)
        added = False
        for keys, cw in zip(s.conductor_keys, s.conductor_wgs):
            feeder = str(cw["properties"].get("feeder", ""))
            if feeder not in feeders:
                continue
            if len(keys) > _LATERAL_SEGMENT_MAX_KEYS:
                continue
            if not _segment_touches_zone(
                s, keys, out, zone_xy, zone_index=zone_index,
            ):
                continue
            for k in keys:
                if k in out or k in open_sw:
                    continue
                out.add(k)
                added = True
        if not added:
            break
    return out


def _expand_captive_feeder_components(
    s: NetworkState,
    expanded: set[str],
    forbidden: set[str],
    feeders: set[str],
) -> set[str]:
    """Merge feeder components that only attach to the dark zone (R44).

    When an entire graph island taps the outage through nodes already in
    ``expanded`` and has no escape to the live source partition, include it."""
    open_sw = open_isolation_nodes(s)
    out = set(expanded)
    for feeder in feeders:
        mesh = _feeder_mesh_nodes(s, feeder)
        visited: set[str] = set()
        for seed in mesh:
            if seed in visited:
                continue
            comp: set[str] = set()
            queue: deque[str] = deque([seed])
            while queue:
                cur = queue.popleft()
                if cur in comp:
                    continue
                comp.add(cur)
                visited.add(cur)
                for nb in s.adjacency.get(cur, set()):
                    if s.node_feeder.get(nb) != feeder or nb in comp:
                        continue
                    if nb in open_sw:
                        continue
                    queue.append(nb)
            if not (comp & out):
                continue
            if len(comp) >= len(mesh):
                continue
            live_escape = False
            for n in comp:
                for nb in s.adjacency.get(n, set()):
                    if s.node_feeder.get(nb) != feeder or nb in comp:
                        continue
                    if nb in open_sw:
                        continue
                    if nb in out:
                        continue
                    if nb in forbidden:
                        live_escape = True
                        break
                if live_escape:
                    break
            if not live_escape:
                out |= comp
    return out


def _expand_dependent_branch_nodes(s: NetworkState, core: set[str]) -> set[str]:
    """All laterals graph-connected to the dark main / corridor (R17/R37).

    Expands from ``core`` into every branch except the still-live source
    partition (source-side nodes not already in ``core``).  Open tie/RC nodes
    are included but not crossed.  GIS-near lateral taps are pulled in when
    branch endpoints are not graph-adjacent to the main mesh."""
    if not core:
        return set()

    scope = _fault_target_feeders(s)
    forbidden: set[str] = set()
    if s.fault_node and scope:
        saved_node = s.fault_node
        saved_feeder = s.fault_feeder
        try:
            for feeder in sorted(scope):
                fn = _fault_node_on_feeder(s, feeder, saved_node)
                if not fn:
                    continue
                s.fault_node = fn
                s.fault_feeder = feeder
                source_side = _source_zone_from_fault(s, fn)
                forbidden |= source_side - core - {fn}
        finally:
            s.fault_node = saved_node
            s.fault_feeder = saved_feeder
    elif s.fault_node:
        source_side = _source_zone_from_fault(s, s.fault_node)
        forbidden = source_side - core - {s.fault_node}

    kua_fault = _is_kua_feeder(s.fault_feeder or "")
    open_sw = open_isolation_nodes(s)
    expanded: set[str] = set(core)
    bfs_q: deque[str] = deque(core)
    while bfs_q:
        cur = bfs_q.popleft()
        if cur in open_sw:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb in expanded or nb in forbidden:
                continue
            nb_feeder = s.node_feeder.get(nb, "")
            if scope and nb_feeder and nb_feeder not in scope:
                continue
            if kua_fault and nb_feeder.startswith("PDA"):
                continue
            if _blocks_interconnect_cross_feeder(s, cur, nb):
                continue
            if _is_cross_feeder_tie_hop(s, cur, nb):
                continue
            expanded.add(nb)
            if nb not in open_sw:
                bfs_q.append(nb)

    zone_xy = [s.node_xy[k] for k in expanded if k in s.node_xy]
    zone_index = _make_zone_snap_index(zone_xy)
    feeders = set(scope) if scope else (
        {s.node_feeder.get(k) for k in core if k in s.node_xy} - {""}
    )
    if not feeders and s.fault_feeder:
        feeders = {s.fault_feeder}
    for keys, cw in zip(s.conductor_keys, s.conductor_wgs):
        feeder = str(cw["properties"].get("feeder", "UNK"))
        if feeder not in feeders:
            continue
        if not _segment_touches_zone(
            s, keys, expanded, zone_xy, zone_index=zone_index,
        ):
            continue
        for k in keys:
            if k in forbidden or k in expanded:
                continue
            if kua_fault and s.node_feeder.get(k, "").startswith("PDA"):
                continue
            expanded.add(k)

    bfs_q = deque(n for n in expanded if n not in core)
    while bfs_q:
        cur = bfs_q.popleft()
        if cur in open_sw:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb in expanded or nb in forbidden:
                continue
            nb_feeder = s.node_feeder.get(nb, "")
            if scope and nb_feeder and nb_feeder not in scope:
                continue
            if kua_fault and nb_feeder.startswith("PDA"):
                continue
            if _blocks_interconnect_cross_feeder(s, cur, nb):
                continue
            if _is_cross_feeder_tie_hop(s, cur, nb):
                continue
            expanded.add(nb)
            if nb not in open_sw:
                bfs_q.append(nb)

    if not kua_fault and feeders:
        expanded = _expand_zone_conductor_nodes(s, expanded, feeders, forbidden)
        expanded = _expand_protection_device_branches(
            s, expanded, forbidden, feeders,
        )
        bfs_q = deque(n for n in expanded if n not in core)
        while bfs_q:
            cur = bfs_q.popleft()
            if cur in open_sw:
                continue
            for nb in s.adjacency.get(cur, set()):
                if nb in expanded or nb in forbidden:
                    continue
                nb_feeder = s.node_feeder.get(nb, "")
                if scope and nb_feeder and nb_feeder not in scope:
                    continue
                if _blocks_interconnect_cross_feeder(s, cur, nb):
                    continue
                if _is_cross_feeder_tie_hop(s, cur, nb):
                    continue
                expanded.add(nb)
                if nb not in open_sw:
                    bfs_q.append(nb)
        expanded = _expand_gis_zone_lateral_segments(s, expanded, feeders)
        expanded = _expand_captive_feeder_components(
            s, expanded, forbidden, feeders,
        )
        bfs_q = deque(n for n in expanded if n not in core)
        while bfs_q:
            cur = bfs_q.popleft()
            if cur in open_sw:
                continue
            for nb in s.adjacency.get(cur, set()):
                if nb in expanded or nb in forbidden:
                    continue
                nb_feeder = s.node_feeder.get(nb, "")
                if scope and nb_feeder and nb_feeder not in scope:
                    continue
                if _blocks_interconnect_cross_feeder(s, cur, nb):
                    continue
                if _is_cross_feeder_tie_hop(s, cur, nb):
                    continue
                expanded.add(nb)
                if nb not in open_sw:
                    bfs_q.append(nb)
    return expanded


def _expand_protection_device_branches(
    s: NetworkState,
    expanded: set[str],
    forbidden: set[str],
    feeders: set[str],
) -> set[str]:
    """All downstream branches from dropouts/RC inside the outage zone (R42).

    PDA meshed lines fork at protection devices; a single load-side trace can
    miss a sibling branch (e.g. PDA03F-004)."""
    if not expanded or not feeders:
        return expanded
    open_sw = open_isolation_nodes(s)
    zone = set(expanded)
    changed = True
    while changed:
        changed = False
        device_nodes: set[str] = set()
        for sw in s.switches:
            props = sw["properties"]
            if props.get("feeder") not in feeders:
                continue
            node = s.switch_node.get(props["id"])
            if node:
                device_nodes.add(node)
        for rc in s.reclosers:
            props = rc["properties"]
            if props.get("feeder") not in feeders:
                continue
            node = s.recloser_node.get(props["id"])
            if node:
                device_nodes.add(node)

        for dev in list(zone & device_nodes):
            feeder = s.node_feeder.get(dev, "")
            if feeder not in feeders:
                continue
            mesh = _feeder_mesh_nodes(s, feeder)
            dist = (
                _feeder_cb_hop_distance(s, feeder)
                if feeder.startswith("PDA") else {}
            )
            dev_hop = dist.get(dev)
            src_walls: set[str] = set()
            forbidden_hop: set[str] = set()
            if dev_hop is not None:
                forbidden_hop = {n for n in mesh if dist.get(n, 0) < dev_hop}
            for nb in s.adjacency.get(dev, set()):
                if nb not in mesh:
                    continue
                if nb in forbidden:
                    src_walls.add(nb)
                elif dev_hop is not None and dist.get(nb, dev_hop) < dev_hop:
                    src_walls.add(nb)
            walls = src_walls | forbidden_hop | ({dev} if dev in open_sw else set())
            for nb in s.adjacency.get(dev, set()):
                if nb in zone or nb not in mesh:
                    continue
                if nb in src_walls:
                    continue
                branch = _bfs_fault_expand(
                    s, nb,
                    walls=walls,
                    stop_at=open_sw,
                    forbidden=set(),
                    mesh=mesh,
                )
                new_nodes = branch - zone
                if new_nodes:
                    zone |= branch
                    changed = True
            if feeder.startswith("PDA") and dev_hop is not None:
                traced = _pda_trace_line_end_corridors(s, zone, dev, feeder)
                if traced - zone:
                    zone = traced
                    changed = True
    return zone


def _active_cb_nodes(s: NetworkState) -> set[str]:
    """Graph nodes of energised source circuit breakers."""
    feeder_off = {
        feeder for feeder, cb_set in s.feeder_cbs.items()
        if cb_set and all(s.cb_status.get(fid, 1) == 0 for fid in cb_set)
    }
    nodes: set[str] = set()
    for fid, node in s.cb_node.items():
        feeder = s.cb_feeder.get(fid, "UNK")
        if s.cb_status.get(fid, 1) == 1 and feeder not in feeder_off:
            nodes.add(node)
    return nodes


def _node_dist(s: NetworkState, a: str, b: str) -> float:
    ax, ay = s.node_xy[a]
    bx, by = s.node_xy[b]
    return math.hypot(ax - bx, ay - by)


def _kua_feeder_hop_from_seed(
    s: NetworkState,
    feeder: str,
    *,
    skip_open_switch_ids: frozenset[str] | None = None,
) -> dict[str, int]:
    """Hop counts on the KUA feeder mesh from the line-end seed (R38)."""
    seed = _kua_source_seed_node(s, feeder)
    if not seed:
        return {}
    grid_ties = _kua_grid_tie_nodes(s, feeder)
    open_sw = open_isolation_nodes(s)
    if skip_open_switch_ids:
        open_sw -= {
            s.switch_node[fid]
            for fid in skip_open_switch_ids
            if fid in s.switch_node
        }
    dist: dict[str, int] = {seed: 0}
    queue: deque[str] = deque([seed])
    while queue:
        cur = queue.popleft()
        if cur in open_sw and cur != seed:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb in dist:
                continue
            if s.node_feeder.get(nb, "").startswith("PDA"):
                continue
            if not _kua_trace_may_enter(s, nb, feeder, grid_ties):
                continue
            if _is_cross_feeder_tie_hop(s, cur, nb):
                continue
            if _is_kua_pda_boundary_hop(s, cur, nb):
                continue
            dist[nb] = dist[cur] + 1
            if nb in open_sw:
                continue
            queue.append(nb)
    return dist


def _kua_restoration_hop_from_seed(
    s: NetworkState,
    feeder: str,
    sw_status: dict[str, int] | None = None,
) -> dict[str, int]:
    """Hop map for line-end restore — restoration sectionalisers do not block hops."""
    skip = _kua_line_end_restoration_sectional_ids(s, sw_status)
    return _kua_feeder_hop_from_seed(s, feeder, skip_open_switch_ids=skip)


def _kua_mesh_allowed(s: NetworkState, feeder: str) -> set[str]:
    """KUA feeder mesh plus PDA grid-tie endpoint nodes (R38)."""
    return set(s._feeder_keys.get(feeder, [])) | set(
        _feeder_grid_interconnect_nodes(s, feeder),
    )


def _kua_live_end_seed(s: NetworkState, fault: str, feeder: str) -> str | None:
    """Graph node that energises the live side of ``fault``.

    When the fault sits seed-ward of the PDA tie(s), the live end is the remote
    line-end seed.  When the fault is past the tie(s), the live end is the far
    bus beyond the fault (max hop from the line-end seed)."""
    hop = _kua_feeder_hop_from_seed(s, feeder)
    fault_hop = hop.get(fault)
    if fault_hop is None:
        return _kua_source_seed_node(s, feeder)
    ties = _kua_grid_tie_nodes(s, feeder)
    if any(hop.get(t, -1) > fault_hop for t in ties):
        return _kua_source_seed_node(s, feeder)
    if not hop:
        return _kua_source_seed_node(s, feeder)
    return max(hop, key=hop.get)


def _kua_trace_from_live_end(
    s: NetworkState, fault: str, feeder: str, live_end: str,
) -> set[str]:
    """Nodes on the live side: reachable from ``live_end`` without crossing ``fault``."""
    open_sw = open_isolation_nodes(s)
    mesh = _kua_mesh_allowed(s, feeder)
    grid_ties = _kua_grid_tie_nodes(s, feeder)
    zone: set[str] = {live_end}
    queue: deque[str] = deque([live_end])
    while queue:
        cur = queue.popleft()
        if cur in open_sw and cur != live_end:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb in zone or nb == fault:
                continue
            if nb not in mesh:
                continue
            if s.node_feeder.get(nb, "").startswith("PDA"):
                continue
            if not _kua_trace_may_enter(s, nb, feeder, grid_ties):
                continue
            if _is_kua_pda_boundary_hop(s, cur, nb):
                continue
            if _is_cross_feeder_tie_hop(s, cur, nb):
                continue
            zone.add(nb)
            if nb not in open_sw:
                queue.append(nb)
    for n in list(zone):
        for nb in s.adjacency.get(n, set()):
            if nb in open_sw:
                zone.add(nb)
    return zone


def _kua_source_side_nodes(
    s: NetworkState, fault: str, feeder: str,
) -> set[str]:
    """Nodes on the remote live side of ``fault`` (R27/R38)."""
    live_end = _kua_live_end_seed(s, fault, feeder)
    if not live_end:
        return {fault}
    zone = _kua_trace_from_live_end(s, fault, feeder, live_end)
    zone.add(fault)
    return zone


def _kua_load_side_nodes(
    s: NetworkState, fault: str, feeder: str,
) -> set[str]:
    """Nodes on the PDA-ward (de-energized) side of ``fault`` for KUA feeders.

    Shortest-path corridors to *every* registered PDA grid tie, then full
    mesh expansion minus the live seed partition.  PDA feeders are never entered."""
    source = _kua_source_side_nodes(s, fault, feeder)
    grid_ties = _kua_grid_tie_nodes(s, feeder)
    open_sw = open_isolation_nodes(s)
    mesh = _kua_mesh_allowed(s, feeder)

    zone: set[str] = {fault}
    for tie in grid_ties:
        zone |= _shortest_path_in_zone(
            s, fault, {tie}, mesh, open_barrier=open_sw,
        )

    queue: deque[str] = deque(n for n in zone if n not in open_sw)
    while queue:
        cur = queue.popleft()
        if cur in open_sw:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb in zone or nb in source:
                continue
            if s.node_feeder.get(nb, "").startswith("PDA"):
                continue
            if _is_kua_pda_boundary_hop(s, cur, nb):
                continue
            if s.node_feeder.get(nb, "") != feeder and nb not in grid_ties:
                continue
            if _is_cross_feeder_tie_hop(s, cur, nb):
                continue
            zone.add(nb)
            if nb not in open_sw:
                queue.append(nb)
    return zone


def _core_fault_section_for_feeder(
    s: NetworkState, feeder: str, fault: str | None = None,
) -> set[str]:
    """Directional dark section for ``feeder`` at the fault coordinates (R39)."""
    fn = _fault_node_on_feeder(s, feeder, fault)
    if not fn:
        return set()
    saved_node = s.fault_node
    saved_feeder = s.fault_feeder
    try:
        s.fault_node = fn
        s.fault_feeder = feeder
        return _core_fault_section_nodes(s)
    finally:
        s.fault_node = saved_node
        s.fault_feeder = saved_feeder


def _kua_is_source_node(
    s: NetworkState, fault: str, node: str, feeder: str,
) -> bool:
    """True when ``node`` lies on the remote line-end (energized) side of ``fault``."""
    return node in _kua_source_side_nodes(s, fault, feeder)


def _kua_source_side_neighbor(
    s: NetworkState, fault: str, neighbor: str, feeder: str,
) -> bool:
    return _kua_is_source_node(s, fault, neighbor, feeder)


def _fault_context_energization(s: NetworkState, *, ignore_fault: bool = True) -> set[str]:
    """Energization model for directional fault-zone tracing (R27).

    KUA faults: only the far line-end CB feeds — PDA-side paths are load.
    Other feeders: full physical energization."""
    feeder = s.fault_feeder or (
        s.node_feeder.get(s.fault_node, "") if s.fault_node else ""
    )
    saved_fault = s.fault_node
    if ignore_fault:
        s.fault_node = None
    try:
        if _is_kua_feeder(feeder):
            return _kua_feeder_energization_ex(s, feeder)
        return compute_energization(s)
    finally:
        s.fault_node = saved_fault


def _fault_context_cb_nodes(s: NetworkState) -> set[str]:
    """Active source CB graph nodes relevant to the fault feeder."""
    feeder = s.fault_feeder or (
        s.node_feeder.get(s.fault_node, "") if s.fault_node else ""
    )
    if _is_kua_feeder(feeder):
        nodes: set[str] = set()
        for fid in s.feeder_cbs.get(feeder, set()):
            if s.cb_status.get(fid, 1) == 1 and fid in s.cb_node:
                nodes.add(s.cb_node[fid])
        return nodes
    return _active_cb_nodes(s)


def _feeder_active_cb_nodes(s: NetworkState, feeder: str) -> set[str]:
    """Energised source CB graph nodes for a single feeder."""
    cb_set = s.feeder_cbs.get(feeder, set())
    if cb_set and all(s.cb_status.get(fid, 1) == 0 for fid in cb_set):
        return set()
    return {
        s.cb_node[fid]
        for fid in cb_set
        if s.cb_status.get(fid, 1) == 1 and fid in s.cb_node
    }


def _compute_feeder_cb_hop_distance(
    s: NetworkState, feeder: str,
) -> dict[str, int]:
    """Shortest hop count from ``feeder`` source CB(s) on the feeder mesh (R40)."""
    cb_nodes = _feeder_active_cb_nodes(s, feeder)
    if not cb_nodes:
        return {}
    mesh = _feeder_mesh_nodes(s, feeder)
    open_barrier = open_isolation_nodes(s)
    dist: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque((n, 0) for n in cb_nodes)
    while queue:
        cur, d = queue.popleft()
        if cur in dist or cur not in mesh:
            continue
        dist[cur] = d
        if cur in open_barrier and cur not in cb_nodes:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb in dist or nb not in mesh:
                continue
            if nb in open_barrier and nb not in cb_nodes:
                continue
            if _blocks_interconnect_cross_feeder(s, cur, nb):
                continue
            if _is_cross_feeder_tie_hop(s, cur, nb):
                continue
            queue.append((nb, d + 1))
    return dist


def _feeder_nodes_reachable_from_cb(
    s: NetworkState,
    feeder: str,
    *,
    wall: str | None = None,
) -> set[str]:
    """Graph nodes energisable from ``feeder`` CB(s) on the feeder mesh (R40).

    Open tie/RC nodes may be included but are not traversed (R37)."""
    cb_nodes = _feeder_active_cb_nodes(s, feeder)
    if not cb_nodes:
        return set()
    mesh = _feeder_mesh_nodes(s, feeder)
    open_sw = open_isolation_nodes(s)
    reached: set[str] = set(cb_nodes)
    queue: deque[str] = deque(cb_nodes)
    while queue:
        cur = queue.popleft()
        if cur in open_sw and cur not in cb_nodes:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb in reached or nb not in mesh:
                continue
            if wall and nb == wall:
                continue
            if _blocks_interconnect_cross_feeder(s, cur, nb):
                continue
            if _is_cross_feeder_tie_hop(s, cur, nb):
                continue
            reached.add(nb)
            if nb in open_sw:
                continue
            queue.append(nb)
    return reached


def _feeder_cb_hop_distance(s: NetworkState, feeder: str) -> dict[str, int]:
    if not feeder:
        return {}
    return _cc_get(
        s, f"cb_hops_{feeder}",
        lambda: _compute_feeder_cb_hop_distance(s, feeder),
    )


def _source_closer_than_fault(
    s: NetworkState, fault: str, feeder: str,
) -> set[str]:
    """Nodes on the source side of ``fault`` (toward the feeder CB, R37/R40).

    Hop-count from CB on the feeder mesh; if the fault node is unreachable,
    compare hop counts at fault neighbours, then fall back to CB-originated BFS."""
    mesh = _feeder_mesh_nodes(s, feeder)
    dist = _compute_feeder_cb_hop_distance(s, feeder)
    fault_dist = dist.get(fault)
    if fault_dist is not None:
        return {n for n, d in dist.items() if d < fault_dist and n in mesh}

    neighbor_hops = {
        nb: dist[nb]
        for nb in s.adjacency.get(fault, set())
        if nb in dist and nb in mesh
    }
    if neighbor_hops:
        min_hop = min(neighbor_hops.values())
        return {n for n, d in dist.items() if d <= min_hop and n in mesh}

    return _feeder_nodes_reachable_from_cb(s, feeder, wall=fault) - {fault}


def _pda_line_end_targets(
    s: NetworkState, feeder: str, fault_hop: int, dist: dict[str, int],
) -> set[str]:
    """Line-end / far-bus nodes downstream of ``fault_hop`` on a PDA feeder (R41)."""
    mesh = _feeder_mesh_nodes(s, feeder)
    if not dist:
        return set()
    max_h = max(dist.values())
    targets: set[str] = set()
    for n in mesh:
        nh = dist.get(n, 0)
        if nh <= fault_hop:
            continue
        if nh >= max_h - 12:
            targets.add(n)
            continue
        same_nbs = [
            nb for nb in s.adjacency.get(n, set())
            if s.node_feeder.get(nb) == feeder
        ]
        if len(same_nbs) <= 1:
            targets.add(n)
    return targets


def _pda_trace_line_end_corridors(
    s: NetworkState,
    zone: set[str],
    fault: str,
    feeder: str,
) -> set[str]:
    """Shortest-path corridors to load-side line ends not yet in ``zone`` (R45).

    Meshed rings may require a brief hop dip below ``fault``; paths within
    ``_PDA_RING_DIP_SLACK`` are accepted so far line ends are included without
    flooding the entire feeder."""
    mesh = _feeder_mesh_nodes(s, feeder)
    dist = _feeder_cb_hop_distance(s, feeder)
    fault_hop = dist.get(fault, 0)
    open_sw = open_isolation_nodes(s)
    out = set(zone)
    min_allowed = fault_hop - _PDA_RING_DIP_SLACK
    for tgt in _pda_line_end_targets(s, feeder, fault_hop, dist):
        if tgt in out:
            continue
        path = _shortest_path_in_zone(
            s, fault, {tgt}, mesh, open_barrier=open_sw,
        )
        if tgt not in path:
            continue
        if min(dist.get(n, fault_hop) for n in path) < min_allowed:
            continue
        out |= path
    return out


def _pda_load_side_zone(
    s: NetworkState, fault: str, feeder: str,
) -> set[str]:
    """Load-side outage for PDA feeders — corridors to line ends plus mesh BFS (R41/R45)."""
    mesh = _feeder_mesh_nodes(s, feeder)
    dist = _feeder_cb_hop_distance(s, feeder)
    fault_hop = dist.get(fault, 0)
    forbidden_hop = {n for n in mesh if dist.get(n, 0) < fault_hop}
    open_sw = open_isolation_nodes(s)
    zone: set[str] = {fault}

    src_neighbors = {
        nb for nb in s.adjacency.get(fault, set())
        if nb in mesh and dist.get(nb, fault_hop) < fault_hop
    }
    hop_walls = src_neighbors | forbidden_hop
    for seed in s.adjacency.get(fault, set()):
        if seed in src_neighbors or seed not in mesh:
            continue
        zone |= _bfs_fault_expand(
            s, seed,
            walls=hop_walls,
            stop_at=open_sw,
            forbidden={fault},
            mesh=mesh,
        )

    zone = _pda_connect_load_hop_islands(s, zone, fault, feeder)
    zone = _pda_trace_line_end_corridors(s, zone, fault, feeder)
    return zone


def _pda_connect_source_hop_islands(
    s: NetworkState, zone: set[str], fault: str, feeder: str, fault_hop: int,
) -> set[str]:
    """Merge source-hop islands touching ``zone`` (R43).

    Ring/mesh PDA feeders can split the source partition; any component with
    hop < ``fault_hop`` that touches the traced corridor belongs in the outage."""
    mesh = _feeder_mesh_nodes(s, feeder)
    dist = _feeder_cb_hop_distance(s, feeder)
    source_hop = {n for n in mesh if dist.get(n, 0) < fault_hop}
    if not source_hop:
        return zone
    expanded = set(zone)
    remaining = set(source_hop)
    while remaining:
        start = next(iter(remaining))
        comp: set[str] = {start}
        queue: deque[str] = deque([start])
        remaining.discard(start)
        while queue:
            cur = queue.popleft()
            for nb in s.adjacency.get(cur, set()):
                if nb not in source_hop or nb in comp:
                    continue
                comp.add(nb)
                remaining.discard(nb)
                queue.append(nb)
        if comp & expanded:
            expanded |= comp
    return expanded


def _pda_source_corridor_to_cb(
    s: NetworkState, fault: str, feeder: str,
) -> set[str]:
    """Source-ward dark corridor on PDA: fault back to CB if path is clear (R43).

    Uses only nodes with CB-hop count strictly less than ``fault`` so ring
    circuits do not bleed through the load-side.  Open tie/dropout/RC on the
    path stops the zone there; CB graph nodes stay energised (lit)."""
    mesh = _feeder_mesh_nodes(s, feeder)
    dist = _feeder_cb_hop_distance(s, feeder)
    fault_hop = dist.get(fault)
    if fault_hop is None:
        return {fault}

    source_allowed = {n for n in mesh if dist.get(n, 0) < fault_hop}
    source_allowed.add(fault)
    open_sw = open_isolation_nodes(s)
    cb_nodes = _feeder_active_cb_nodes(s, feeder) & mesh
    if not cb_nodes:
        return {fault}

    path_to_cb = _shortest_path_in_zone(
        s, fault, cb_nodes, source_allowed, open_barrier=open_sw,
    )
    if path_to_cb & cb_nodes:
        return path_to_cb - cb_nodes

    open_on_source = (open_sw & source_allowed) - {fault}
    zone: set[str] = {fault}
    if open_on_source:
        zone |= _paths_to_open_targets(
            s, fault, open_on_source, [source_allowed], open_barrier=open_sw,
        )
        if len(zone) > 1:
            zone = _pda_connect_source_hop_islands(s, zone, fault, feeder, fault_hop)
            return zone - cb_nodes

    load_forbidden = {n for n in mesh if dist.get(n, fault_hop) >= fault_hop}
    for seed in s.adjacency.get(fault, set()):
        if seed not in source_allowed or seed in load_forbidden:
            continue
        zone |= _bfs_fault_expand(
            s, seed,
            walls={fault},
            stop_at=open_sw,
            forbidden=load_forbidden,
            mesh=source_allowed,
        )
    zone = _pda_connect_source_hop_islands(s, zone, fault, feeder, fault_hop)
    return zone - cb_nodes


def _pda_connect_load_hop_islands(
    s: NetworkState, zone: set[str], fault: str, feeder: str,
) -> set[str]:
    """Merge hop>fault islands that touch ``zone`` — fixes main-line gaps (R40).

    Meshed PDA lines can split the load-side into hop islands when hop-based
    forbidden nodes block BFS; any load-hop component touching the traced zone
    is part of the same outage."""
    mesh = _feeder_mesh_nodes(s, feeder)
    dist = _feeder_cb_hop_distance(s, feeder)
    fault_hop = dist.get(fault, 0)
    load_hop = {n for n in mesh if dist.get(n, 0) > fault_hop}
    if not load_hop:
        return zone
    expanded = set(zone)
    remaining = set(load_hop)
    while remaining:
        start = next(iter(remaining))
        comp: set[str] = {start}
        queue: deque[str] = deque([start])
        remaining.discard(start)
        while queue:
            cur = queue.popleft()
            for nb in s.adjacency.get(cur, set()):
                if nb not in load_hop or nb in comp:
                    continue
                comp.add(nb)
                remaining.discard(nb)
                queue.append(nb)
        if comp & expanded:
            expanded |= comp
    return expanded


def _source_side_neighbor(s: NetworkState, fault: str, neighbor: str) -> bool:
    """True when ``neighbor`` lies on the source side (R21/R27/R37/R40)."""
    feeder = s.fault_feeder or s.node_feeder.get(fault, "")
    if _is_kua_feeder(feeder):
        return _kua_source_side_neighbor(s, fault, neighbor, feeder)
    dist = _feeder_cb_hop_distance(s, feeder)
    fh = dist.get(fault)
    nh = dist.get(neighbor)
    if fh is not None and nh is not None:
        return nh < fh
    source_part = _feeder_nodes_reachable_from_cb(s, feeder, wall=fault)
    return neighbor in source_part


def _neighbor_leads_to_source(s: NetworkState, fault: str, neighbor: str) -> bool:
    """Legacy CB reachability check — prefer ``_source_side_neighbor`` for display."""
    open_sw = open_switch_nodes(s)
    if neighbor in open_sw:
        return False
    cb_nodes = _active_cb_nodes(s)
    if neighbor in cb_nodes:
        return True
    seen: set[str] = {fault}
    queue: deque[str] = deque([neighbor])
    seen.add(neighbor)
    while queue:
        cur = queue.popleft()
        if cur in cb_nodes:
            return True
        for nb in s.adjacency.get(cur, set()):
            if nb in seen or nb in open_sw:
                continue
            seen.add(nb)
            queue.append(nb)
    return False


def _is_cross_feeder_tie_hop(s: NetworkState, cur: str, nb: str) -> bool:
    """True when ``nb`` is a tie node on a different feeder than ``cur``."""
    if nb not in _tie_boundary_nodes(s):
        return False
    return s.node_feeder.get(cur, "") != s.node_feeder.get(nb, "")


def _bfs_fault_expand(
    s: NetworkState,
    start: str,
    *,
    walls: set[str],
    stop_at: set[str],
    forbidden: set[str] | None = None,
    block_cross_feeder: bool = False,
    mesh: set[str] | None = None,
) -> set[str]:
    """BFS expansion for fault-zone tracing.

    ``walls``: nodes that cannot be entered.
    ``stop_at``: nodes included but not expanded beyond (e.g. tie switch, CB,
    open switch used as an existing isolation point).
    ``forbidden``: nodes excluded from the walk (other directional zone).
    ``block_cross_feeder``: on source-side walks, do not hop through a tie
    onto a neighbouring feeder (fault zone stays on the fault feeder).
    ``mesh``: when set, expansion stays on these nodes (PDA feeder mesh, R40)."""
    forb = forbidden or set()
    if start in walls or start in forb:
        return set()
    zone: set[str] = {start}
    queue: deque[str] = deque([start])
    while queue:
        cur = queue.popleft()
        if cur in stop_at and cur != start:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb in zone or nb in walls or nb in forb:
                continue
            if mesh is not None and nb not in mesh:
                continue
            if _blocks_interconnect_cross_feeder(s, cur, nb):
                continue
            if block_cross_feeder and _is_cross_feeder_tie_hop(s, cur, nb):
                continue
            zone.add(nb)
            queue.append(nb)
    return zone


def open_dropout_nodes(s: NetworkState) -> set[str]:
    """Graph nodes of open F-coded dropout switches."""
    nodes: set[str] = set()
    for sw in s.switches:
        if sw["properties"].get("deviceClass") != "dropout":
            continue
        fid = sw["properties"]["id"]
        if s.switch_status.get(fid, 1) == 0 and fid in s.switch_node:
            nodes.add(s.switch_node[fid])
    return nodes


def open_non_dropout_switch_nodes(s: NetworkState) -> set[str]:
    """Open switch nodes excluding dropouts (sectionalisers / tie switches)."""
    return open_switch_nodes(s) - open_dropout_nodes(s)


def _first_tie_ahead(
    s: NetworkState, start: str, blocked: set[str],
) -> str | None:
    """First tie-switch node reachable from ``start`` without entering ``blocked``."""
    seen: set[str] = set(blocked) | {start}
    queue: deque[str] = deque([start])
    while queue:
        cur = queue.popleft()
        if cur != start and cur in _tie_boundary_nodes(s):
            return cur
        for nb in s.adjacency.get(cur, set()):
            if nb not in seen:
                seen.add(nb)
                queue.append(nb)
    return None


def _tie_is_open(s: NetworkState, tie_node: str) -> bool:
    for fid in s.tie_switch_ids:
        if s.switch_node.get(fid) == tie_node and s.switch_status.get(fid, 1) == 0:
            return True
    return False


def _tie_provides_backfeed(
    s: NetworkState,
    tie_node: str,
    isolation_wall: set[str],
    fault: str,
) -> bool:
    """True when load-side beyond a closed tie reaches supply via current switches."""
    energized = compute_energization(s)
    blocked = set(isolation_wall) | {fault, tie_node}
    queue: deque[str] = deque()
    seen: set[str] = set(blocked)
    for nb in s.adjacency.get(tie_node, set()):
        if nb not in seen:
            seen.add(nb)
            queue.append(nb)
    while queue:
        cur = queue.popleft()
        if cur in energized:
            return True
        for nb in s.adjacency.get(cur, set()):
            if nb not in seen:
                seen.add(nb)
                queue.append(nb)
    return False


def _bfs_downstream_branch(
    s: NetworkState, start: str, forbidden: set[str],
) -> set[str]:
    """All nodes downstream from ``start`` on the same branch (full dark extent)."""
    zone: set[str] = {start}
    queue: deque[str] = deque([start])
    while queue:
        cur = queue.popleft()
        for nb in s.adjacency.get(cur, set()):
            if nb in zone or nb in forbidden:
                continue
            if _is_cross_feeder_tie_hop(s, cur, nb):
                continue
            zone.add(nb)
            queue.append(nb)
    return zone


def _load_side_zone_from_fault(
    s: NetworkState, fault: str, source_zone: set[str],
) -> set[str]:
    """Full load-side outage from ``fault`` until open tie/RC (R37 rule 1)."""
    feeder = s.fault_feeder or s.node_feeder.get(fault, "")
    if _is_kua_feeder(feeder):
        return _kua_load_side_nodes(s, fault, feeder)

    if feeder.startswith("PDA"):
        return _pda_load_side_zone(s, fault, feeder)

    mesh = _feeder_mesh_nodes(s, feeder)
    forbidden = _source_closer_than_fault(s, fault, feeder)
    open_sw = open_isolation_nodes(s)
    load_seeds = [
        nb for nb in s.adjacency.get(fault, set())
        if nb not in forbidden and nb in mesh
    ]
    zone: set[str] = {fault}
    for seed in load_seeds:
        zone |= _bfs_fault_expand(
            s, seed,
            walls=set(),
            stop_at=open_sw,
            forbidden=forbidden | {fault},
            mesh=mesh,
        )
    if len(zone) <= 1:
        zone = _nodes_load_side_of_fault(s, fault)
    return zone


def _expand_load_side_zone(
    s: NetworkState, fault: str, source_zone: set[str],
) -> set[str]:
    """Load-side fault section with dropout / tie switching rules (R19).

    Used for back-feed restoration trimming after operator switching — not for
    the initial topological outage display (see ``_load_side_zone_from_fault``).

    * Open switch on load path (incl. operator-opened iso ties) → zone stops
      there; nothing beyond an open tie/sectionaliser is included.
    * Open dropout only (no open tie on load) → dropout/tie back-feed rules.
    * No open switches on load path → expand to the next open tie (GIS).
    """
    feeder = s.fault_feeder or s.node_feeder.get(fault, "")
    hop_closer = _source_closer_than_fault(s, fault, feeder)
    forbidden = hop_closer if hop_closer else (source_zone - {fault})
    open_do   = open_dropout_nodes(s)
    open_tie  = open_tie_switch_nodes(s)
    open_sw   = open_isolation_nodes(s)

    reachable = _bfs_fault_expand(
        s, fault, walls=set(), stop_at=set(), forbidden=forbidden,
    )
    open_on_load = (reachable & open_sw) - {fault}

    if not open_on_load:
        return _bfs_fault_expand(
            s, fault, walls=set(), stop_at=open_tie, forbidden=forbidden,
        )

    base = _bfs_fault_expand(
        s, fault, walls=set(), stop_at=open_sw, forbidden=forbidden,
    )

    if open_on_load & open_tie:
        return base

    load_zone: set[str] = set(base)
    for do_node in sorted(base & open_do):
        tie = _first_tie_ahead(s, do_node, forbidden | base - {do_node})
        if tie is None:
            continue

        corridor = _bfs_fault_expand(
            s, do_node, walls=open_sw, stop_at={tie}, forbidden=forbidden,
        )

        if _tie_is_open(s, tie):
            load_zone |= corridor
            load_zone.add(tie)
            continue

        isolation = load_zone | base
        if _tie_provides_backfeed(s, tie, isolation, fault):
            continue

        load_zone |= corridor
        downstream = _bfs_fault_expand(
            s, tie, walls=open_sw, stop_at=set(), forbidden=forbidden,
        )
        load_zone |= downstream

    return load_zone


def _source_zone_from_fault(
    s: NetworkState, fault: str, load_block: set[str] | None = None,
) -> set[str]:
    """Source-side nodes: walk toward source from fault (R21/R27)."""
    feeder = s.fault_feeder or s.node_feeder.get(fault, "")
    open_sw = open_isolation_nodes(s)
    block = load_block if load_block is not None else set()

    if _is_kua_feeder(feeder):
        zone = _kua_source_side_nodes(s, fault, feeder)
        if block:
            zone -= block
        return zone

    source_part = _feeder_nodes_reachable_from_cb(s, feeder, wall=fault)
    zone: set[str] = set(source_part) | {fault}
    for n in list(zone):
        for nb in s.adjacency.get(n, set()):
            if nb in open_sw:
                zone.add(nb)
    if block:
        zone -= block
    return zone


def _nodes_load_side_of_fault(s: NetworkState, fault: str) -> set[str]:
    """Nodes on the load side of ``fault`` (physical source/load partition)."""
    feeder = s.fault_feeder or s.node_feeder.get(fault, "")
    mesh = (
        _feeder_mesh_nodes(s, feeder)
        if feeder and not _is_kua_feeder(feeder) else None
    )
    load_seeds = [
        nb for nb in s.adjacency.get(fault, set())
        if not _source_side_neighbor(s, fault, nb)
        and (mesh is None or nb in mesh)
    ]
    open_sw = open_isolation_nodes(s)
    zone: set[str] = set()
    for seed in load_seeds:
        zone |= _bfs_fault_expand(
            s, seed, walls=set(), stop_at=open_sw, forbidden={fault},
            mesh=mesh,
        )
    if zone:
        return zone
    source_part = _source_zone_from_fault(s, fault, load_block=set())
    all_reach = _bfs_fault_expand(
        s, fault, walls=set(), stop_at=open_sw, forbidden=set(),
        mesh=mesh,
    )
    return all_reach - source_part


def _core_fault_section_nodes(s: NetworkState) -> set[str]:
    """Directional fault section (R19–R21).

    Source/load split uses physical energization; open iso ties shrink the zone.
    Live back-feed updates are applied in ``_display_affected_nodes``."""
    if not s.fault_node:
        return set()
    fault = s.fault_node
    feeder = s.fault_feeder or s.node_feeder.get(fault, "")
    source_zone = _source_zone_from_fault(s, fault)
    load_zone = _load_side_zone_from_fault(s, fault, source_zone)
    if _is_kua_feeder(feeder):
        load_zone |= _source_corridor_to_open_device(s, fault)
    elif feeder.startswith("PDA"):
        load_zone |= _pda_source_corridor_to_cb(
            s, fault, feeder or s.node_feeder.get(fault, ""),
        )
    zone = load_zone if load_zone else {fault}
    return _trim_zone_at_protecting_reclosers(s, zone, feeder, fault)


def compute_fault_affected_nodes(s: NetworkState) -> set[str]:
    """Fault zone on main line plus dependent branch/lateral meshes (R16–R17/R39)."""
    scope = _fault_target_feeders(s)
    if not s.fault_node or not scope:
        return set()
    core: set[str] = set()
    for feeder in sorted(scope):
        core |= _core_fault_section_for_feeder(s, feeder)
    expanded = _expand_dependent_branch_nodes(s, core)
    expanded = _filter_nodes_to_feeders(s, expanded, scope)
    # R68: re-apply RC hop floor after lateral expansion (mesh bleed).
    trimmed: set[str] = set()
    for feeder in sorted(scope):
        fault = _fault_node_on_feeder(s, feeder) or s.fault_node
        if not fault:
            continue
        feeder_nodes = {
            n for n in expanded
            if s.node_feeder.get(n) == feeder or n == fault
        }
        trimmed |= _trim_zone_at_protecting_reclosers(
            s, feeder_nodes, feeder, fault,
        )
    return trimmed if trimmed else expanded


def _snap_latlon_to_node(s: NetworkState, lat: float, lon: float) -> tuple[str | None, str | None]:
    """Snap WGS84 coordinates to nearest conductor graph node."""
    xu, yu = to_utm(lon, lat)
    snap_feeder, snap_node = find_nearest_conductor_snap(s, xu, yu)
    nearest = snap_node or find_nearest(s, xu, yu)
    if snap_feeder and nearest:
        on_feeder = find_nearest_in_feeder(s, xu, yu, snap_feeder, fallback=False)
        if on_feeder:
            nearest = on_feeder
    feeder = snap_feeder or (s.node_feeder.get(nearest, "UNK") if nearest else None)
    return nearest, feeder


def _bfs_path_nodes(s: NetworkState, start: str, end: str) -> set[str]:
    """Shortest-path node set between two graph nodes (BFS)."""
    if start == end:
        return {start}
    parent: dict[str, str] = {}
    queue: deque[str] = deque([start])
    seen: set[str] = {start}
    while queue:
        cur = queue.popleft()
        for nb in s.adjacency.get(cur, set()):
            if nb in seen:
                continue
            seen.add(nb)
            parent[nb] = cur
            if nb == end:
                path: set[str] = {end}
                walk = end
                while walk != start:
                    walk = parent[walk]
                    path.add(walk)
                return path
            queue.append(nb)
    return {start, end}


def compute_maintenance_zone_nodes(s: NetworkState) -> set[str]:
    """Work zone between maintenance start/end plus dependent laterals (R20)."""
    if not s.maint_active or not s.maint_start_node or not s.maint_end_node:
        return set()
    core = _bfs_path_nodes(s, s.maint_start_node, s.maint_end_node)
    return _expand_dependent_branch_nodes(s, core)


def _operator_topology_changed(s: NetworkState) -> bool:
    """True when any switch/recloser differs from the pre-fault snapshot (R31)."""
    if not s.fault_node and not s.maint_active:
        return False
    snap_sw = s.snapshot_switch
    snap_rc = s.snapshot_recloser
    if snap_sw is None and snap_rc is None:
        return False
    snap_sw = snap_sw or {}
    snap_rc = snap_rc or {}
    for fid, st in s.switch_status.items():
        if snap_sw.get(fid, st) != st:
            return True
    for fid, st in s.recloser_status.items():
        if snap_rc.get(fid, st) != st:
            return True
    return False


def _display_live_topology(s: NetworkState) -> bool:
    """True when map polygons/conductors follow live switch/RC state (R31/R48)."""
    return bool(s.fault_node or s.maint_active) and _operator_topology_changed(s)


def _operational_zone_base(s: NetworkState) -> set[str]:
    """Topological fault + maintenance zone before live operator trim."""
    base: set[str] = set()
    if s.fault_node:
        base |= _cc_get(s, "fault_topo", lambda: compute_fault_affected_nodes(s))
    if s.maint_active:
        base |= compute_maintenance_zone_nodes(s)
    return base


def _display_feeder_scope(s: NetworkState) -> set[str]:
    """Feeders whose outage overlay may be shown for the active event."""
    scope: set[str] = set()
    if s.fault_node:
        scope |= set(_fault_target_feeders(s))
    if s.maint_feeder:
        scope.add(s.maint_feeder)
    return scope


def _plan_steps_fingerprint(steps: list[dict]) -> tuple:
    """Stable identity for cached switching-plan steps (R53)."""
    return tuple(
        (st.get("action"), st.get("switchId"), st.get("planEffect"))
        for st in steps
    )


def _clear_switching_plan_runtime(s: NetworkState) -> None:
    """Reset operator plan-execute progress (R53)."""
    s.switching_plan_steps = []
    s.switching_plan_executed = 0
    s.kua_line_end_display_ack = False


def _store_switching_plan_runtime(s: NetworkState, steps: list[dict]) -> None:
    """Cache generated plan steps for ``/switching-plan/execute`` (R53)."""
    new_fp = _plan_steps_fingerprint(steps)
    old_fp = _plan_steps_fingerprint(s.switching_plan_steps)
    s.switching_plan_steps = list(steps)
    if new_fp != old_fp:
        s.switching_plan_executed = 0
        s.kua_line_end_display_ack = False


def _switching_plan_step_at(s: NetworkState, step_idx: int) -> dict | None:
    """Return the cached plan step for a 1-based execute index."""
    i = step_idx - 1
    steps = s.switching_plan_steps
    if 0 <= i < len(steps):
        return steps[i]
    return None


def _kua_line_end_display_acknowledged(s: NetworkState) -> bool:
    """True after operator confirmed KUA line-end back-feed on the plan (R53)."""
    return bool(s.kua_line_end_display_ack)


def _backfeed_restoration_active(s: NetworkState) -> bool:
    """True after a restoration step returns supply into the work zone (R49/R53).

    Isolation-only (RC trip / sectional OPEN) keeps the full outage polygon until
    the operator acknowledges KUA line-end NOTE or closes a cross-feeder tie."""
    if not _operator_topology_changed(s):
        return False
    snap_sw = s.snapshot_switch or {}
    for fid in s.interconnect_switch_ids:
        if s.switch_status.get(fid, 1) == 1 and snap_sw.get(fid, 1) == 0:
            return True
    primary = s.fault_feeder or s.maint_feeder or ""
    if _is_kua_feeder(primary):
        for fid in _sectionalizing_switch_ids(s):
            if s.switch_status.get(fid, 1) == 0 and snap_sw.get(fid, 1) == 1:
                return _kua_line_end_display_acknowledged(s)
    if s.maint_active:
        base = _operational_zone_base(s)
        if base & _compute_live_energization(s):
            return True
    return False


def _display_restoration_live(s: NetworkState) -> bool:
    """True when the map should show live supply colours and trimmed polygons."""
    return bool(s.fault_node or s.maint_active) and _backfeed_restoration_active(s)


def _operator_isolation_active(s: NetworkState) -> bool:
    """True when the operator opened a switch/recloser since the fault snapshot."""
    if not s.fault_node:
        return False
    snap_sw = s.snapshot_switch
    snap_rc = s.snapshot_recloser
    if snap_sw is None and snap_rc is None:
        return False
    snap_sw = snap_sw or {}
    snap_rc = snap_rc or {}
    work = _cc_get(s, "fault_topo", lambda: compute_fault_affected_nodes(s))
    for fid, st in s.switch_status.items():
        if st == 0 and snap_sw.get(fid, 1) == 1:
            node = s.switch_node.get(fid)
            if node and node in work:
                return True
    for fid, st in s.recloser_status.items():
        if st == 0 and snap_rc.get(fid, 1) == 1:
            node = s.recloser_node.get(fid)
            if node and node in work:
                return True
    return False


def _load_side_backfeed_restored(s: NetworkState, fault: str) -> set[str]:
    """Load-side nodes that regained physical supply via back-feed (R21/R29)."""
    source_zone = _source_zone_from_fault(s, fault)
    load_zone = _expand_load_side_zone(s, fault, source_zone)
    load_zone = _expand_dependent_branch_nodes(s, load_zone | {fault})
    physical_on = compute_energization(s)
    return load_zone & physical_on


def _display_affected_nodes(s: NetworkState) -> set[str]:
    """Map display — directional fault zone; live back-feed trim after iso (R21/R29)."""
    return _cc_get(s, "display_affected", lambda: _compute_display_affected(s))


def _compute_display_affected(s: NetworkState) -> set[str]:
    """Uncached display affected set (see ``_display_affected_nodes``)."""
    if not s.fault_node and not s.maint_active:
        return set()

    base = _operational_zone_base(s)
    if not _display_restoration_live(s):
        return base

    live_on = compute_live_energization(s)
    all_dark = set(s.adjacency.keys()) - live_on
    dark_core = base & all_dark
    if s.fault_node:
        if s.fault_node not in live_on:
            dark_core.add(s.fault_node)
        # R62: keep blocked main-line section until operator recloses iso devices
        envelope = _isolation_envelope_nodes(s, s.fault_node)
        dark_core |= envelope & base
        feeder = s.fault_feeder or s.maint_feeder or ""
        if _is_kua_feeder(feeder) and _active_backfeed_source_feeders(s):
            dark_core |= _kua_residual_outage_nodes(s, feeder) & base
    if not dark_core:
        return set()
    return dark_core - live_on


def _graph_hops(s: NetworkState, a: str, b: str, limit: int = 12) -> int:
    """Shortest-path hop count between graph nodes, or ``limit + 1`` if unreachable."""
    if not a or not b:
        return limit + 1
    if a == b:
        return 0
    seen: set[str] = {a}
    queue: deque[tuple[str, int]] = deque([(a, 0)])
    while queue:
        cur, d = queue.popleft()
        if d >= limit:
            continue
        for nb in s.adjacency.get(cur, set()):
            if nb == b:
                return d + 1
            if nb not in seen:
                seen.add(nb)
                queue.append((nb, d + 1))
    return limit + 1


def _device_graph_node(s: NetworkState, fid: str) -> str | None:
    return s.recloser_node.get(fid) or s.switch_node.get(fid)


def _near_tie_section(s: NetworkState, fid: str, max_hops: int = 8) -> bool:
    node = _device_graph_node(s, fid)
    if not node:
        return False
    for tie_fid in s.interconnect_switch_ids:
        tie_node = s.switch_node.get(tie_fid)
        if tie_node and _graph_hops(s, node, tie_node, max_hops) <= max_hops:
            return True
    return False


def _nodes_lost_if_device_open(
    s: NetworkState, fid: str, *, planning: bool = True,
) -> set[str]:
    """Nodes that lose supply when ``fid`` is opened/tripped."""
    base = compute_energization(s, planning=planning)
    saved_sw = dict(s.switch_status)
    saved_rc = dict(s.recloser_status)
    try:
        if fid in s.recloser_status:
            s.recloser_status[fid] = 0
        elif fid in s.switch_status:
            s.switch_status[fid] = 0
        else:
            return set()
        return base - compute_energization(s, planning=planning)
    finally:
        s.switch_status = saved_sw
        s.recloser_status = saved_rc


def _customers_in_nodes(s: NetworkState, nodes: set[str]) -> int:
    total = 0
    for rid, rn in s.recloser_node.items():
        if rn in nodes:
            total += s.recloser_customers.get(rid, 0)
    for fid, sn in s.switch_node.items():
        if sn in nodes:
            total += s.switch_customers.get(fid, 0)
    return total


def _total_network_customers(s: NetworkState) -> int:
    return sum(s.recloser_customers.values()) + sum(s.switch_customers.values())


def _stats_energized_nodes(s: NetworkState) -> set[str]:
    """Graph nodes counted as energized for SCADA / feeder stats (R42/R49)."""
    all_keys = set(s.adjacency.keys())
    has_zone = bool(s.fault_node or s.maint_active)
    if not has_zone:
        return all_keys
    if _display_restoration_live(s):
        return compute_live_energization(s)
    return all_keys - _display_affected_nodes(s)


def _network_energization_stats(s: NetworkState) -> dict[str, int]:
    """Nodes and customer counts for header / status panel (R42)."""
    all_nodes = len(s.adjacency)
    energized = _stats_energized_nodes(s)
    nodes_on = len(energized)
    nodes_off = all_nodes - nodes_on
    customers_on = _customers_in_nodes(s, energized)
    customers_total = _total_network_customers(s)
    customers_off = max(0, customers_total - customers_on)
    return {
        "nodesOn": nodes_on,
        "nodesOff": nodes_off,
        "customersOn": customers_on,
        "customersOff": customers_off,
        "customersTotal": customers_total,
    }


def _is_dropout_fid(s: NetworkState, fid: str) -> bool:
    """True for F-coded fuse cutouts — excluded from switching plans (R46)."""
    props, kind = _device_meta(s, fid)
    return kind == "switch" and props.get("deviceClass") == "dropout"


def _recloser_line_end_backfeed_possible(
    s: NetworkState, rc_fid: str, primary_feeder: str,
) -> bool:
    """True when tripping RC lets the remote line-end re-energise downstream."""
    if not _is_kua_feeder(primary_feeder) or rc_fid not in s.recloser_node:
        return False
    on_closed = _kua_feeder_energization_ex(s, primary_feeder)
    saved = s.recloser_status[rc_fid]
    rc_status = dict(s.recloser_status)
    rc_status[rc_fid] = 0
    try:
        on_open = _kua_feeder_energization_ex(s, primary_feeder, rc_status=rc_status)
        isolated = on_closed - on_open
        return bool(isolated)
    finally:
        s.recloser_status[rc_fid] = saved


def _recloser_kua_sectional_backfeed_possible(
    s: NetworkState,
    rc_fid: str,
    primary_feeder: str,
    work_zone: set[str],
) -> bool:
    """After tripping RC, a sectionaliser open restores load from the line end."""
    if not _is_kua_feeder(primary_feeder) or rc_fid not in s.recloser_node:
        return False
    plan_open = {rc_fid}
    for sw_fid, status in s.switch_status.items():
        if status != 1 or sw_fid in plan_open:
            continue
        if sw_fid in s.interconnect_switch_ids or _is_dropout_fid(s, sw_fid):
            continue
        rescued_n, _ = _line_end_rescue_if_open(
            s, sw_fid, work_zone, primary_feeder, plan_open, set(),
        )
        if rescued_n > 0:
            return True
    return False


def _recloser_backfeed_possible(
    s: NetworkState,
    rc_fid: str,
    primary_feeder: str,
    work_zone: set[str] | None = None,
) -> bool:
    """RC may be tripped only when tie or line-end back-feed works (R46/R47)."""
    if _lateral_rc_backfeed_possible(s, rc_fid):
        return True
    if _recloser_line_end_backfeed_possible(s, rc_fid, primary_feeder):
        return True
    if work_zone and _recloser_kua_sectional_backfeed_possible(
        s, rc_fid, primary_feeder, work_zone,
    ):
        return True
    return False


def _colocated_switches_for_recloser(
    s: NetworkState, rc_fid: str, max_hops: int = 2,
) -> list[str]:
    """Blade switches at the same lateral tap — operator trips RC instead (R46)."""
    rc_node = s.recloser_node.get(rc_fid)
    if not rc_node:
        return []
    out: list[str] = []
    for fid, node in s.switch_node.items():
        if fid in s.recloser_status:
            continue
        if _graph_hops(s, rc_node, node, max_hops) <= max_hops:
            out.append(fid)
    return out


def _prefer_recloser_over_colocated_switches(
    s: NetworkState,
    candidates: list[str],
    primary_feeder: str,
    work_zone: set[str],
) -> list[str]:
    """Drop colocated blade switches when an RC with back-feed isolates the zone."""
    cand = list(dict.fromkeys(candidates))
    remove: set[str] = set()
    for rc_fid in cand:
        if rc_fid not in s.recloser_status:
            continue
        if not _recloser_backfeed_possible(s, rc_fid, primary_feeder, work_zone):
            continue
        if not _isolates_work_zone(s, rc_fid, work_zone):
            continue
        for sw_fid in _colocated_switches_for_recloser(s, rc_fid):
            if sw_fid in cand:
                remove.add(sw_fid)
    return [c for c in cand if c not in remove]


def _restoration_gain_threshold(cands: list[tuple[int, int, str]]) -> int:
    """Minimum customers worth a restoration step — large system first (R46)."""
    if not cands:
        return 0
    best_c = cands[0][0]
    if best_c <= 0:
        return 1
    return max(
        _LOW_IMPACT_RESTORE_CUSTOMERS,
        int(best_c * _LOW_IMPACT_RESTORE_RATIO),
    )


def _skip_low_impact_restorations(
    cands: list[tuple[int, int, str]],
) -> list[tuple[int, int, str]]:
    """Drop restoration options below the large-system threshold (R46)."""
    if not cands:
        return []
    threshold = _restoration_gain_threshold(cands)
    return [c for c in cands if c[0] >= threshold]


def _isolation_sort_key(
    s: NetworkState, fid: str, primary_feeder: str,
    energized: set[str] | None = None,
) -> tuple:
    """RC with back-feed first at lateral taps; then tie; dropouts excluded (R46/R47)."""
    props, kind = _device_meta(s, fid)
    if fid in s.interconnect_switch_ids:
        tier = 5
    elif kind == "recloser":
        tier = -1
    elif fid in s.tie_switch_ids and props.get("feeder") == primary_feeder:
        tier = 0
    elif fid in s.tie_switch_ids:
        tier = 1
    elif props.get("deviceClass") == "dropout":
        tier = 99
    else:
        tier = 3
    customers = _device_downstream_customers(s, fid, energized)
    nodes = _device_downstream_nodes(s, fid)
    return (tier, -customers, -nodes, fid)


def _recloser_line_kind(props: dict) -> str:
    op = str(props.get("operationType", "L")).upper()
    return "mainline" if op in ("R", "M") else "lateral"


def _is_mainline_device(s: NetworkState, fid: str, primary_feeder: str) -> bool:
    if fid in s.recloser_status:
        props, _ = _device_meta(s, fid)
        return _recloser_line_kind(props) == "mainline"
    props, _ = _device_meta(s, fid)
    if fid in s.interconnect_switch_ids:
        return False
    if fid in s.tie_switch_ids and props.get("feeder") == primary_feeder:
        return True
    return props.get("deviceClass") != "dropout"


def _device_downstream_nodes(s: NetworkState, fid: str) -> int:
    node = s.recloser_node.get(fid) or s.switch_node.get(fid)
    if not node:
        return 0
    best = 0
    for nb in s.adjacency.get(node, set()):
        isl = _downstream_island(s, nb, {node})
        best = max(best, len(isl))
    return best


def _device_downstream_customers(
    s: NetworkState, fid: str, energized: set[str] | None = None,
) -> int:
    node = s.recloser_node.get(fid) or s.switch_node.get(fid)
    if not node:
        return s.recloser_customers.get(fid, 0)
    if energized is None:
        energized = compute_energization(s, planning=True)
    load_side: set[str] = set()
    for nb in s.adjacency.get(node, set()):
        if nb not in energized:
            load_side |= _downstream_island(s, nb, {node})
    if not load_side:
        for nb in s.adjacency.get(node, set()):
            load_side |= _downstream_island(s, nb, {node})
    total = 0
    for rc in s.reclosers:
        rc_id = rc["properties"]["id"]
        rc_node = s.recloser_node.get(rc_id)
        if rc_node and rc_node in load_side:
            total += int(rc["properties"].get("customers", 0) or 0)
    if fid in s.recloser_customers:
        total = max(total, s.recloser_customers[fid])
    return total


def _nearby_open_tie_ids(
    s: NetworkState, node: str, max_hops: int = 6,
) -> list[str]:
    """Open tie switches within ``max_hops`` graph hops of ``node``."""
    tie_nodes = _tie_boundary_nodes(s)
    found: list[str] = []
    seen: set[str] = {node}
    queue: deque[tuple[str, int]] = deque([(node, 0)])
    while queue:
        cur, depth = queue.popleft()
        if depth > max_hops:
            continue
        if cur in tie_nodes:
            for fid in s.interconnect_switch_ids:
                if (
                    s.switch_node.get(fid) == cur
                    and s.switch_status.get(fid, 1) == 0
                ):
                    found.append(fid)
        for nb in s.adjacency.get(cur, set()):
            if nb not in seen:
                seen.add(nb)
                queue.append((nb, depth + 1))
    return found


def _lateral_rc_backfeed_possible(s: NetworkState, rc_fid: str) -> bool:
    """True when an open tie can back-feed the section isolated by tripping lateral RC."""
    if rc_fid not in s.recloser_node:
        return False
    rc_node = s.recloser_node[rc_fid]
    saved_rc = s.recloser_status[rc_fid]
    s.recloser_status[rc_fid] = 1
    on_closed = compute_energization(s, planning=True)
    s.recloser_status[rc_fid] = 0
    on_open = compute_energization(s, planning=True)
    s.recloser_status[rc_fid] = saved_rc
    isolated = on_closed - on_open
    if not isolated:
        return False
    for tie in _nearby_open_tie_ids(s, rc_node):
        sw_saved = s.switch_status[tie]
        s.recloser_status[rc_fid] = 0
        s.switch_status[tie] = 1
        restored = compute_energization(s, planning=True)
        s.recloser_status[rc_fid] = saved_rc
        s.switch_status[tie] = sw_saved
        if isolated & restored:
            return True
    return False


def _filter_isolation_candidates(
    s: NetworkState,
    candidates: list[str],
    primary_feeder: str,
    work_zone: set[str],
) -> list[str]:
    """RC at lateral tap with back-feed; no dropouts (R46/R47)."""
    phys = compute_energization(s, planning=True)
    out: list[str] = []
    for fid in candidates:
        if fid in s.interconnect_switch_ids or _is_dropout_fid(s, fid):
            continue
        if fid in s.recloser_status:
            if not _recloser_backfeed_possible(s, fid, primary_feeder, work_zone):
                continue
        out.append(fid)
    out = _prefer_recloser_over_colocated_switches(
        s, out, primary_feeder, work_zone,
    )
    out.sort(key=lambda fid: _isolation_sort_key(s, fid, primary_feeder, phys))
    return out


def _switching_plan_cut_ids(
    s: NetworkState,
    sw_status: dict[str, int],
    plan_closed: set[str] | frozenset[str],
) -> frozenset[str]:
    """Sectionalisers plus *open* grid interconnects until closed in the plan (R47).

    Display ring model ignores open KUA↔PDA ties; the switching plan must treat
    them as open until the operator closes them for back-feed."""
    cut = set(_sectionalizing_switch_ids(s))
    for fid in s.interconnect_switch_ids:
        if sw_status.get(fid, 1) == 0 and fid not in plan_closed:
            cut.add(fid)
    return frozenset(cut)


def _live_display_cut_ids(s: NetworkState) -> frozenset[str]:
    """Cut set for live operator map — mirrors switching-plan interconnect rules."""
    closed_ic = {
        fid for fid in s.interconnect_switch_ids
        if s.switch_status.get(fid, 1) == 1
    }
    return _switching_plan_cut_ids(s, s.switch_status, closed_ic)


def _kua_line_end_capped_nodes(s: NetworkState, feeder: str, line_on: set[str]) -> set[str]:
    """Line-end energization capped source-ward of tripped isolation RCs (R49).

    Meshed KUA feeders otherwise keep the load-side lit via ring bypass when an
    open RC only removes its graph node — back-feed from PDA ties must supply
    the load-side instead."""
    tripped = _tripped_isolation_rc_ids(s)
    if not tripped:
        return line_on
    hop = _kua_feeder_hop_from_seed(s, feeder)
    if not hop:
        return line_on
    rc_hops = [
        hop[s.recloser_node[fid]]
        for fid in tripped
        if fid in s.recloser_node and s.recloser_node[fid] in hop
    ]
    if not rc_hops:
        return line_on
    cap = min(rc_hops)
    # R67: nodes missing from the hop map must not inherit the cap default.
    return {n for n in line_on if n in hop and hop[n] <= cap}


def _kua_line_end_rc_load_side_nodes(
    s: NetworkState, feeder: str, line_on: set[str],
) -> set[str]:
    """Trim substation-ward mesh bleed past a tripped RC (R49/R56).

    Hops rise from the PDA-interconnect side (low) toward the remote KUA
    line end (high, e.g. KUA01R-04).  Nodes with hop *less* than the open RC
    sit substation-ward and must not stay lit from ring bypass when only the
  remote line end is supplying — unless a restoration sectional between the RC
  and the substation keeps that corridor intentional."""
    tripped = _tripped_isolation_rc_ids(s)
    if not tripped:
        return line_on
    hop = _kua_restoration_hop_from_seed(s, feeder)
    if not hop:
        return line_on
    restore_hops = [
        hop[s.switch_node[fid]]
        for fid in _kua_line_end_restoration_sectional_ids(s)
        if fid in s.switch_node and s.switch_node[fid] in hop
    ]
    min_restore_hop = min(restore_hops) if restore_hops else None
    remove: set[str] = set()
    for rc_fid in tripped:
        rc = s.recloser_node.get(rc_fid)
        if not rc or rc not in hop:
            continue
        rc_h = hop[rc]
        remove.add(rc)
        for n in line_on:
            h = hop.get(n)
            if h is None or h >= rc_h:
                continue
            if min_restore_hop is not None and h >= min_restore_hop:
                continue
            remove.add(n)
    return line_on - remove


def _kua_cap_line_end_at_sectionals(
    s: NetworkState,
    feeder: str,
    line_on: set[str],
    *,
    sw_status: dict[str, int] | None = None,
) -> set[str]:
    """Cap line-end energization at open restoration sectionalisers (R56).

    Hops increase toward the remote KUA source (e.g. KUA01R-04).  Keep only
    nodes at or beyond the opened sectional toward that source; drop
    substation-ward mesh bleed (e.g. PDA10S-08 when PDA10S-13 is open)."""
    sectionals = _kua_line_end_restoration_sectional_ids(s, sw_status)
    if not sectionals:
        return line_on
    hop = _kua_restoration_hop_from_seed(s, feeder, sw_status)
    if not hop:
        return line_on
    cap_hops = [
        hop[s.switch_node[fid]]
        for fid in sectionals
        if fid in s.switch_node and s.switch_node[fid] in hop
    ]
    if not cap_hops:
        return line_on
    cap_h = max(cap_hops)
    capped = {n for n in line_on if hop.get(n, 0) >= cap_h}
    for fid in sectionals:
        node = s.switch_node.get(fid)
        if node and hop.get(node, -1) >= cap_h:
            capped.add(node)
    return capped


def _kua_substation_side_nodes(
    s: NetworkState,
    feeder: str,
    *,
    sw_status: dict[str, int] | None = None,
    rc_status: dict[str, int] | None = None,
) -> set[str]:
    """Nodes reachable from feeder CB when open switches/reclosers block."""
    sw_st = sw_status if sw_status is not None else s.switch_status
    rc_st = rc_status if rc_status is not None else s.recloser_status
    removed: set[str] = set()
    if s.fault_node:
        removed.add(s.fault_node)
    for fid, st in rc_st.items():
        if st == 0 and fid in s.recloser_node:
            removed.add(s.recloser_node[fid])
    for fid, st in sw_st.items():
        if st == 0 and fid in s.switch_node:
            if fid in s.rc_bypass_switch_ids:
                continue
            removed.add(s.switch_node[fid])
    allowed = _kua_mesh_allowed(s, feeder)
    energized: set[str] = set()
    queue: deque[str] = deque()
    for fid, node in s.cb_node.items():
        if (
            s.cb_feeder.get(fid) == feeder
            and s.cb_status.get(fid, 1) == 1
            and node not in removed
            and node in allowed
            and node not in energized
        ):
            energized.add(node)
            queue.append(node)
    while queue:
        cur = queue.popleft()
        for nb in s.adjacency.get(cur, set()):
            if nb in removed or nb in energized or nb not in allowed:
                continue
            energized.add(nb)
            queue.append(nb)
    return energized


def _kua_line_end_trim_substation_side(
    s: NetworkState,
    feeder: str,
    line_on: set[str],
    *,
    sw_status: dict[str, int] | None = None,
    rc_status: dict[str, int] | None = None,
    line_restore: bool | None = None,
) -> set[str]:
    """Remove substation-side mesh wrongly lit via ring when a sectional is open."""
    active = (
        line_restore if line_restore is not None
        else _kua_line_end_supply_active(s)
    )
    if not active:
        return line_on
    return line_on - _kua_substation_side_nodes(
        s, feeder, sw_status=sw_status, rc_status=rc_status,
    )


def _kua_restoration_line_on(
    s: NetworkState,
    feeder: str,
    *,
    line_restore: bool,
    has_backfeed: bool,
    sw_status: dict[str, int] | None = None,
    rc_status: dict[str, int] | None = None,
) -> set[str]:
    """KUA line-end energization trimmed for RC + sectional restoration display."""
    line_on = _kua_feeder_energization_ex(
        s, feeder,
        sw_status=sw_status, rc_status=rc_status,
        line_end_restore=line_restore,
    )
    tripped = _tripped_isolation_rc_ids(s)
    if tripped and has_backfeed and not line_restore:
        # PDA tie only — do not light mesh past the open isolation RC toward line end.
        line_on = _kua_line_end_capped_nodes(s, feeder, line_on)
    # Substation-side trim when a PDA tie is feeding — it wrongly removes the
    # remote line-end seed (hop 0) on meshed KUA01 during line-end-only restore.
    if line_restore and has_backfeed:
        line_on = _kua_line_end_trim_substation_side(
            s, feeder, line_on,
            sw_status=sw_status, rc_status=rc_status,
            line_restore=True,
        )
    if line_restore and not has_backfeed:
        line_on = _kua_line_end_rc_load_side_nodes(s, feeder, line_on)
        line_on = _kua_cap_line_end_at_sectionals(
            s, feeder, line_on, sw_status=sw_status,
        )
        line_on |= _kua_line_end_load_side_touch_nodes(
            s, feeder, sw_status=sw_status, rc_status=rc_status,
        )
    return line_on


def _kua_line_end_load_side_touch_nodes(
    s: NetworkState,
    feeder: str,
    *,
    sw_status: dict[str, int] | None = None,
    rc_status: dict[str, int] | None = None,
) -> set[str]:
    """Nodes line-end-ward of open restoration sectionalisers (R55).

    Fills gaps where mesh colocate keys miss the main BFS so spans up to the
    open sectionaliser (e.g. PDA10S-13) show energized after line-end NOTE."""
    sectionals = _kua_line_end_restoration_sectional_ids(s, sw_status)
    if not sectionals:
        return set()
    hop = _kua_restoration_hop_from_seed(s, feeder, sw_status)
    if not hop:
        return set()
    cap_hops = [
        hop[s.switch_node[fid]]
        for fid in sectionals
        if fid in s.switch_node and s.switch_node[fid] in hop
    ]
    if not cap_hops:
        return set()
    cap_h = max(cap_hops)
    seed = _kua_source_seed_node(s, feeder)
    if not seed:
        return set()
    sw_st = sw_status if sw_status is not None else s.switch_status
    rc_st = rc_status if rc_status is not None else s.recloser_status
    removed: set[str] = set()
    if s.fault_node:
        removed.add(s.fault_node)
    for fid, st in rc_st.items():
        if st == 0 and fid in s.recloser_node:
            removed.add(s.recloser_node[fid])
    mesh = _kua_mesh_allowed(s, feeder)
    touched: set[str] = set()
    high_seeds = [
        n for n, h in hop.items()
        if h >= cap_h and n in mesh and n not in removed
    ]
    if not high_seeds:
        high_seeds = [seed]
    queue: deque[str] = deque()
    for node in high_seeds:
        if node not in touched:
            touched.add(node)
            queue.append(node)
    while queue:
        cur = queue.popleft()
        for nb in s.adjacency.get(cur, set()):
            if nb in touched or nb in removed or nb not in mesh:
                continue
            nh = hop.get(nb)
            if nh is None or nh < cap_h:
                continue
            touched.add(nb)
            queue.append(nb)
    for fid in sectionals:
        node = s.switch_node.get(fid)
        if node and hop.get(node, 0) >= cap_h:
            touched.add(node)
    return touched


def _kua_line_end_restore_floor_hop(s: NetworkState, feeder: str) -> int | None:
    """Hop of the outermost open restoration sectional (line-end side) (R64/R66).

    When several sectionalisers are open (e.g. PDA10S-13 + PDA10S-14), use the
    maximum hop so line-end supply starts at the remote-most device — not at the
    isolation sectional closer to the substation.

    Uses the restoration hop map so open sectionalisers do not hide themselves
    from the floor calculation."""
    if not _kua_line_end_supply_active(s) or not _kua_line_end_display_acknowledged(s):
        return None
    hop = _kua_restoration_hop_from_seed(s, feeder)
    if not hop:
        return None
    hops = [
        hop[s.switch_node[fid]]
        for fid in _kua_line_end_restoration_sectional_ids(s)
        if fid in s.switch_node and s.switch_node[fid] in hop
    ]
    return max(hops) if hops else None


def _kua_line_end_display_floor_hop(s: NetworkState, feeder: str) -> int | None:
    """Outermost open restoration sectional hop during line-end-only display."""
    if not _kua_line_end_supply_active(s) or not _kua_line_end_display_acknowledged(s):
        return None
    if _kua_interconnect_backfeed_nodes(s, feeder):
        return None
    return _kua_line_end_restore_floor_hop(s, feeder)


def _trim_kua_line_end_display_energized(
    s: NetworkState, feeder: str, energized: set[str],
) -> set[str]:
    """Drop PDA-side conductor keys after mesh/colocate extension (R56)."""
    floor_h = _kua_line_end_display_floor_hop(s, feeder)
    if floor_h is None:
        return energized
    hop = _kua_restoration_hop_from_seed(s, feeder)
    if not hop:
        return energized
    trimmed = {n for n in energized if hop.get(n, -1) >= floor_h}
    for fid in _kua_line_end_restoration_sectional_ids(s):
        node = s.switch_node.get(fid)
        if node:
            trimmed.add(node)
    for rc_fid in _tripped_isolation_rc_ids(s):
        rc = s.recloser_node.get(rc_fid)
        if rc:
            trimmed.discard(rc)
    return trimmed


def _kua_line_end_substation_ward_segment(
    hop: dict[str, int], floor_h: int, keys: list[str],
) -> bool:
    """True when all known hops on the segment are PDA-ward of the open sectional."""
    hops = [hop[k] for k in keys if k in hop]
    if not hops:
        return False
    return max(hops) < floor_h


def _kua_line_end_past_sectional_segment(
    hop: dict[str, int], floor_h: int, keys: list[str],
) -> bool:
    """True when every keyed node is line-end-ward of the open sectional (R64)."""
    hops = [hop[k] for k in keys if k in hop]
    if not hops:
        return False
    return min(hops) > floor_h


def _pda_backfeed_trace_removed(s: NetworkState) -> set[str]:
    """Barriers for PDA↔PDA interconnect back-feed corridor tracing (R76)."""
    removed: set[str] = set()
    if s.fault_node:
        removed.add(s.fault_node)
    for fid in _tripped_isolation_rc_ids(s):
        node = s.recloser_node.get(fid)
        if node:
            removed.add(node)
    for fid in s.interconnect_switch_ids:
        if s.switch_status.get(fid, 1) == 0 and fid in s.switch_node:
            removed.add(s.switch_node[fid])
    snap_sw = s.snapshot_switch or {}
    for fid in _sectionalizing_switch_ids(s):
        if (
            s.switch_status.get(fid, 1) == 0
            and snap_sw.get(fid, 1) == 1
            and fid in s.switch_node
        ):
            removed.add(s.switch_node[fid])
    return removed


def _pda_interconnect_backfeed_nodes(s: NetworkState) -> set[str]:
    """Mesh corridor from closed PDA↔PDA ties on the faulted feeder (R76).

    Independent of live-display ``phys`` so forced-dark load islands on the
    tie→open-sectional highway still paint.  Never enters the CB/main side of an
    open lateral RC."""
    primary = s.fault_feeder or s.maint_feeder or ""
    if not primary or _is_kua_feeder(primary):
        return set()
    snap_sw = s.snapshot_switch or {}
    removed = _pda_backfeed_trace_removed(s)
    blocked = _open_lateral_rc_source_side(s)
    for fid, st in s.recloser_status.items():
        if st == 0 and fid in s.recloser_node and _recloser_is_lateral(s, fid):
            blocked.add(s.recloser_node[fid])
    mesh = _feeder_mesh_nodes(s, primary)
    restored: set[str] = set()
    for fid in s.interconnect_switch_ids:
        if s.switch_status.get(fid, 1) != 1 or snap_sw.get(fid, 1) != 0:
            continue
        props, _ = _device_meta(s, fid)
        f1 = str(props.get("feeder", ""))
        f2 = str(props.get("feeder2", ""))
        if primary not in (f1, f2):
            continue
        start = s.switch_node.get(fid)
        if not start or start in removed or start in blocked:
            continue
        seen: set[str] = {start}
        queue: deque[str] = deque([start])
        while queue:
            cur = queue.popleft()
            for nb in s.adjacency.get(cur, set()):
                if (
                    nb in seen
                    or nb in removed
                    or nb in blocked
                    or nb not in mesh
                ):
                    continue
                seen.add(nb)
                queue.append(nb)
        restored |= seen
    return restored


def _pda_interconnect_restored_nodes(
    s: NetworkState, phys: set[str],
) -> set[str]:
    """Closed interconnect back-feed corridor on the faulted feeder (R71/R76).

    ``phys`` is accepted for call-site compatibility but no longer clips the
    corridor — live-display energization can omit forced-dark highway nodes."""
    _ = phys
    return _pda_interconnect_backfeed_nodes(s)


def _compute_live_energization(s: NetworkState) -> set[str]:
    """Uncached live energization (see ``compute_live_energization``)."""
    primary = s.fault_feeder or s.maint_feeder or ""
    if _is_kua_feeder(primary):
        line_restore = (
            _kua_line_end_supply_active(s)
            and _kua_line_end_display_acknowledged(s)
        )
        backfeed = _kua_interconnect_backfeed_nodes(s, primary)
        if line_restore or backfeed:
            line_on = _kua_restoration_line_on(
                s, primary,
                line_restore=line_restore,
                has_backfeed=bool(backfeed),
            )
            if line_restore and backfeed:
                # R64: line-end past open sectional + PDA corridor to open RC
                line_end_on = _kua_cap_line_end_at_sectionals(s, primary, line_on)
                return line_end_on | backfeed
            result = line_on | backfeed
            if line_restore and not backfeed:
                result = _trim_kua_line_end_display_energized(s, primary, result)
            return result
    phys = compute_energization_ex(
        s.adjacency, s.node_feeder,
        s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
        s.switch_node, s.switch_status, s.fault_node,
        _live_display_cut_ids(s),
        s.recloser_node, s.recloser_status,
    )
    if _is_kua_feeder(primary):
        return phys
    forced = _open_recloser_forced_dark(s)
    live = phys - forced
    # R71/R76: PDA↔PDA interconnect back-feed — mesh corridor, not phys-limited.
    if _active_backfeed_source_feeders(s):
        live |= _pda_interconnect_backfeed_nodes(s)
    return live


def compute_live_energization(s: NetworkState) -> set[str]:
    """Live operator map — interconnect + KUA line-end rules match switching plan (R49)."""
    return _cc_get(s, "live_on", lambda: _compute_live_energization(s))


def _kua_line_end_supply_active(s: NetworkState) -> bool:
    """True when a KUA sectionaliser was OPENED for line-end restoration (R49)."""
    if not _is_kua_feeder(s.fault_feeder or s.maint_feeder or ""):
        return False
    snap_sw = s.snapshot_switch or {}
    for fid in _sectionalizing_switch_ids(s):
        if s.switch_status.get(fid, 1) == 0 and snap_sw.get(fid, 1) == 1:
            return True
    return False


def _active_backfeed_source_feeders(s: NetworkState) -> set[str]:
    """Neighbour feeders tied in (CLOSE) since the pre-fault snapshot (R49)."""
    snap_sw = s.snapshot_switch or {}
    primary = s.fault_feeder or s.maint_feeder or ""
    out: set[str] = set()
    for fid in s.interconnect_switch_ids:
        if s.switch_status.get(fid, 1) != 1 or snap_sw.get(fid, 1) != 0:
            continue
        props, _ = _device_meta(s, fid)
        f1 = str(props.get("feeder", ""))
        f2 = str(props.get("feeder2", ""))
        if primary and primary in (f1, f2):
            out.add(f2 if f1 == primary else f1)
    return out


def _supply_feeder_priority(s: NetworkState, feeder: str) -> int:
    """Lower = preferred when two sources reach a node at the same hop count."""
    backfeed = _active_backfeed_source_feeders(s)
    primary = s.fault_feeder or s.maint_feeder or ""
    if feeder in backfeed:
        return 0
    if feeder and feeder != primary:
        return 1
    return 2


def _bfs_supply_in_zone(
    s: NetworkState,
    seeds: list[tuple[str, str]],
    energized: set[str],
    allowed: set[str],
    removed: set[str],
    supply: dict[str, str],
    dist: dict[str, int],
    *,
    overwrite: bool = False,
) -> None:
    """Multi-source BFS assigning supply feeder within ``allowed`` nodes."""
    queue: deque[str] = deque()
    for node, feeder in sorted(
        seeds, key=lambda item: _supply_feeder_priority(s, item[1]),
    ):
        if node not in energized or node not in allowed or node in removed:
            continue
        if not overwrite and node in dist:
            continue
        dist[node] = 0
        supply[node] = feeder
        queue.append(node)
    while queue:
        cur = queue.popleft()
        d = dist[cur]
        for nb in s.adjacency.get(cur, set()):
            if nb in removed or nb not in energized or nb not in allowed:
                continue
            nd = d + 1
            if nb not in dist:
                dist[nb] = nd
                supply[nb] = supply[cur]
                queue.append(nb)
                continue
            better_prio = (
                dist[nb] == nd
                and _supply_feeder_priority(s, supply[cur])
                < _supply_feeder_priority(s, supply.get(nb, ""))
            )
            if overwrite and (dist[nb] > nd or better_prio):
                if dist[nb] != nd or supply.get(nb) != supply[cur]:
                    dist[nb] = nd
                    supply[nb] = supply[cur]
                    queue.append(nb)
            elif not overwrite and better_prio:
                supply[nb] = supply[cur]
                queue.append(nb)


def _compute_node_supply_feeders(
    s: NetworkState, energized: set[str],
) -> dict[str, str]:
    """Map energized graph node → feeder of the supplying source CB/seed (R49).

    Multi-source BFS with hop-count ties broken in favour of cross-feeder
    back-feed (e.g. PDA02 via closed PDA02S-08 over the KUA01 GIS tag)."""
    removed = _live_supply_removed_nodes(s)
    feeder_source_off: set[str] = set()
    for feeder, cb_set in s.feeder_cbs.items():
        if cb_set and all(s.cb_status.get(fid, 1) == 0 for fid in cb_set):
            feeder_source_off.add(feeder)

    primary = s.fault_feeder or s.maint_feeder or ""
    dist: dict[str, int] = {}
    supply: dict[str, str] = {}
    back_paint_zone: set[str] = set()
    back_sources_set: set[str] = set()
    hop: dict[str, int] | None = None

    if _is_kua_feeder(primary) and _display_restoration_live(s):
        line_restore = (
            _kua_line_end_supply_active(s)
            and _kua_line_end_display_acknowledged(s)
        )
        backfeed = _kua_interconnect_backfeed_nodes(s, primary)
        line_on = _kua_restoration_line_on(
            s, primary,
            line_restore=line_restore,
            has_backfeed=bool(backfeed),
        )
        line_seeds: list[tuple[str, str]] = []
        hop = (
            _kua_restoration_hop_from_seed(s, primary)
            if line_restore or backfeed
            else _kua_feeder_hop_from_seed(s, primary)
        )
        back_sources_set = set(_active_backfeed_source_feeders(s))
        trace_removed = _kua_backfeed_trace_removed(s)
        if back_sources_set and hop:
            back_paint_zone = _kua_pda_backfeed_paint_zone(
                s, primary, hop=hop, removed=trace_removed,
            )
        seed = _kua_source_seed_node(s, primary)
        if line_restore and not backfeed:
            # Line-end-only: seed supply from remote KUA end (high hop), not PDA side.
            seed_set: set[tuple[str, str]] = set()
            if hop:
                cap_hops = [
                    hop[s.switch_node[fid]]
                    for fid in _kua_line_end_restoration_sectional_ids(s)
                    if fid in s.switch_node and s.switch_node[fid] in hop
                ]
                floor_h = max(cap_hops) if cap_hops else max(
                    (hop.get(n, 0) for n in line_on), default=0,
                )
                max_h = max((hop.get(n, 0) for n in line_on), default=floor_h)
                for fid, node in s.cb_node.items():
                    feeder = s.cb_feeder.get(fid, "UNK")
                    if (
                        feeder == primary
                        and s.cb_status.get(fid, 1) == 1
                        and node in energized & line_on
                        and node not in removed
                        and feeder not in feeder_source_off
                        and hop.get(node, 0) >= floor_h
                    ):
                        seed_set.add((node, primary))
                for node in line_on:
                    if (
                        node in energized
                        and node not in removed
                        and hop.get(node, 0) >= max_h
                    ):
                        seed_set.add((node, primary))
            elif seed and seed in energized & line_on and seed not in removed:
                seed_set.add((seed, primary))
            line_seeds.extend(sorted(seed_set))
        else:
            for fid, node in s.cb_node.items():
                feeder = s.cb_feeder.get(fid, "UNK")
                if (
                    feeder == primary
                    and s.cb_status.get(fid, 1) == 1
                    and node in energized & line_on
                    and node not in removed
                    and feeder not in feeder_source_off
                ):
                    line_seeds.append((node, feeder))
            if seed and seed in energized & line_on and seed not in removed:
                line_seeds.append((seed, primary))
        line_paint = line_on
        if line_restore and backfeed and hop:
            line_paint = _kua_line_end_high_hop_nodes(s, primary, line_on, hop)
        _bfs_supply_in_zone(
            s, line_seeds, energized, line_paint, removed, supply, dist,
        )
        snap_sw = s.snapshot_switch or {}
        back_seeds: list[tuple[str, str]] = []
        for fid in s.interconnect_switch_ids:
            if s.switch_status.get(fid, 1) != 1 or snap_sw.get(fid, 1) != 0:
                continue
            props, _ = _device_meta(s, fid)
            f1 = str(props.get("feeder", ""))
            f2 = str(props.get("feeder2", ""))
            if primary not in (f1, f2):
                continue
            foreign = f2 if f1 == primary else f1
            node = s.switch_node.get(fid)
            if node and node in energized & backfeed and foreign:
                back_seeds.append((node, foreign))
        _bfs_supply_in_zone(
            s, back_seeds, energized, back_paint_zone, removed, supply, dist,
            overwrite=True,
        )
        for n in list(supply.keys()):
            if supply.get(n) in back_sources_set and n not in back_paint_zone:
                del supply[n]
    else:
        seeds: list[tuple[str, str]] = []
        for fid, node in s.cb_node.items():
            feeder = s.cb_feeder.get(fid, "UNK")
            if (
                s.cb_status.get(fid, 1) == 1
                and node in energized
                and node not in removed
                and feeder not in feeder_source_off
            ):
                seeds.append((node, feeder))
        _bfs_supply_in_zone(
            s, seeds, energized, energized, removed, supply, dist,
        )
        # R71: PDA↔PDA interconnect back-feed — paint neighbour feeder colour
        # from the closed tie through the restored corridor (stops at open cuts).
        snap_sw = s.snapshot_switch or {}
        back_sources_set = set(_active_backfeed_source_feeders(s))
        if back_sources_set and primary:
            back_seeds: list[tuple[str, str]] = []
            for fid in s.interconnect_switch_ids:
                if s.switch_status.get(fid, 1) != 1 or snap_sw.get(fid, 1) != 0:
                    continue
                props, _ = _device_meta(s, fid)
                f1 = str(props.get("feeder", ""))
                f2 = str(props.get("feeder2", ""))
                if primary not in (f1, f2):
                    continue
                foreign = f2 if f1 == primary else f1
                node = s.switch_node.get(fid)
                if node and node in energized and foreign in back_sources_set:
                    back_seeds.append((node, foreign))
            if back_seeds:
                back_paint_zone = _pda_interconnect_restored_nodes(s, energized)
                _bfs_supply_in_zone(
                    s, back_seeds, energized, back_paint_zone, removed, supply, dist,
                    overwrite=True,
                )

    # Continuous conductor keys — inherit from energised neighbours (R49/R60).
    changed = True
    while changed:
        changed = False
        for node in energized:
            if node in supply:
                continue
            node_feeder = str(s.node_feeder.get(node, ""))
            for nb in s.adjacency.get(node, set()):
                if nb not in supply:
                    continue
                src = supply[nb]
                if src in back_sources_set and node not in back_paint_zone:
                    continue
                # R67: KUA / interconnect supply must not inherit onto foreign PDA GIS.
                if (
                    (src == primary or src in back_sources_set)
                    and node_feeder
                    and node_feeder != primary
                    and not node_feeder.startswith("KUA")
                ):
                    continue
                supply[node] = src
                changed = True
                break
    return supply


def _segment_supply_feeder(
    keys: list[str],
    gis_feeder: str,
    energized: set[str],
    supply_map: dict[str, str],
    *,
    s: NetworkState | None = None,
    hop: dict[str, int] | None = None,
    back_paint_zone: set[str] | None = None,
) -> str | None:
    """Actual source feeder for map tint — always returned when supply is known."""
    live_keys = [k for k in keys if k in energized]
    if not live_keys:
        return None
    sources = {supply_map.get(k) for k in keys if supply_map.get(k)} - {None}
    if not sources:
        return None
    # R71: closed interconnect back-feed wins tint on the restored corridor.
    if s is not None:
        back_sources = _active_backfeed_source_feeders(s)
        if back_sources:
            back_hit = sorted(
                sf for sf in sources if sf in back_sources
            )
            if back_hit:
                if back_paint_zone is not None:
                    in_zone = any(k in back_paint_zone for k in live_keys)
                    if in_zone or any(
                        supply_map.get(k) in back_sources for k in live_keys
                    ):
                        return back_hit[0]
                else:
                    return back_hit[0]
    foreign = sorted(sf for sf in sources if sf != gis_feeder)
    if foreign and s and str(gis_feeder).startswith("KUA"):
        back_sources = _active_backfeed_source_feeders(s)
        if foreign[0] in back_sources:
            pda_keys = [k for k in keys if supply_map.get(k) in back_sources]
            blocked = False
            if back_paint_zone is not None and pda_keys:
                blocked = not all(k in back_paint_zone for k in pda_keys)
            if not blocked and hop:
                rc_hops = [
                    hop[s.recloser_node[fid]]
                    for fid in _tripped_isolation_rc_ids(s)
                    if fid in s.recloser_node and s.recloser_node[fid] in hop
                ]
                if rc_hops:
                    cap = min(rc_hops)
                    seg_hops = [hop[k] for k in keys if k in hop]
                    blocked = bool(seg_hops and max(seg_hops) > cap)
            if blocked:
                foreign = []
                sources -= back_sources
    if foreign:
        return foreign[0]
    if not sources:
        return gis_feeder or None
    return sorted(sources)[0]


def _energization_under_plan(
    s: NetworkState,
    plan_open: set[str] | frozenset[str],
    plan_closed: set[str] | frozenset[str] | None = None,
) -> set[str]:
    """Physical energization with plan opens (trip/open) and closes (tie close)."""
    plan_closed = plan_closed or frozenset()
    sw_status = dict(s.switch_status)
    rc_status = dict(s.recloser_status)
    for fid in plan_open:
        if fid in rc_status:
            rc_status[fid] = 0
        elif fid in sw_status:
            sw_status[fid] = 0
    for fid in plan_closed:
        if fid in sw_status:
            sw_status[fid] = 1
    return compute_energization_ex(
        s.adjacency, s.node_feeder,
        s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
        s.switch_node, sw_status, s.fault_node,
        _switching_plan_cut_ids(s, sw_status, plan_closed),
        s.recloser_node, rc_status,
    )


def _kua_line_end_under_plan(
    s: NetworkState,
    feeder: str,
    plan_open: set[str] | frozenset[str],
) -> set[str]:
    """Line-end-only energization while honouring devices opened in the plan."""
    sw_status = dict(s.switch_status)
    rc_status = dict(s.recloser_status)
    for fid in plan_open:
        if fid in rc_status:
            rc_status[fid] = 0
        elif fid in sw_status:
            sw_status[fid] = 0
    return _kua_feeder_energization_ex(
        s, feeder, sw_status=sw_status, rc_status=rc_status,
    )


def _isolates_work_zone(
    s: NetworkState, fid: str, work_zone: set[str],
) -> bool:
    """True when opening/tripping ``fid`` removes supply from part of ``work_zone``."""
    lost = _nodes_lost_if_device_open(s, fid)
    return bool(lost & work_zone)


def _best_tie_backfeed_if_open(
    s: NetworkState,
    iso_fid: str,
    work_zone: set[str],
) -> tuple[int, int, str | None]:
    """Best open tie to close after tripping ``iso_fid`` — (customers, nodes, tie_id)."""
    plan_open = frozenset({iso_fid})
    best_c, best_n, best_tie = 0, 0, None
    for tie_fid in s.interconnect_switch_ids:
        if s.switch_status.get(tie_fid, 1) != 0:
            continue
        on_with = _energization_under_plan(s, plan_open, frozenset({tie_fid}))
        rescued = on_with & work_zone
        if not rescued:
            continue
        gained_c = _customers_in_nodes(s, rescued)
        gained_n = len(rescued)
        if gained_c > best_c or (gained_c == best_c and gained_n > best_n):
            best_c, best_n, best_tie = gained_c, gained_n, tie_fid
    return best_c, best_n, best_tie


def _isolation_plan_score(
    s: NetworkState,
    fid: str,
    work_zone: set[str],
    primary_feeder: str,
) -> tuple:
    """Smallest collateral outage first, then tie back-feed benefit (R46)."""
    lost = _nodes_lost_if_device_open(s, fid)
    back_c, back_n, _ = _best_tie_backfeed_if_open(s, fid, work_zone)
    isolates = 0 if _isolates_work_zone(s, fid, work_zone) else 1
    phys = compute_energization(s, planning=True)
    return (
        isolates,
        len(lost),
        -back_c,
        -back_n,
        *_isolation_sort_key(s, fid, primary_feeder, phys),
    )


def _line_end_rescue_if_open(
    s: NetworkState,
    fid: str,
    work_zone: set[str],
    primary_feeder: str,
    plan_open: set[str],
    plan_closed: set[str],
) -> tuple[int, int]:
    """Nodes in ``work_zone`` fed from the remote line end when ``fid`` is opened."""
    if not _is_kua_feeder(primary_feeder):
        return 0, 0
    open_with = set(plan_open) | {fid}
    line_with = _kua_line_end_under_plan(s, primary_feeder, frozenset(open_with))
    rescued = work_zone & line_with
    if not rescued:
        return 0, 0
    return len(rescued), _customers_in_nodes(s, rescued)


def _line_end_sectionalizing_candidates(
    s: NetworkState,
    work_zone: set[str],
    primary_feeder: str,
    plan_open: set[str],
    plan_closed: set[str],
) -> list[tuple[int, int, str]]:
    """Closed blade switches — opening partitions outage and feeds from line end."""
    out: list[tuple[int, int, str]] = []
    for fid, status in s.switch_status.items():
        if status != 1 or fid in plan_open or fid in plan_closed:
            continue
        if fid in s.interconnect_switch_ids or _is_dropout_fid(s, fid):
            continue
        props, _ = _device_meta(s, fid)
        if props.get("feeder") != primary_feeder:
            continue
        node = s.switch_node.get(fid)
        if not node:
            continue
        rescued_n, rescued_c = _line_end_rescue_if_open(
            s, fid, work_zone, primary_feeder, plan_open, plan_closed,
        )
        if rescued_n > 0:
            out.append((rescued_c, rescued_n, fid))
    fault_node = s.fault_node
    out.sort(
        key=lambda x: (
            -x[0],
            -x[1],
            _graph_hops(s, s.switch_node.get(x[2], ""), fault_node, 500) or 9999
            if fault_node else 0,
            x[2],
        ),
    )
    return out


def _gain_if_switch_closed(
    s: NetworkState,
    fid: str,
    baseline: set[str],
    *,
    plan_open: set[str] | frozenset[str] | None = None,
) -> tuple[int, int, set[str]]:
    """``(node_count, customers, node_set)`` restored if open tie ``fid`` closes."""
    if s.switch_status.get(fid, 1) != 0:
        return 0, 0, set()
    if plan_open is not None:
        on_with = _energization_under_plan(s, plan_open, frozenset({fid}))
        gained = on_with - baseline
    else:
        saved = s.switch_status[fid]
        s.switch_status[fid] = 1
        new_on = compute_energization(s, planning=True)
        s.switch_status[fid] = saved
        gained = new_on - baseline
    if not gained:
        return 0, 0, set()
    return len(gained), _customers_in_nodes(s, gained), gained


def _count_nodes_if_switch_closed(
    s: NetworkState, fid: str, baseline: set[str],
) -> int:
    n, _, _ = _gain_if_switch_closed(s, fid, baseline)
    return n


def _cross_feeder_restoration_candidates(
    s: NetworkState,
    work_zone: set[str],
    baseline_energized: set[str],
    *,
    plan_open: set[str] | frozenset[str] | None = None,
) -> list[tuple[int, int, str]]:
    """Open tie switches ranked by customers then nodes restored (R31)."""
    out: list[tuple[int, int, str]] = []
    for fid in s.interconnect_switch_ids:
        if s.switch_status.get(fid, 1) != 0:
            continue
        node = s.switch_node.get(fid)
        if not node:
            continue
        gained_n, gained_c, gained_set = _gain_if_switch_closed(
            s, fid, baseline_energized, plan_open=plan_open,
        )
        if gained_n <= 0:
            continue
        touches_zone = (
            node in work_zone
            or any(nb in work_zone for nb in s.adjacency.get(node, set()))
            or bool(gained_set & work_zone)
        )
        if not touches_zone and not any(
            nb in baseline_energized for nb in s.adjacency.get(node, set())
        ):
            continue
        out.append((gained_c, gained_n, fid))
    out.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return out


def _line_end_backfeed_summary(
    s: NetworkState,
    work_zone: set[str],
    primary_feeder: str,
    plan_open: set[str],
) -> tuple[int, int]:
    """Nodes/customers on load-side fed from KUA line end after sectional OPEN."""
    if not _is_kua_feeder(primary_feeder):
        return 0, 0
    line_on = _kua_line_end_under_plan(s, primary_feeder, frozenset(plan_open))
    rescued = line_on & work_zone
    if s.fault_node:
        rescued.discard(s.fault_node)
    return len(rescued), _customers_in_nodes(s, rescued)


def _combined_plan_energized(
    s: NetworkState,
    primary_feeder: str,
    plan_open: set[str],
    plan_closed: set[str],
) -> set[str]:
    """Restoration view: KUA line-end feed merged with neighbour CB energization."""
    phys = _energization_under_plan(s, frozenset(plan_open), frozenset(plan_closed))
    if not _is_kua_feeder(primary_feeder):
        return phys
    snap_sw = s.snapshot_switch or {}
    line_restore = any(
        fid in _sectionalizing_switch_ids(s)
        and fid in plan_open
        and snap_sw.get(fid, 1) == 1
        for fid in plan_open
    )
    sw_status = dict(s.switch_status)
    rc_status = dict(s.recloser_status)
    for fid in plan_open:
        if fid in rc_status:
            rc_status[fid] = 0
        elif fid in sw_status:
            sw_status[fid] = 0
    for fid in plan_closed:
        if fid in sw_status:
            sw_status[fid] = 1
    line_on = _kua_restoration_line_on(
        s, primary_feeder,
        line_restore=line_restore,
        has_backfeed=bool(plan_closed),
        sw_status=sw_status, rc_status=rc_status,
    )
    backfeed = _kua_interconnect_backfeed_nodes(
        s, primary_feeder, sw_status=sw_status,
    ) if plan_closed else set()
    return line_on | backfeed if (line_restore or backfeed) else phys


def _substations_geojson(s: NetworkState) -> list[dict]:
    out = []
    for sub in s.substations:
        fid = sub["properties"]["id"]
        status = s.cb_status.get(fid, 1)
        out.append({**sub, "properties": {**sub["properties"],
                    "status": status, "state": "CLOSE" if status == 1 else "OPEN"}})
    return out


def _live_map_bundle(s: NetworkState) -> dict:
    """Cached conductors + outage polygons from one energization pass (R51)."""
    return _cc_get(s, "live_map_bundle", lambda: _build_live_map_bundle(s))


def _build_live_map_bundle(s: NetworkState) -> dict:
    """Single scan of conductor segments → live conductors + outage hulls."""
    node_energized = compute_display_energization(s)
    restoration_live = _display_restoration_live(s)
    primary = s.fault_feeder or s.maint_feeder or ""
    paint_energized = node_energized
    if restoration_live:
        paint_energized = _extend_energized_through_conductors(s, node_energized)
        if _is_kua_feeder(primary):
            paint_energized = _trim_kua_line_end_display_energized(
                s, primary, paint_energized,
            )
    affected = _display_affected_nodes(s)
    has_zone = bool(s.fault_node or s.maint_active)
    supply_map = (
        _cc_get(
            s, "node_supply",
            lambda: _compute_node_supply_feeders(s, compute_live_energization(s)),
        )
        if restoration_live else {}
    )
    if restoration_live and supply_map:
        supply_map = _extend_supply_map_through_conductors(
            s, supply_map, paint_energized,
        )
    feeders_affected: set[str] = set()
    active_feeders = _active_feeders_with_cb(s)
    feeders_source_open = sorted(
        f for f in active_feeders
        if all(s.cb_status.get(fid, 1) == 0 for fid in s.feeder_cbs[f])
    )
    scope = _fault_target_feeders(s) if s.fault_node else frozenset()
    zone_xy = (
        [s.node_xy[k] for k in affected if k in s.node_xy]
        if affected else None
    )
    zone_index = _make_zone_snap_index(zone_xy) if zone_xy else None
    line_end_floor = (
        _kua_line_end_restore_floor_hop(s, primary)
        if restoration_live and _is_kua_feeder(primary) else None
    )
    line_end_hop = (
        _kua_restoration_hop_from_seed(s, primary)
        if line_end_floor is not None else None
    )
    tint_hop = None
    if restoration_live and _is_kua_feeder(primary):
        tint_hop = (
            _kua_restoration_hop_from_seed(s, primary)
            if _active_backfeed_source_feeders(s)
            else _kua_feeder_hop_from_seed(s, primary)
        )
    back_sources = (
        _active_backfeed_source_feeders(s) if restoration_live else set()
    )
    if restoration_live and tint_hop and back_sources:
        back_paint_zone = _kua_pda_backfeed_paint_zone(
            s, primary, hop=tint_hop, removed=_kua_backfeed_trace_removed(s),
        )
    elif restoration_live and back_sources and not _is_kua_feeder(primary):
        # R71: PDA↔PDA restored corridor for supply tint (stops at open cuts).
        back_paint_zone = _pda_interconnect_restored_nodes(
            s, compute_live_energization(s),
        )
    else:
        back_paint_zone = set()

    polygon_affected = set(affected)
    if restoration_live and back_paint_zone:
        # R76: restored PDA back-feed corridor may remain inside the fault
        # envelope, but it must not keep outage polygons once it is visibly lit.
        polygon_affected -= back_paint_zone

    restore_poly_index = None
    if restoration_live and back_paint_zone:
        restore_xy = [s.node_xy[k] for k in back_paint_zone if k in s.node_xy]
        restore_poly_index = _make_zone_snap_index(restore_xy, 160.0)

    # R69: main-line guard at open lateral protecting RC (e.g. PDA07R-01).
    lateral_main_guard = _protecting_lateral_rc_mainline_guard(s)
    lateral_guard_index = None
    if lateral_main_guard:
        guard_xy = [s.node_xy[k] for k in lateral_main_guard if k in s.node_xy]
        lateral_guard_index = _make_zone_snap_index(guard_xy, 90.0)

    outage_features: list[dict] = []
    seen_rings: set[tuple[tuple[float, float], ...]] = set()
    feeder_node_counts: dict[str, int] = defaultdict(int)
    for k in polygon_affected:
        fdr = s.node_feeder.get(k)
        if fdr:
            feeder_node_counts[fdr] += 1

    def _append_outage_corridor(
        feeder: str,
        ring_utm: list[tuple[float, float]],
    ) -> None:
        if scope and feeder not in scope:
            return
        key = tuple(ring_utm)
        if key in seen_rings:
            return
        seen_rings.add(key)
        ring_wgs = _utm_ring_to_wgs_polygon(ring_utm)
        if not ring_wgs:
            return
        outage_features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring_wgs]},
            "properties": {
                "feeder": feeder,
                "nodesAffected": feeder_node_counts.get(feeder, 0),
                "faultFeeder": s.fault_feeder,
                "faultCoords": _format_fault_coords(s.fault_lat, s.fault_lon),
                "zone": "fault-impact",
                "includesLaterals": True,
            },
        })

    conductors_out: list[dict] = []
    for cw, keys in zip(s.conductor_wgs, s.conductor_keys):
        feeder = cw["properties"]["feeder"]
        # R76: only promote paint across spans that are live or in the back-feed zone.
        if restoration_live and back_paint_zone and keys:
            if any(k in back_paint_zone for k in keys) or any(
                k in node_energized for k in keys
            ):
                seg_energized = paint_energized
            else:
                seg_energized = node_energized
        else:
            seg_energized = paint_energized if restoration_live else node_energized
        if has_zone and scope and feeder not in scope:
            on = True
        elif (
            line_end_floor is not None
            and line_end_hop
            and _kua_line_end_past_sectional_segment(line_end_hop, line_end_floor, keys)
        ):
            on = True
        elif (
            line_end_floor is not None
            and line_end_hop
            and _kua_line_end_substation_ward_segment(line_end_hop, line_end_floor, keys)
        ):
            # R65: PDA tie→RC corridor sits hop-ward of S-13 but is live from
            # interconnect back-feed — do not force those segments OFF.
            if keys and any(k in seg_energized for k in keys):
                on = not _conductor_segment_off(
                    keys, seg_energized, affected, s=s, zone_xy=zone_xy,
                    zone_index=zone_index, physical=restoration_live,
                    back_paint_zone=back_paint_zone,
                )
            else:
                on = False
        elif has_zone:
            on = not _conductor_segment_off(
                keys, seg_energized, affected, s=s, zone_xy=zone_xy,
                zone_index=zone_index, physical=restoration_live,
                back_paint_zone=back_paint_zone,
            )
        else:
            on = True
        if not on:
            feeders_affected.add(feeder)
            if has_zone and (not scope or feeder in scope):
                # R76: fault-side OFF legs next to the restored highway must not
                # paint 45 m outage buffers that cover PDA05-tinted conductors.
                # R69: lateral-island OFF legs must not paint across the tap onto
                # the energised main line past PDA07R-01 (etc.).
                skip_poly = bool(
                    (
                        restoration_live and back_paint_zone and (
                            any(k in back_paint_zone for k in keys)
                            or _segment_near_nodes(
                                s, keys, back_paint_zone, snap_m=160.0,
                                zone_index=restore_poly_index,
                            )
                        )
                    )
                    or (
                        lateral_main_guard and (
                            any(k in lateral_main_guard for k in keys)
                            or _segment_near_nodes(
                                s, keys, lateral_main_guard, snap_m=90.0,
                                zone_index=lateral_guard_index,
                            )
                        )
                    )
                )
                if not skip_poly:
                    pts_utm = [
                        to_utm(lon, lat)
                        for lon, lat in cw["geometry"]["coordinates"]
                    ]
                    ring_utm = _buffer_polyline_ring_utm(pts_utm, half_width_m=45.0)
                    if ring_utm:
                        _append_outage_corridor(feeder, ring_utm)
        props: dict = {**cw["properties"], "status": "on" if on else "off"}
        if on and restoration_live:
            supply_f = _segment_supply_feeder(
                keys, feeder, paint_energized, supply_map,
                s=s, hop=tint_hop, back_paint_zone=back_paint_zone,
            )
            # R67: only recolour the faulted KUA feeder (incl. PDA back-feed tint).
            # Unrelated GIS feeders keep their native map colours.
            if (
                supply_f
                and _is_kua_feeder(primary)
                and feeder != primary
                and not str(feeder).startswith("KUA")
            ):
                supply_f = None
            # R71: PDA faulted feeder must show interconnect source colour when
            # any live key is in the restored back-feed corridor.
            if (
                not supply_f
                and back_sources
                and feeder == primary
                and not _is_kua_feeder(primary)
            ):
                hit = sorted(
                    {
                        supply_map.get(k)
                        for k in keys
                        if supply_map.get(k) in back_sources
                        and (not back_paint_zone or k in back_paint_zone or k in paint_energized)
                    } - {None}
                )
                if hit:
                    supply_f = hit[0]
            # R74: any ON primary segment touching the restored corridor must
            # show the interconnect source colour (overrides native GIS / stale
            # primary supply left on coastal laterals past the closed tie).
            if (
                back_sources
                and feeder == primary
                and not _is_kua_feeder(primary)
                and back_paint_zone
                and any(k in back_paint_zone for k in keys)
            ):
                supply_f = sorted(back_sources)[0]
            if supply_f:
                props["supplyFeeder"] = supply_f
                tint = s.feeder_color.get(supply_f, props.get("color"))
                props["displayColor"] = tint
                # R73: also overwrite GIS colour so every render path tints.
                props["color"] = tint
        conductors_out.append({**cw, "properties": props})

    if has_zone and polygon_affected:
        for fid in s.tie_switch_ids:
            if s.switch_status.get(fid, 1) != 0:
                continue
            node = s.switch_node.get(fid)
            if not node or node not in s.node_xy or node not in polygon_affected:
                continue
            # R76: open cut at the restored corridor edge must not keep a
            # 45 m outage disc on top of the PDA05 highway.
            # R69: open ties on the lateral island must not disc-bleed onto the
            # energised main line at the protecting RC tap.
            if restoration_live and back_paint_zone and (
                any(nb in back_paint_zone for nb in s.adjacency.get(node, set()))
                or _segment_near_nodes(
                    s, [node], back_paint_zone, snap_m=160.0,
                    zone_index=restore_poly_index,
                )
            ):
                continue
            if lateral_main_guard and (
                node in lateral_main_guard
                or any(nb in lateral_main_guard for nb in s.adjacency.get(node, set()))
                or _segment_near_nodes(
                    s, [node], lateral_main_guard, snap_m=90.0,
                    zone_index=lateral_guard_index,
                )
            ):
                continue
            if any(nb in polygon_affected for nb in s.adjacency.get(node, set())):
                sw_props = next(
                    (sw["properties"] for sw in s.switches if sw["properties"]["id"] == fid),
                    None,
                )
                feeder = (sw_props or {}).get("feeder", s.node_feeder.get(node, "UNK"))
                x, y = s.node_xy[node]
                ring_utm = _buffer_ring_utm(x, y, 45.0)
                _append_outage_corridor(feeder, ring_utm)
        if not outage_features:
            for k in polygon_affected:
                if k not in s.node_xy:
                    continue
                feeder = s.node_feeder.get(k, s.fault_feeder or "UNK")
                x, y = s.node_xy[k]
                ring_utm = _buffer_ring_utm(x, y, 45.0)
                _append_outage_corridor(feeder, ring_utm)

    return {
        "conductors": conductors_out,
        "outage_polys": outage_features,
        "feeders_affected": sorted(feeders_affected),
        "feeders_source_open": feeders_source_open,
    }


def build_live_conductors(s: NetworkState):
    bundle = _live_map_bundle(s)
    return (
        bundle["conductors"],
        bundle["feeders_affected"],
        bundle["feeders_source_open"],
    )


def get_live_conductors_view(s: NetworkState):
    """Cached conductor features + feeder stats for API routes (R30)."""
    return _cc_get(s, "live_conductors", lambda: build_live_conductors(s))


def get_outage_polygons_cached(s: NetworkState) -> list[dict]:
    """Cached outage hull features — shares ``live_map_bundle`` with conductors (R51)."""
    if not s.fault_node and not s.maint_active:
        return []
    return _live_map_bundle(s)["outage_polys"]


def _scada_payload(
    s: NetworkState,
    feeders_affected: list[str],
    feeders_source_open: list[str],
) -> dict:
    """SCADA header stats — shared by ``/scada`` and ``/live-refresh`` (R51)."""
    sw_open, sw_total = tie_switch_counts(s)
    active_feeders = _active_feeders_with_cb(s)
    stats = _network_energization_stats(s)
    has_zone = bool(s.fault_node or s.maint_active)
    backfeed_sources = sorted(_active_backfeed_source_feeders(s))
    line_end_active = (
        _kua_line_end_supply_active(s) and _kua_line_end_display_acknowledged(s)
        if has_zone else False
    )
    primary = s.fault_feeder or s.maint_feeder or ""
    active_supply: list[str] = []
    if line_end_active and primary:
        active_supply.append(primary)
    for f in backfeed_sources:
        if f not in active_supply:
            active_supply.append(f)
    return {
        "faultActive":       bool(s.fault_node),
        "lineDisplayFull":   not has_zone,
        "lineDisplayPhysical": _display_restoration_live(s),
        "lineDisplayIsolation": _display_live_topology(s) and not _display_restoration_live(s),
        "lineEndRestoreActive": line_end_active,
        "backfeedSourceFeeders": backfeed_sources,
        "activeSupplyFeeders": active_supply,
        "appBuild": "R76",
        "faultFeeder":       s.fault_feeder,
        "faultFeeders":      s.fault_feeders,
        "faultLat":          s.fault_lat,
        "faultLon":          s.fault_lon,
        "faultCoords":       _format_fault_coords(s.fault_lat, s.fault_lon),
        "faultCause":        s.fault_cause,
        "faultPhase":        s.fault_phase,
        "switchOpen":        sw_open,
        "switchTotal":       sw_total,
        "cbOpen":            len(feeders_source_open),
        "cbTotal":           len(active_feeders),
        "nodesOn":           stats["nodesOn"],
        "nodesOff":          stats["nodesOff"],
        "customersOn":       stats["customersOn"],
        "customersOff":      stats["customersOff"],
        "customersTotal":    stats["customersTotal"],
        "feedersAffected":   feeders_affected,
        "feedersSourceOpen": feeders_source_open,
        "maintActive":       s.maint_active,
        "maintFeeder":       s.maint_feeder,
        "maintStartLat":     s.maint_start_lat,
        "maintStartLon":     s.maint_start_lon,
        "maintEndLat":       s.maint_end_lat,
        "maintEndLon":       s.maint_end_lon,
        "maintJobName":      s.maint_job_name,
        "maintJobNumber":    s.maint_job_number,
        "maintCoords": (
            f"{_format_fault_coords(s.maint_start_lat, s.maint_start_lon)} → "
            f"{_format_fault_coords(s.maint_end_lat, s.maint_end_lon)}"
            if s.maint_active else None
        ),
    }


def _build_live_refresh_payload(s: NetworkState) -> dict:
    """One energization pass → full operator map payload (R51)."""
    bundle = _live_map_bundle(s)
    return {
        "conductors": {
            "type": "FeatureCollection",
            "features": bundle["conductors"],
        },
        "outagePoly": {
            "type": "FeatureCollection",
            "features": bundle["outage_polys"],
        },
        "scada": _scada_payload(
            s, bundle["feeders_affected"], bundle["feeders_source_open"],
        ),
        "switches": {
            "type": "FeatureCollection",
            "features": _switches_geojson(s),
        },
        "reclosers": {
            "type": "FeatureCollection",
            "features": _reclosers_geojson(s),
        },
        "substations": {
            "type": "FeatureCollection",
            "features": _substations_geojson(s),
        },
    }


def _rc_grid_tie_close_candidates(
    s: NetworkState,
    iso_rc_fid: str | None,
    primary_feeder: str,
    plan_open: set[str],
    plan_closed: set[str],
) -> list[str]:
    """Open KUA↔PDA grid ties to close after RC trip — back-feed from PDA (R47)."""
    if (
        not iso_rc_fid
        or iso_rc_fid not in s.recloser_status
        or not _is_kua_feeder(primary_feeder)
    ):
        return []
    rc_node = s.recloser_node.get(iso_rc_fid)
    if not rc_node:
        return []
    ranked: list[tuple[int, int, str]] = []
    for tie_fid in _nearby_open_tie_ids(s, rc_node, max_hops=250):
        if tie_fid in plan_open or tie_fid in plan_closed:
            continue
        props, _ = _device_meta(s, tie_fid)
        if not is_kua_pda_interconnect(props):
            continue
        f1 = str(props.get("feeder", ""))
        f2 = str(props.get("feeder2", ""))
        if primary_feeder not in (f1, f2):
            continue
        neighbor = f2 if f1 == primary_feeder else f1
        if not s.feeder_cbs.get(neighbor):
            continue
        hops = _graph_hops(
            s, rc_node, s.switch_node.get(tie_fid, ""), 250,
        ) or 999
        pref = {"PDA02": 0, "PDA03": 1, "PDA10": 2}.get(neighbor, 3)
        ranked.append((pref, hops, tie_fid))
    ranked.sort(key=lambda x: (x[0], x[1], x[2]))
    ties = [t for _, _, t in ranked]
    neighbor_of = lambda tie: (
        str(_device_meta(s, tie)[0].get("feeder2", ""))
        if str(_device_meta(s, tie)[0].get("feeder", "")) == primary_feeder
        else str(_device_meta(s, tie)[0].get("feeder", ""))
    )
    if any(neighbor_of(t) == "PDA02" for t in ties):
        ties = [t for t in ties if neighbor_of(t) != "PDA10"]
    return ties


def _select_isolation_device(
    s: NetworkState,
    ranked_iso: list[str],
    work_zone: set[str],
    primary_feeder: str,
) -> str | None:
    """RC at nearest lateral tap with back-feed; else smallest-outage switch (R47)."""
    fault_node = s.fault_node
    rc_pool = [
        fid for fid in ranked_iso
        if fid in s.recloser_status
        and _isolates_work_zone(s, fid, work_zone)
        and _recloser_backfeed_possible(s, fid, primary_feeder, work_zone)
    ]
    if rc_pool:
        rc_pool.sort(
            key=lambda f: (
                _graph_hops(s, s.recloser_node[f], fault_node, 500) or 9999
                if fault_node else 0,
                len(_nodes_lost_if_device_open(s, f)),
                f,
            )
        )
        return rc_pool[0]
    scored = sorted(
        ranked_iso,
        key=lambda fid: _isolation_plan_score(s, fid, work_zone, primary_feeder),
    )
    for fid in scored:
        if _isolates_work_zone(s, fid, work_zone):
            return fid
    return ranked_iso[0] if ranked_iso else None


def _switching_plan_for_zone(
    s: NetworkState,
    work_zone: set[str],
    *,
    context_label: str,
    meta: dict,
) -> dict:
    """Shared FISR isolation/restoration planner for fault or maintenance zones."""
    if not work_zone:
        return {"error": "ไม่พบโซนปฏิบัติงาน — ตรวจสอบพิกัดหรือจุดฟอลต์"}

    primary_feeder = meta.get("feeder") or s.fault_feeder or s.maint_feeder or "?"
    kua_line_end = _is_kua_feeder(primary_feeder)

    all_nodes  = set(s.adjacency.keys())
    if kua_line_end:
        energized0 = _kua_feeder_energization_ex(s, primary_feeder)
    else:
        energized0 = compute_energization(s)
    de_nodes0  = all_nodes - energized0

    isolation_candidates: list[str] = []
    for fid, status in s.switch_status.items():
        if status != 1:
            continue
        if fid in s.interconnect_switch_ids:
            continue
        if _is_dropout_fid(s, fid):
            continue
        node = s.switch_node.get(fid)
        if not node:
            continue
        neighbors = s.adjacency.get(node, set())
        in_zone   = node in work_zone
        near_zone = any(nb in work_zone for nb in neighbors)
        near_energ = any(nb in energized0 for nb in neighbors)
        if (in_zone or near_zone) and near_energ:
            isolation_candidates.append(fid)

    for fid, status in s.recloser_status.items():
        if status != 1:
            continue
        node = s.recloser_node.get(fid)
        if not node:
            continue
        neighbors = s.adjacency.get(node, set())
        in_zone   = node in work_zone
        near_zone = any(nb in work_zone for nb in neighbors)
        near_energ = any(nb in energized0 for nb in neighbors)
        if (in_zone or near_zone) and near_energ:
            isolation_candidates.append(fid)

    ranked_iso = _filter_isolation_candidates(
        s, isolation_candidates, primary_feeder, work_zone,
    )

    iso_pick = _select_isolation_device(s, ranked_iso, work_zone, primary_feeder)
    iso_switches = [iso_pick] if iso_pick else (ranked_iso[:1] if ranked_iso else [])

    steps: list[dict] = []
    plan_open: set[str] = set()
    plan_closed: set[str] = set()
    step_no = 0

    def _append_step(
        *,
        action: str,
        fid: str | None,
        section: str,
        reason: str,
        nodes_restored: int = 0,
        plan_effect: str | None = None,
        plan_effect_target: str | None = None,
    ) -> None:
        nonlocal step_no
        step_no += 1
        if action == "NOTE" or not fid:
            note_step = {
                "action": action,
                "switchId": None,
                "deviceType": "note",
                "section": section,
                "feeder": primary_feeder,
                "location": "",
                "instructionTh": reason,
                "reason": f"ขั้นที่ {step_no} — {reason}",
                "nodesRestored": nodes_restored,
            }
            if plan_effect:
                note_step["planEffect"] = plan_effect
            if plan_effect_target:
                note_step["planEffectTarget"] = plan_effect_target
            steps.append(note_step)
            return
        props, kind = _device_meta(s, fid)
        steps.append({
            "action": action,
            "switchId": fid,
            "deviceType": kind,
            "section": section,
            "feeder": props.get("feeder", "?"),
            "location": props.get("location", ""),
            "instructionTh": _step_instruction_th(s, action, fid),
            "reason": f"ขั้นที่ {step_no} — {reason}",
            "nodesRestored": nodes_restored,
        })

    for fid in iso_switches:
        props, kind = _device_meta(s, fid)
        if kind == "recloser":
            label = "Recloser บนไลน์แยก"
            extra = " — จ่ายย้อนจากปลายสาย/tie ได้ ไม่ต้องเปิด tie"
        else:
            label = "สวิตช์ tie" if fid in s.tie_switch_ids else "สวิตช์"
            extra = ""
        back_c, back_n, tie_hint = _best_tie_backfeed_if_open(s, fid, work_zone)
        tie_note = (
            f" · ถ่ายโหลดผ่าน tie ได้ ~{back_c:,} ลูกค้า"
            if back_c else ""
        )
        _append_step(
            action="OPEN",
            fid=fid,
            section="isolation",
            reason=f"แยก{context_label} ({label}){extra}{tie_note}",
        )
        plan_open.add(fid)

    iso_rc = next((f for f in iso_switches if f in s.recloser_status), None)
    cumulative_energized = _energization_under_plan(s, frozenset(plan_open), frozenset())
    used_ties: set[str] = set()

    for tie_fid in _rc_grid_tie_close_candidates(
        s, iso_rc, primary_feeder, plan_open, plan_closed,
    ):
        if tie_fid in used_ties:
            continue
        used_ties.add(tie_fid)
        plan_closed.add(tie_fid)
        baseline = cumulative_energized
        cumulative_energized = _energization_under_plan(
            s, frozenset(plan_open), frozenset(plan_closed),
        )
        gained = cumulative_energized - baseline
        gained_n = len(gained)
        gained_c = _customers_in_nodes(s, gained) or gained_n
        props, _ = _device_meta(s, tie_fid)
        f1, f2 = str(props.get("feeder", "")), str(props.get("feeder2", ""))
        neighbor = f2 if f1 == primary_feeder else f1
        cust_txt = f" · ~{gained_c:,} ลูกค้า" if gained_c else ""
        _append_step(
            action="CLOSE",
            fid=tie_fid,
            section="restoration",
            reason=(
                f"ปิด tie ถ่ายโหลดจากฟีดเดอร์ {neighbor} "
                f"ย้อนกลับหลังปลด Recloser (+{gained_n:,} nodes{cust_txt})"
            ),
            nodes_restored=gained_n,
        )

    for _ in range(8):
        cands = _cross_feeder_restoration_candidates(
            s, work_zone, cumulative_energized, plan_open=frozenset(plan_open),
        )
        cands = _skip_low_impact_restorations(cands)
        if not cands:
            break
        gained_c, gained_n, tie_fid = cands[0]
        if tie_fid in used_ties or tie_fid in plan_open or gained_n <= 0:
            break
        used_ties.add(tie_fid)
        plan_closed.add(tie_fid)
        cumulative_energized = _energization_under_plan(
            s, frozenset(plan_open), frozenset(plan_closed),
        )
        cust_txt = f" · ~{gained_c:,} ลูกค้า" if gained_c else ""
        _append_step(
            action="CLOSE",
            fid=tie_fid,
            section="restoration",
            reason=(
                f"ปิด tie ถ่ายโหลดจากฟีดเดอร์เพื่อนบ้าน "
                f"(+{gained_n:,} nodes{cust_txt})"
            ),
            nodes_restored=gained_n,
        )

    line_end_cands = _line_end_sectionalizing_candidates(
        s, work_zone, primary_feeder, plan_open, plan_closed,
    )
    line_end_cands = _skip_low_impact_restorations(line_end_cands)
    for rescued_c, rescued_n, sw_fid in line_end_cands:
        if sw_fid in plan_open or sw_fid in plan_closed:
            continue
        plan_open.add(sw_fid)
        cust_txt = f" · ~{rescued_c:,} ลูกค้า" if rescued_c else ""
        _append_step(
            action="OPEN",
            fid=sw_fid,
            section="restoration",
            reason=(
                f"เปิด {sw_fid} แยกวงจร (ปิดวงจรฝั่งจุดฟอลต์) "
                f"เพื่อเตรียมจ่ายจากปลายสาย (~{rescued_n:,} nodes{cust_txt})"
            ),
            nodes_restored=rescued_n,
        )
        cumulative_energized = _combined_plan_energized(
            s, primary_feeder, plan_open, plan_closed,
        )
        back_n, back_c = _line_end_backfeed_summary(
            s, work_zone, primary_feeder, plan_open,
        )
        if _is_kua_feeder(primary_feeder) and back_n > 0:
            _append_step(
                action="NOTE",
                fid=None,
                section="restoration",
                reason=(
                    f"ยืนยัน: ปลายสาย {primary_feeder} จ่ายย้อนกลับแล้ว "
                    f"~{back_n:,} nodes · ~{back_c:,} ลูกค้าใช้งานได้ — "
                    f"ลดผลกระทบสูงสุดแล้ว เริ่มซ่อมจุดฟอลต์เมื่อพร้อม"
                ),
                nodes_restored=back_n,
                plan_effect="kuaLineEndAck",
            )
        break

    for i, step in enumerate(steps):
        step["step"] = i + 1

    de_iso = all_nodes - _combined_plan_energized(
        s, primary_feeder, plan_open, plan_closed,
    )

    total_restorable    = sum(st["nodesRestored"] for st in steps)
    nodes_irrecoverable = len(work_zone)
    fault_pct = round(nodes_irrecoverable / max(1, len(all_nodes)) * 100, 2)

    iso_count = sum(1 for st in steps if st.get("section") == "isolation")
    res_count = sum(1 for st in steps if st.get("section") == "restoration")
    next_step = steps[0] if steps else None
    next_hint = (
        next_step["instructionTh"]
        if next_step
        else "ไม่มีขั้นตอน — ตรวจสอบสถานะเครือข่าย"
    )

    operator_brief = meta.get("operatorBrief") or (
        f"{context_label} · แยก {iso_count} ขั้น · คืนไฟ {res_count} ขั้น"
    )

    return {
        "steps":              steps,
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
            f"โซนปฏิบัติงาน {nodes_irrecoverable:,} ({fault_pct}%) · "
            f"แผน {len(steps)} ขั้น (แยก {iso_count} / คืน {res_count}) · "
            f"คืนไฟได้ {total_restorable:,} nodes"
        ),
        **meta,
    }


def generate_maintenance_switching_plan(s: NetworkState) -> dict:
    if not s.maint_active:
        return {"error": "ยังไม่ได้กำหนดโซนบำรุงรักษา — กรอกพิกัดเริ่มต้น/สิ้นสุดก่อน"}

    work_zone = compute_maintenance_zone_nodes(s)
    start_txt = _format_fault_coords(s.maint_start_lat, s.maint_start_lon)
    end_txt   = _format_fault_coords(s.maint_end_lat, s.maint_end_lon)
    job_name  = s.maint_job_name or "—"
    job_no    = s.maint_job_number or "—"
    coords_txt = f"{start_txt} → {end_txt}"
    operator_brief = (
        f"งาน {job_no} · {job_name} · ฟีดเดอร์ {s.maint_feeder or '?'} · "
        f"โซน {coords_txt}"
    )
    return _switching_plan_for_zone(
        s, work_zone,
        context_label="โซนบำรุงรักษา",
        meta={
            "planType":         "maintenance",
            "feeder":           s.maint_feeder,
            "jobName":          job_name,
            "jobNumber":        job_no,
            "maintStartCoords": start_txt,
            "maintEndCoords":   end_txt,
            "maintCoords":      coords_txt,
            "operatorBrief":    operator_brief,
            "faultFeeder":      s.maint_feeder,
            "faultCoords":      coords_txt,
        },
    )

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


def _buffer_polyline_ring_utm(
    pts: list[tuple[float, float]],
    half_width_m: float = 45.0,
) -> list[tuple[float, float]] | None:
    """Corridor polygon hugging a polyline — clearer than a wide convex hull."""
    if not pts:
        return None
    if len(pts) == 1:
        x, y = pts[0]
        return _buffer_ring_utm(x, y, half_width_m)
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for i, (x, y) in enumerate(pts):
        if i == 0:
            dx, dy = pts[1][0] - x, pts[1][1] - y
        elif i == len(pts) - 1:
            dx, dy = x - pts[i - 1][0], y - pts[i - 1][1]
        else:
            dx, dy = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
        ln = math.hypot(dx, dy)
        if ln < 1e-9:
            continue
        nx, ny = -dy / ln * half_width_m, dx / ln * half_width_m
        left.append((x + nx, y + ny))
        right.append((x - nx, y - ny))
    if len(left) < 2:
        x, y = pts[0]
        return _buffer_ring_utm(x, y, half_width_m)
    ring = left + list(reversed(right))
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def outage_polygons(s: NetworkState) -> list[dict]:
    """Outage overlay — delegates to ``live_map_bundle`` (R51)."""
    return get_outage_polygons_cached(s)


# ─────────────────────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
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
        "faultCoordSnapM":    _FAULT_COORD_SNAP_M,
        "faultMapClickSnapM": _FAULT_MAP_CLICK_SNAP_M,
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
    features, _, _ = get_live_conductors_view(s)
    return jsonify({"type": "FeatureCollection", "features": features})


@app.route("/switches")
def switches():
    s = get_state()
    return jsonify({"type": "FeatureCollection", "features": _switches_geojson(s)})


@app.route("/reclosers")
def reclosers():
    s = get_state()
    return jsonify({"type": "FeatureCollection", "features": _reclosers_geojson(s)})


@app.route("/reclosers/<fid>/toggle", methods=["POST"])
def toggle_recloser(fid: str):
    s = get_state()
    if fid not in s.recloser_status:
        abort(404)
    nxt = 0 if s.recloser_status.get(fid, 1) == 1 else 1
    s.recloser_status[fid] = nxt
    _invalidate_compute_cache(s)
    return jsonify({
        "id": fid, "status": nxt,
        "state": "CLOSE" if nxt == 1 else "OPEN",
        "deviceType": "recloser",
    })


@app.route("/transformers")
def transformers():
    return jsonify({"type": "FeatureCollection", "features": get_state().transformers})


@app.route("/feeders")
def feeders():
    s = get_state()
    energized = _stats_energized_nodes(s)
    live, _, _ = get_live_conductors_view(s)
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
    return jsonify({
        "type": "FeatureCollection",
        "features": _substations_geojson(s),
    })


@app.route("/scada")
def scada():
    s = get_state()
    _, feeders_affected, feeders_source_open = get_live_conductors_view(s)
    return jsonify(_scada_payload(s, feeders_affected, feeders_source_open))


@app.route("/live-refresh")
def live_refresh():
    """Bundled map refresh after operator switch/RC actions (R51)."""
    s = get_state()
    return jsonify(_cc_get(s, "live_refresh", lambda: _build_live_refresh_payload(s)))


@app.route("/outage-polygon")
def outage_polygon_route():
    s = get_state()
    return jsonify({
        "type": "FeatureCollection",
        "features": get_outage_polygons_cached(s),
    })


# ── Write endpoints ─────────────────────────────────────────────────────────
@app.route("/switches/<fid>/toggle", methods=["POST"])
def toggle_switch(fid: str):
    s = get_state()
    if fid not in s.switch_node:
        abort(404)
    nxt = 0 if s.switch_status.get(fid, 1) == 1 else 1
    s.switch_status[fid] = nxt
    _invalidate_compute_cache(s)
    return jsonify({"id": fid, "status": nxt, "state": "CLOSE" if nxt == 1 else "OPEN"})


@app.route("/substations/<fid>/toggle", methods=["POST"])
def toggle_substation(fid: str):
    s = get_state()
    if fid not in s.cb_node:
        abort(404)
    nxt = 0 if s.cb_status.get(fid, 1) == 1 else 1
    s.cb_status[fid] = nxt
    _invalidate_compute_cache(s)
    return jsonify({"id": fid, "status": nxt, "state": "CLOSE" if nxt == 1 else "OPEN"})


def _take_snapshot(s: NetworkState) -> None:
    """Capture switch/CB/RC state at fault (or maintenance) placement for restore."""
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_cb = dict(s.cb_status)
    s.snapshot_recloser = dict(s.recloser_status)


def _restore_snapshot(s: NetworkState) -> None:
    if s.snapshot_switch is not None:
        s.switch_status = dict(s.snapshot_switch)
    if s.snapshot_cb is not None:
        s.cb_status = dict(s.snapshot_cb)
    if s.snapshot_recloser is not None:
        s.recloser_status = dict(s.snapshot_recloser)
    s.snapshot_switch = None
    s.snapshot_cb     = None
    s.snapshot_recloser = None


@app.route("/fault/nearby")
def fault_nearby_feeders():
    """Feeders near reported coords — for operator feeder picker (R28)."""
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
    except (KeyError, TypeError, ValueError):
        abort(400)
    max_m = float(request.args.get("maxM", _FAULT_COORD_SNAP_M))
    s = get_state()
    xu, yu = to_utm(lon, lat)
    candidates = find_conductor_snaps_near(s, xu, yu, max_dist_m=max_m)
    return jsonify({
        "lat": lat,
        "lon": lon,
        "candidates": candidates,
        "suggested": candidates[0]["feeder"] if candidates else None,
    })


@app.route("/fault", methods=["POST"])
def set_fault():
    s    = get_state()
    data = request.get_json(force=True) or {}
    lat, lon = float(data["lat"]), float(data["lon"])
    cause = normalize_cause(str(data.get("cause", FAULT_CAUSES[0])))
    phase = normalize_phase(str(data.get("phase", "ALL")))
    feeder_hint = str(data.get("feeder") or "").strip() or None
    feeders_raw = data.get("feeders")
    selected_feeders: list[str] = []
    if isinstance(feeders_raw, list):
        selected_feeders = [
            str(f).strip() for f in feeders_raw if str(f).strip()
        ]
    if feeder_hint and feeder_hint not in selected_feeders:
        selected_feeders.insert(0, feeder_hint)
    map_click = bool(data.get("mapClick"))
    snap_m = _FAULT_MAP_CLICK_SNAP_M if map_click else _FAULT_COORD_SNAP_M

    xu, yu = to_utm(lon, lat)
    snap_feeder, nearest, _ = snap_fault_to_network(
        s, xu, yu,
        feeder_hint=feeder_hint or (selected_feeders[0] if selected_feeders else None),
        max_dist_m=snap_m,
    )
    if not nearest:
        return jsonify({
            "active": False,
            "error": (
                f"ไม่พบสายไฟฟ้าภายใน {snap_m:.0f} m จากพิกัดนี้"
                + (f" (ฟีดเดอร์ {feeder_hint})" if feeder_hint else "")
                + (
                    " — คลิกให้ใกล้สายบนแผนที่มากขึ้น"
                    if map_click
                    else " — ปรับพิกัดให้ใกล้ถนนข้างเส้นทางสายมากขึ้น"
                )
            ),
            "feeder": None, "lat": None, "lon": None,
        })

    # Snapshot the pre-fault switching state BEFORE the operator starts
    # isolating / restoring, so /fault DELETE can roll us back cleanly.
    _take_snapshot(s)

    primary = snap_feeder or s.node_feeder.get(nearest, "UNK")
    if selected_feeders:
        scope = [f for f in selected_feeders if f in s.feeder_edge_count]
        if not scope:
            scope = [primary]
    else:
        scope = [primary]

    s.fault_node   = nearest
    s.fault_feeder = scope[0]
    s.fault_feeders = scope
    s.fault_lat    = lat
    s.fault_lon    = lon
    s.fault_cause  = cause
    s.fault_phase  = phase
    s.fault_started_at = time.time()

    # R68: fault behind RC → trip protecting RC before zone/cache compute so the
    # outage corridor stops at the RC (snapshot already captured CLOSED state).
    tripped_rcs = _auto_trip_protecting_reclosers(s)

    _invalidate_compute_cache(s)
    # Warm fault-zone cache once so parallel /conductor + /outage-polygon reuse it (R36).
    affected = _cc_get(s, "fault_topo", lambda: compute_fault_affected_nodes(s))
    nodes_off = len(affected)
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
        "feeders": s.fault_feeders,
        "lat": s.fault_lat, "lon": s.fault_lon,
        "cause": cause, "phase": phase, "outageId": s.fault_id,
        "trippedReclosers": tripped_rcs,
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
    s.fault_feeders = []
    s.fault_cause = s.fault_phase = None
    s.fault_id = None
    s.fault_started_at = None

    _clear_switching_plan_runtime(s)

    # Restore pre-switching state (overrides original "open all switches" bug)
    _restore_snapshot(s)
    _invalidate_compute_cache(s)

    return jsonify({"active": False, "feeder": None, "lat": None, "lon": None,
                    "outageId": cleared_id})


@app.route("/fault", methods=["GET"])
def get_fault():
    s = get_state()
    return jsonify({
        "active": bool(s.fault_node), "feeder": s.fault_feeder,
        "feeders": s.fault_feeders,
        "lat": s.fault_lat, "lon": s.fault_lon,
        "coords": _format_fault_coords(s.fault_lat, s.fault_lon),
        "cause": s.fault_cause, "phase": s.fault_phase,
    })


@app.route("/maintenance", methods=["POST"])
def set_maintenance():
    s = get_state()
    data = request.get_json(force=True) or {}
    try:
        start_lat = float(data["startLat"])
        start_lon = float(data["startLon"])
        end_lat   = float(data["endLat"])
        end_lon   = float(data["endLon"])
    except (KeyError, TypeError, ValueError):
        return jsonify({
            "active": False,
            "error": "กรุณาระบุพิกัดเริ่มต้นและสิ้นสุด (startLat/startLon/endLat/endLon)",
        })

    job_name   = str(data.get("jobName", "")).strip() or None
    job_number = str(data.get("jobNumber", "")).strip() or None

    start_node, start_feeder = _snap_latlon_to_node(s, start_lat, start_lon)
    end_node, end_feeder     = _snap_latlon_to_node(s, end_lat, end_lon)
    if not start_node or not end_node:
        return jsonify({
            "active": False,
            "error": "ไม่พบโหนดเครือข่ายใกล้พิกัด — ลองเลื่อนให้ใกล้สายจำหน่าย",
        })

    feeder = start_feeder
    if end_feeder and start_feeder and end_feeder != start_feeder:
        feeder = start_feeder or end_feeder

    _take_snapshot(s)

    s.maint_active     = True
    s.maint_start_lat  = start_lat
    s.maint_start_lon  = start_lon
    s.maint_end_lat    = end_lat
    s.maint_end_lon    = end_lon
    s.maint_start_node = start_node
    s.maint_end_node   = end_node
    s.maint_feeder     = feeder
    s.maint_job_name   = job_name
    s.maint_job_number = job_number

    zone_nodes = len(compute_maintenance_zone_nodes(s))
    _invalidate_compute_cache(s)
    return jsonify({
        "active": True,
        "feeder": feeder,
        "startLat": start_lat, "startLon": start_lon,
        "endLat": end_lat, "endLon": end_lon,
        "jobName": job_name, "jobNumber": job_number,
        "zoneNodes": zone_nodes,
        "startCoords": _format_fault_coords(start_lat, start_lon),
        "endCoords":   _format_fault_coords(end_lat, end_lon),
    })


@app.route("/maintenance", methods=["DELETE"])
def clear_maintenance():
    s = get_state()
    s.maint_active = False
    s.maint_start_lat = s.maint_start_lon = s.maint_end_lat = s.maint_end_lon = None
    s.maint_start_node = s.maint_end_node = s.maint_feeder = None
    s.maint_job_name = s.maint_job_number = None
    _restore_snapshot(s)
    _invalidate_compute_cache(s)
    return jsonify({"active": False})


@app.route("/maintenance", methods=["GET"])
def get_maintenance():
    s = get_state()
    return jsonify({
        "active": s.maint_active,
        "feeder": s.maint_feeder,
        "startLat": s.maint_start_lat, "startLon": s.maint_start_lon,
        "endLat": s.maint_end_lat, "endLon": s.maint_end_lon,
        "jobName": s.maint_job_name, "jobNumber": s.maint_job_number,
        "startCoords": _format_fault_coords(s.maint_start_lat, s.maint_start_lon),
        "endCoords":   _format_fault_coords(s.maint_end_lat, s.maint_end_lon),
    })


@app.route("/maintenance/switching-plan", methods=["POST"])
def maintenance_switching_plan():
    s = get_state()
    result = generate_maintenance_switching_plan(s)
    if not result.get("error"):
        _store_switching_plan_runtime(s, result.get("steps", []))
        result.update(_switching_plan_runtime_payload(s))
    return jsonify(result)


@app.route("/switching-plan/normalize", methods=["POST"])
def switching_plan_normalize():
    return jsonify(generate_normalization_plan(get_state()))


@app.route("/switching-plan", methods=["POST"])
def switching_plan():
    return jsonify(generate_switching_plan(get_state()))


@app.route("/switching-plan/normalize/execute/<int:step_idx>", methods=["POST"])
def execute_normalization_step(step_idx: int):
    data   = request.get_json(force=True)
    action = data.get("action")
    sw_id  = data.get("switchId")
    if action == "NOTE" or not sw_id:
        return jsonify({"ok": True, "skipped": True, "action": action})
    s = get_state()
    if sw_id in s.recloser_status:
        s.recloser_status[sw_id] = 1 if action == "CLOSE" else 0
        new_status = s.recloser_status[sw_id]
    elif sw_id in s.switch_node:
        s.switch_status[sw_id] = 1 if action == "CLOSE" else 0
        new_status = s.switch_status[sw_id]
    else:
        abort(404)
    _invalidate_compute_cache(s)
    return jsonify({"ok": True, "switchId": sw_id, "action": action,
                    "newStatus": new_status})


@app.route("/switching-plan/execute/<int:step_idx>", methods=["POST"])
def execute_step(step_idx: int):
    data   = request.get_json(force=True)
    action = data.get("action")
    sw_id  = data.get("switchId")
    s      = get_state()
    plan_step = _switching_plan_step_at(s, step_idx)

    if action == "NOTE" or not sw_id:
        effect = (
            (plan_step or {}).get("planEffect")
            or data.get("planEffect")
        )
        instr = str(
            (plan_step or {}).get("instructionTh")
            or (plan_step or {}).get("reason")
            or data.get("instructionTh")
            or ""
        )
        if effect == "kuaLineEndAck" or (
            _is_kua_feeder(s.fault_feeder or "")
            and "จ่ายไฟจาก KUA01 (ปลายสาย)" in instr
        ):
            s.kua_line_end_display_ack = True
        s.switching_plan_executed = max(s.switching_plan_executed, step_idx)
        _invalidate_compute_cache(s)
        # R75: do not rebuild liveMap here — NOTE ack must return immediately.
        return jsonify({
            "ok": True,
            "action": action,
            "planEffect": effect,
            "kuaLineEndAck": s.kua_line_end_display_ack,
            "lineDisplayPhysical": _display_restoration_live(s),
            **_switching_plan_runtime_payload(s),
        })

    if sw_id in s.recloser_status:
        s.recloser_status[sw_id] = 1 if action == "CLOSE" else 0
        new_status = s.recloser_status[sw_id]
        device_type = "recloser"
    elif sw_id in s.switch_node:
        s.switch_status[sw_id] = 1 if action == "CLOSE" else 0
        new_status = s.switch_status[sw_id]
        device_type = "switch"
    else:
        abort(404)
    s.switching_plan_executed = max(s.switching_plan_executed, step_idx)
    _invalidate_compute_cache(s)
    # R75: return device status immediately. Full map paint stays on
    # /live-refresh (frontend refreshLiveAfterPlanStep) so OPEN PDA07S-12
    # does not hang waiting for a multi-minute liveMap rebuild.
    return jsonify({
        "ok": True,
        "switchId": sw_id,
        "action": action,
        "newStatus": new_status,
        "deviceType": device_type,
        "state": "CLOSE" if new_status == 1 else "OPEN",
        "lineDisplayPhysical": _display_restoration_live(s),
        **_switching_plan_runtime_payload(s),
    })


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
    s = get_state()
    print("Warming live map cache…", flush=True)
    _cc_get(s, "live_refresh", lambda: _build_live_refresh_payload(s))
    port = int(os.environ.get("PORT", "5000"))
    print(f"\nSERVER READY → http://0.0.0.0:{port}", flush=True)
    print("  UI: templates/indexpro.html\n", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

"""Quick verify KUA01 zone1 step 4 — PDA02 backfeed colour + outage trim."""
import os
import time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import app as a


def t(label: str) -> None:
    print(f"  [{time.perf_counter() - t0:.1f}s] {label}", flush=True)


t0 = time.perf_counter()
print("Loading state…", flush=True)
s = a.get_state()
a.apply_startup_cb_closed(s)
t("state ready")

hop = a._kua_feeder_hop_from_seed(s, "KUA01")
h08 = a._kua01_device_hop(s, "PDA10S-08")
h13 = a._kua01_device_hop(s, "PDA10S-13")
node = min(
    (n for n, h in hop.items() if abs(h - (h08 + h13) // 2) <= 2),
    key=lambda n: abs(hop[n] - (h08 + h13) // 2),
)
s.fault_node = node
s.fault_feeder = "KUA01"
s.fault_feeders = ["KUA01"]
s.snapshot_switch = dict(s.switch_status)
s.snapshot_recloser = dict(s.recloser_status)
s.recloser_status["PDA10R-01"] = 0
s.switch_status["PDA10S-13"] = 0
s.kua_line_end_display_ack = True
s.switch_status["PDA02S-08"] = 1
for fid in s.feeder_cbs.get("PDA02", []):
    s.cb_status[fid] = 1
a._invalidate_compute_cache(s)
t("scenario step 4 set")

tie = s.switch_node["PDA02S-08"]
rc = s.recloser_node["PDA10R-01"]
rc_h = hop[rc]
back = a._kua_interconnect_backfeed_nodes(s, "KUA01")
live = a.compute_live_energization(s)
t(f"live={len(live)} backfeed={len(back)}")

past_rc_live = [n for n in live if hop.get(n, -1) > rc_h]
supply = a._compute_node_supply_feeders(s, live)
past_rc_pda2 = [n for n in live if hop.get(n, -1) > rc_h and supply.get(n) == "PDA02"]
print(f"nodes live past RC hop: {len(past_rc_live)}  PDA02 supply past RC: {len(past_rc_pda2)}")
pda2_nodes = sum(1 for n in back if supply.get(n) == "PDA02")
print(f"backfeed PDA02 supply nodes={pda2_nodes}/{len(back)}")
print(f"restoration_live={a._display_restoration_live(s)}")

bundle = a._live_map_bundle(s)
t("live_map_bundle built")
conds = bundle["conductors"]
rc_h = hop[rc]
pda2_kua_past_rc = 0
pda2_kua_at_rc = 0
pda2_kua_total = 0
for i, f in enumerate(conds):
    p = f["properties"]
    if p.get("supplyFeeder") != "PDA02" or p["status"] != "on":
        continue
    gis = p.get("feeder", "")
    if not str(gis).startswith("KUA"):
        continue
    pda2_kua_total += 1
    keys = s.conductor_keys[i]
    hops = [hop.get(k) for k in keys if k in hop]
    if hops and max(hops) <= rc_h:
        pda2_kua_at_rc += 1
    if hops and any(h > rc_h for h in hops):
        pda2_kua_past_rc += 1
print(f"KUA GIS PDA02: total={pda2_kua_total} at/before RC={pda2_kua_at_rc} past RC={pda2_kua_past_rc}")
print(f"backfeed corridor nodes={len(back)} paint_zone={len(a._kua_pda_backfeed_paint_zone(s,'KUA01',hop=hop,removed=a._kua_backfeed_trace_removed(s)))}")

pda2_seg = sum(
    1 for f in conds
    if f["properties"].get("supplyFeeder") == "PDA02"
    and f["properties"]["status"] == "on"
)
off_kua = sum(
    1 for f in conds
    if f["properties"]["feeder"] == "KUA01" and f["properties"]["status"] == "off"
)
print(f"PDA02 coloured segs ON={pda2_seg}  KUA01 OFF segs={off_kua}")
print(f"outage polygons={len(bundle['outage_polys'])}")

aff = a._display_affected_nodes(s)
print(f"affected nodes={len(aff)}")

ok = (
    a._display_restoration_live(s)
    and len(past_rc_pda2) == 0
    and pda2_kua_past_rc == 0
    and pda2_kua_at_rc > 0
    and pda2_nodes > 0
)
print("RESULT:", "PASS" if ok else "FAIL")

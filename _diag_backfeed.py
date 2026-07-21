"""Temporary diagnostic — backfeed / RC / energization."""
from collections import deque

import app as a

s = a.build_state()
a.apply_startup_cb_closed(s)

for fid in ["PDA10R-01", "PDA10S-13", "PDA02S-08", "PDA02R-01"]:
    if "R-" in fid and fid.endswith("R-01") and "S" not in fid:
        node = s.recloser_node.get(fid)
        st = s.recloser_status.get(fid)
        print(f"{fid}: node={node} status={st}")
    else:
        node = s.switch_node.get(fid)
        st = s.switch_status.get(fid)
        ic = fid in s.interconnect_switch_ids
        sec = fid in a._sectionalizing_switch_ids(s)
        print(f"{fid}: node={node} status={st} ic={ic} sec={sec}")

lat, lon = 11.92459, 99.73421
x, y = a.to_utm(lon, lat)
coord_node = a.find_nearest(s, x, y)
print(f"Coord {lat},{lon} -> node {coord_node} feeder={s.node_feeder.get(coord_node)}")

rc_node = s.recloser_node["PDA10R-01"]
print(f"PDA10R-01 degree={len(s.adjacency.get(rc_node, []))} nbs={list(s.adjacency.get(rc_node, []))[:6]}")

nbs = list(s.adjacency.get(rc_node, []))
load_nb = nbs[0] if nbs else rc_node

s.fault_node = load_nb
s.fault_feeder = "KUA01"
s.fault_feeders = ["KUA01"]
s.snapshot_switch = dict(s.switch_status)
s.snapshot_recloser = dict(s.recloser_status)
a._invalidate_compute_cache(s)

s.recloser_status["PDA10R-01"] = 0
s.switch_status["PDA10S-13"] = 0
s.switch_status["PDA02S-08"] = 1
for fid in s.feeder_cbs.get("PDA02", []):
    s.cb_status[fid] = 1
a._invalidate_compute_cache(s)

live = a.compute_live_energization(s)
rest_live = a._display_restoration_live(s)
stats = a._network_energization_stats(s)
print(f"\nAfter PDA02 backfeed: restoration_live={rest_live} nodes_on={stats['nodesOn']} nodes_off={stats['nodesOff']}")

tie_node = s.switch_node["PDA02S-08"]
rc = s.recloser_node["PDA10R-01"]


def reach_from(start, barrier):
    seen = {start}
    q = deque([start])
    while q:
        c = q.popleft()
        for nb in s.adjacency.get(c, []):
            if nb not in seen and nb not in barrier:
                seen.add(nb)
                q.append(nb)
    return seen


barrier = {rc}
from_tie = reach_from(tie_node, barrier)
rc_nbs = set(s.adjacency.get(rc, []))
src_side = [nb for nb in rc_nbs if nb not in from_tie]
print(f"RC source-side neighbors: {src_side[:5]}")
for nb in src_side[:5]:
    print(f"  {nb} live={nb in live} feeder={s.node_feeder.get(nb)}")

print(f"Coord node live={coord_node in live} in_from_tie={coord_node in from_tie}")
supply = a._compute_node_supply_feeders(s, live)
print(f"Coord supply={supply.get(coord_node)}")

for cw, keys in zip(s.conductor_wgs, s.conductor_keys):
    for lo, la in cw["geometry"]["coordinates"]:
        if abs(la - lat) < 0.003 and abs(lo - lon) < 0.003:
            p = cw["properties"]
            print(
                f"Seg: feeder={p['feeder']} status={p.get('status')} "
                f"supply={p.get('supplyFeeder')} all_live={all(k in live for k in keys)}"
            )

# forced dark check
forced = a._open_recloser_forced_dark(s)
phys_raw = a.compute_energization_ex(
    s.adjacency, s.node_feeder,
    s.cb_node, s.cb_feeder, s.cb_status, s.feeder_cbs,
    s.switch_node, s.switch_status, s.fault_node,
    a._live_display_cut_ids(s),
    s.recloser_node, s.recloser_status,
)
print(f"\nphys nodes={len(phys_raw)} forced_dark={len(forced)}")
src_energized_wrong = [nb for nb in src_side if nb in live]
print(f"Source-side wrongly live: {len(src_energized_wrong)} {src_energized_wrong[:5]}")

# Scenario 3: only open PDA10S-13, line-end backfeed (no PDA02)
s2 = a.build_state()
a.apply_startup_cb_closed(s2)
s2.fault_node = load_nb
s2.fault_feeder = "KUA01"
s2.fault_feeders = ["KUA01"]
s2.snapshot_switch = dict(s2.switch_status)
s2.snapshot_recloser = dict(s2.recloser_status)
s2.recloser_status["PDA10R-01"] = 0
s2.switch_status["PDA10S-13"] = 0
a._invalidate_compute_cache(s2)
live2 = a.compute_live_energization(s2)
rest2 = a._display_restoration_live(s2)
stats2 = a._network_energization_stats(s2)
print(f"\nKUA line-end only: restoration_live={rest2} nodes_on={stats2['nodesOn']}")
print(f"Coord node live={coord_node in live2}")

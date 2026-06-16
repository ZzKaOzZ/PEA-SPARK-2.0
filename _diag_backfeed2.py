"""Targeted diagnostic — RC bypass, supply color, line-end backfeed."""
from collections import deque

import app as a

lat, lon = 11.92459, 99.73421


def setup_fault_at_rc_load_side():
    s = a.build_state()
    a.apply_startup_cb_closed(s)
    rc_node = s.recloser_node["PDA10R-01"]
    nbs = list(s.adjacency.get(rc_node, []))
    load_nb = max(nbs, key=lambda n: s.node_xy[n][0])  # pick one neighbor
    s.fault_node = load_nb
    s.fault_feeder = "KUA01"
    s.fault_feeders = ["KUA01"]
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_recloser = dict(s.recloser_status)
    a._invalidate_compute_cache(s)
    return s, rc_node, load_nb


def bfs_from(start, s, barrier=None):
    barrier = barrier or set()
    seen = {start}
    q = deque([start])
    while q:
        c = q.popleft()
        for nb in s.adjacency.get(c, []):
            if nb not in seen and nb not in barrier:
                seen.add(nb)
                q.append(nb)
    return seen


def check_main_line(s, rc_node, live):
    seed = a._kua_source_seed_node(s, "KUA01")
    src_wing = bfs_from(seed, s, barrier={rc_node})
    load_wing = bfs_from(s.fault_node, s, barrier={rc_node})
    both = src_wing & load_wing
    src_only = src_wing - load_wing
    wrongly = [n for n in src_only if n in live]
    print(f"KUA seed={seed}")
    print(f"src_wing={len(src_wing)} load_wing={len(load_wing)} ring_bypass={len(both)}")
    print(f"src_only wrongly live={len(wrongly)} (sample: {wrongly[:3]})")
    return wrongly


def seg_supply_diag(s, live):
    x, y = a.to_utm(lon, lat)
    coord_node = a.find_nearest(s, x, y)
    supply = a._compute_node_supply_feeders(s, live)
    conductors, _, _ = a.build_live_conductors(s)
    print(f"coord_node={coord_node} supply={supply.get(coord_node)}")
    off_color = 0
    pda2_color = 0
    for feat in conductors:
        p = feat["properties"]
        for cl in feat["geometry"]["coordinates"]:
            lo, la = cl
            if abs(la - lat) < 0.003 and abs(lo - lon) < 0.003:
                sf = p.get("supplyFeeder")
                if p["status"] == "off":
                    off_color += 1
                elif sf == "PDA02":
                    pda2_color += 1
                elif sf is None and p["status"] == "on":
                    pass
    print(f"near coord: off={off_color} pda02_color={pda2_color}")


print("=== Scenario A: PDA02 backfeed, RC open, S-13 open ===")
s, rc_node, _ = setup_fault_at_rc_load_side()
s.recloser_status["PDA10R-01"] = 0
s.switch_status["PDA10S-13"] = 0
s.switch_status["PDA02S-08"] = 1
a._invalidate_compute_cache(s)
live = a.compute_live_energization(s)
print(f"live={len(live)} rest={a._display_restoration_live(s)}")
check_main_line(s, rc_node, live)
seg_supply_diag(s, live)

print("\n=== Scenario B: KUA line-end only (S-13 open, RC open) ===")
s2, rc_node2, _ = setup_fault_at_rc_load_side()
s2.recloser_status["PDA10R-01"] = 0
s2.switch_status["PDA10S-13"] = 0
a._invalidate_compute_cache(s2)
live2 = a.compute_live_energization(s2)
line_on = a._kua_feeder_energization_ex(s2, "KUA01")
print(f"live={len(live2)} line_on={len(line_on)} rest={a._display_restoration_live(s2)}")
x, y = a.to_utm(lon, lat)
cn = a.find_nearest(s2, x, y)
print(f"coord live={cn in live2} in line_on={cn in line_on}")
stats = a._network_energization_stats(s2)
print(f"stats nodes_on={stats['nodesOn']}")
conductors, _, _ = a.build_live_conductors(s2)
off = sum(
    1 for f in conductors
    if f["properties"]["status"] == "off"
    and any(abs(c[1] - lat) < 0.003 and abs(c[0] - lon) < 0.003 for c in f["geometry"]["coordinates"])
)
print(f"coord area off segments={off}")

print("\n=== Scenario B2: line_on without blocking S-13 ===")
sw = dict(s2.switch_status)
sw["PDA10S-13"] = 0
# simulate not removing S-13 for line-end backfeed
seed = a._kua_source_seed_node(s2, "KUA01")
removed = {s2.recloser_node["PDA10R-01"]}
if s2.fault_node:
    removed.add(s2.fault_node)
# current: S-13 node also removed
s13 = s2.switch_node["PDA10S-13"]
removed_with_s13 = removed | {s13}
line_full = bfs_from(seed, s2, barrier=removed)  # if S-13 not in barrier
line_no_s13 = bfs_from(seed, s2, barrier=removed)  # S-13 open but not barrier
print(f"line_end reach without S-13 barrier: coord in={cn in line_no_s13}")

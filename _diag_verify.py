"""Verify backfeed fixes."""
import app as a
from collections import Counter

lat, lon = 11.92459, 99.73421


def setup():
    s = a.build_state()
    a.apply_startup_cb_closed(s)
    x, y = a.to_utm(lon, lat)
    cn = a.find_nearest(s, x, y)
    s.fault_node = cn
    s.fault_feeder = "KUA01"
    s.fault_feeders = ["KUA01"]
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_recloser = dict(s.recloser_status)
    s.recloser_status["PDA10R-01"] = 0
    s.switch_status["PDA10S-13"] = 0
    s.switch_status["PDA02S-08"] = 1
    a._invalidate_compute_cache(s)
    return s, cn


s, cn = setup()
hop = a._kua_feeder_hop_from_seed(s, "KUA01")
rc = s.recloser_node["PDA10R-01"]
rc_hop = hop[rc]
src_hop = {n for n, h in hop.items() if h <= rc_hop}
live = a.compute_live_energization(s)
supply = a._compute_node_supply_feeders(s, live)
wrong = [n for n in src_hop if n in live and supply.get(n) == "PDA02"]
print(f"PDA02 backfeed: wrong source-hop nodes={len(wrong)}")

conductors, _, _ = a.build_live_conductors(s)
no_pda2 = off = pda2 = 0
for f in conductors:
    p = f["properties"]
    for cl in f["geometry"]["coordinates"]:
        lo, la = cl
        if abs(la - lat) < 0.008 and abs(lo - lon) < 0.008:
            if p["status"] == "off":
                off += 1
            elif p.get("supplyFeeder") == "PDA02":
                pda2 += 1
            elif p["status"] == "on":
                no_pda2 += 1
            break
print(f"near coord: pda2={pda2} on_no_pda2={no_pda2} off={off}")

# line-end only
s2, cn2 = setup()
s2.switch_status["PDA02S-08"] = 0
a._invalidate_compute_cache(s2)
live2 = a.compute_live_energization(s2)
print(f"line-end only: coord live={cn2 in live2} live_nodes={len(live2)}")
stats = a._network_energization_stats(s2)
print(f"  stats nodes_on={stats['nodesOn']}")

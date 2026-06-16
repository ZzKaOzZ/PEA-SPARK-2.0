"""Hop-based partition diagnostic."""
import app as a

s = a.build_state()
a.apply_startup_cb_closed(s)
hop = a._kua_feeder_hop_from_seed(s, "KUA01")
rc = s.recloser_node["PDA10R-01"]
s13 = s.switch_node["PDA10S-13"]
tie = s.switch_node["PDA02S-08"]
lat, lon = 11.92459, 99.73421
cn = a.find_nearest(s, *a.to_utm(lon, lat))

print(f"PDA10R-01 hop={hop.get(rc)}")
print(f"PDA10S-13 hop={hop.get(s13)}")
print(f"PDA02S-08 hop={hop.get(tie)}")
print(f"coord node hop={hop.get(cn)}")
print(f"KUA seed hop=0 at {a._kua_source_seed_node(s,'KUA01')}")

rc_hop = hop.get(rc, 0)
load_hop = {n for n, h in hop.items() if h > rc_hop}
src_hop = {n for n, h in hop.items() if h <= rc_hop}
print(f"hop partition: src={len(src_hop)} load={len(load_hop)}")
print(f"coord in load_hop={cn in load_hop} in src_hop={cn in src_hop}")

# segments near coord without PDA02 color after backfeed scenario
s.fault_node = cn
s.fault_feeder = "KUA01"
s.fault_feeders = ["KUA01"]
s.snapshot_switch = dict(s.switch_status)
s.snapshot_recloser = dict(s.recloser_status)
s.recloser_status["PDA10R-01"] = 0
s.switch_status["PDA10S-13"] = 0
s.switch_status["PDA02S-08"] = 1
a._invalidate_compute_cache(s)

conductors, _, _ = a.build_live_conductors(s)
no_pda2 = []
for f in conductors:
    p = f["properties"]
    for cl in f["geometry"]["coordinates"]:
        lo, la = cl
        if abs(la - lat) < 0.008 and abs(lo - lon) < 0.008:
            if p["status"] == "on" and p.get("supplyFeeder") != "PDA02":
                no_pda2.append((p.get("supplyFeeder"), p["feeder"], p["status"]))
            break
print(f"\nOn segments near coord WITHOUT PDA02 color: {len(no_pda2)}")
from collections import Counter
print(Counter(no_pda2).most_common(10))

# check main line toward seed - nodes with low hop that get PDA02 backfeed
live = a.compute_live_energization(s)
supply = a._compute_node_supply_feeders(s, live)
wrong = [n for n in src_hop if n in live and supply.get(n) == "PDA02"]
print(f"\nSource-hop nodes with PDA02 supply (wrong): {len(wrong)}")
if wrong[:5]:
    print(" samples:", [(n, hop.get(n)) for n in wrong[:5]])

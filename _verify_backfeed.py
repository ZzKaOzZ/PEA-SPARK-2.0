"""Quick verification — uses cached singleton state (loads once)."""
import os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import app as a

s = a.get_state()
a.apply_startup_cb_closed(s)


def setup_fault():
    rc_node = s.recloser_node["PDA10R-01"]
    nbs = list(s.adjacency.get(rc_node, []))
    load_nb = max(nbs, key=lambda n: s.node_xy[n][0])
    s.fault_node = load_nb
    s.fault_feeder = "KUA01"
    s.fault_feeders = ["KUA01"]
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_recloser = dict(s.recloser_status)
    a._invalidate_compute_cache(s)
    return rc_node, load_nb


def check(label, expect_rest_live):
    live = a.compute_live_energization(s)
    rest = a._display_restoration_live(s)
    stats = a._network_energization_stats(s)
    conductors, _, _ = a.build_live_conductors(s)
    on_segs = sum(1 for f in conductors if f["properties"]["status"] == "on")
    colored = sum(1 for f in conductors if f["properties"].get("displayColor"))
    supply = sum(1 for f in conductors if f["properties"].get("supplyFeeder"))
    rc = s.recloser_node["PDA10R-01"]
    hop = a._kua_feeder_hop_from_seed(s, "KUA01")
    rc_h = hop.get(rc, -1)
    src_wrong = [n for n in live if hop.get(n, 999) < rc_h and n != rc]
    ok = rest == expect_rest_live
    print(f"\n=== {label} ===")
    print(f"restoration_live={rest} (expect {expect_rest_live}) {'OK' if ok else 'FAIL'}")
    print(f"nodes_on={stats['nodesOn']} on_segs={on_segs} supply_tags={supply} colored={colored}")
    print(f"RC source-side wrongly live: {len(src_wrong)}")
    payload = a._scada_payload(s, [], [])
    print(f"activeSupplyFeeders={payload.get('activeSupplyFeeders')}")


# Reset fault state
s.fault_node = None
s.fault_feeder = None
s.fault_feeders = []
a._invalidate_compute_cache(s)

rc_node, _ = setup_fault()

# A: PDA02 backfeed
s.recloser_status["PDA10R-01"] = 0
s.switch_status["PDA10S-13"] = 0
s.switch_status["PDA02S-08"] = 1
for fid in s.feeder_cbs.get("PDA02", []):
    s.cb_status[fid] = 1
a._invalidate_compute_cache(s)
check("PDA02 backfeed + S-13 open", True)

# B: line-end only
setup_fault()
s.recloser_status["PDA10R-01"] = 0
s.switch_status["PDA10S-13"] = 0
a._invalidate_compute_cache(s)
check("KUA line-end only", True)

print("\nDone.")

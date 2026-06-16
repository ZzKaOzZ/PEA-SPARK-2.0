"""One-shot verification for KUA01 backfeed fixes (reuses single build_state)."""
import app as a

LAT, LON = 11.92459, 99.73421


def prep(s, *, pda02=False, s13=True, rc_trip=True):
    a.apply_startup_cb_closed(s)
    x, y = a.to_utm(LON, LAT)
    cn = a.find_nearest(s, x, y)
    hop = a._kua_feeder_hop_from_seed(s, "KUA01")
    rc = s.recloser_node["PDA10R-01"]
    # fault load-side of RC when possible
    load_cands = [n for n in hop if hop[n] > hop[rc]]
    fault = max(load_cands, key=lambda n: hop[n]) if load_cands else cn
    s.fault_node = fault
    s.fault_feeder = "KUA01"
    s.fault_feeders = ["KUA01"]
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_recloser = dict(s.recloser_status)
    if rc_trip:
        s.recloser_status["PDA10R-01"] = 0
    if s13:
        s.switch_status["PDA10S-13"] = 0
    if pda02:
        s.switch_status["PDA02S-08"] = 1
    a._invalidate_compute_cache(s)
    return cn, rc, hop


def near_coord_stats(conductors):
    pda2 = no_sup = off = 0
    for f in conductors:
        for lo, la in f["geometry"]["coordinates"]:
            if abs(la - LAT) < 0.008 and abs(lo - LON) < 0.008:
                p = f["properties"]
                if p["status"] == "off":
                    off += 1
                elif p.get("supplyFeeder") == "PDA02":
                    pda2 += 1
                elif p["status"] == "on":
                    no_sup += 1
                break
    return pda2, no_sup, off


print("Loading network once…")
S = a.build_state()

# A: PDA02 backfeed + RC trip + S-13 open
cn, rc, hop = prep(S, pda02=True, s13=True)
src = {n for n, h in hop.items() if h <= hop[rc]}
live = a.compute_live_energization(S)
sup = a._compute_node_supply_feeders(S, live)
wrong = sum(1 for n in src if n in live and sup.get(n) == "PDA02")
bf = a._kua_interconnect_backfeed_nodes(S, "KUA01")
co, _, _ = a.build_live_conductors(S)
pda2, no_sup, off = near_coord_stats(co)
pda2n = sum(1 for v in sup.values() if v == "PDA02")
st = a._network_energization_stats(S)
print(f"A PDA02 backfeed: wrong_src_pda2={wrong} live={len(live)} bf={len(bf)} "
      f"pda2_nodes={pda2n} pda2_near={pda2} off_near={off} nodesOn={st['nodesOn']}")

# B: line-end only (S-13 open, no PDA02)
cn, rc, hop = prep(S, pda02=False, s13=True)
live = a.compute_live_energization(S)
st = a._network_energization_stats(S)
co, _, _ = a.build_live_conductors(S)
_, _, off = near_coord_stats(co)
print(f"B line-end only: live={len(live)} nodesOn={st['nodesOn']} "
      f"rest={a._display_restoration_live(S)} off_near={off}")

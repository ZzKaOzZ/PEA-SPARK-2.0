"""Diagnose KUA01 zone1 step 3/4 display: S-13 line-end + PDA02 backfeed colour."""
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import app as a


def prep_zone1(s):
    a.apply_startup_cb_closed(s)
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
    return hop


def segs_near(s, center_node, radius_m=1500.0):
    if center_node not in s.node_xy:
        return []
    cx, cy = s.node_xy[center_node]
    out = []
    for i, (cw, keys) in enumerate(zip(s.conductor_wgs, s.conductor_keys)):
        for k in keys:
            if k not in s.node_xy:
                continue
            x, y = s.node_xy[k]
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius_m ** 2:
                out.append((i, cw, keys))
                break
    return out


def report(label, s, hop):
    a._invalidate_compute_cache(s)
    s13 = s.switch_node["PDA10S-13"]
    s08 = s.switch_node["PDA10S-08"]
    r01 = s.recloser_node["PDA10R-01"]
    s13h = hop[s13]
    s08h = hop[s08]
    r01h = hop[r01]
    live = a.compute_live_energization(s)
    disp = a.compute_display_energization(s)
    co, _, _ = a.build_live_conductors(s)
    supply_map = a._compute_node_supply_feeders(s, live)

    print(f"\n=== {label} ===")
    print(
        "rest", a._display_restoration_live(s),
        "ack", s.kua_line_end_display_ack,
        "PDA02", s.switch_status.get("PDA02S-08"),
        "live", len(live), "disp", len(disp),
    )
    print(
        f"hops S13={s13h} S08={s08h} R01={r01h} | "
        f"S13 live={s13 in live} S08 live={s08 in live} R01 live={r01 in live}"
    )
    print("S13 supply", supply_map.get(s13), "S08 supply", supply_map.get(s08))

    near_s13 = segs_near(s, s13, 2000.0)
    on = off = sup_kua = sup_pda02 = 0
    for i, _cw, _keys in near_s13:
        p = co[i]["properties"]
        if p["status"] == "on":
            on += 1
            sf = p.get("supplyFeeder")
            if sf == "KUA01":
                sup_kua += 1
            elif sf == "PDA02":
                sup_pda02 += 1
        else:
            off += 1
    print(f"near S-13 segs: on={on} off={off} supply KUA01={sup_kua} PDA02={sup_pda02}")

    near_r01 = segs_near(s, r01, 2500.0)
    on2 = off2 = sup_pda02_r = sup_kua_r = sub_on = 0
    r01h = hop[r01]
    for i, cw, keys in near_r01:
        p = co[i]["properties"]
        keys_h = [hop.get(k) for k in keys if k in hop]
        past_r01 = keys_h and max(keys_h) < r01h
        if p["status"] == "on":
            on2 += 1
            if past_r01:
                sub_on += 1
            sf = p.get("supplyFeeder")
            if sf == "PDA02":
                sup_pda02_r += 1
            elif sf == "KUA01":
                sup_kua_r += 1
        else:
            off2 += 1
    print(f"near R-01 segs: on={on2} off={off2} past_R01_on={sub_on} supply PDA02={sup_pda02_r} KUA01={sup_kua_r}")

    bf = a._kua_interconnect_backfeed_nodes(s, "KUA01")
    print("backfeed nodes", len(bf), "R01 in backfeed", r01 in bf)
    if bf:
        pda02_in_bf = sum(1 for n in bf if supply_map.get(n) == "PDA02")
        print("backfeed nodes with PDA02 supply", pda02_in_bf)

    # Step 3 expectations (line-end only, PDA02S-08 still open)
    if s.kua_line_end_display_ack and s.switch_status.get("PDA02S-08", 1) == 0:
        assert s08 not in live, "S-08 must be dark (substation-ward of open S-13)"
        assert r01 not in live, "open R-01 node must not be live"
        assert sup_pda02 == 0, f"PDA02 supply near S-13 must be 0, got {sup_pda02}"
        assert s13 in live, "S-13 must be live from line end"
        assert supply_map.get(s13) == "KUA01", f"S-13 supply must be KUA01, got {supply_map.get(s13)}"
        assert sub_on == 0, f"segments past open R-01 must be dark, got {sub_on}"
        print("ASSERT step3 OK")


def main() -> None:
    s = a.build_state()
    hop = prep_zone1(s)

    report("after step 2 (before NOTE)", s, hop)

    s.kua_line_end_display_ack = True
    report("after step 3 NOTE ack", s, hop)

    s.switch_status["PDA02S-08"] = 1
    report("after step 4 PDA02S-08 close", s, hop)


if __name__ == "__main__":
    main()

"""R62: main-line outage polygon after tie + RC isolation (KUA01 zone1)."""
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import app as a


def main() -> None:
    s = a.build_state()
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
    a._invalidate_compute_cache(s)

    s13 = s.switch_node["PDA10S-13"]
    r01 = s.recloser_node["PDA10R-01"]
    s13h, r01h = hop[s13], hop[r01]
    h_lo, h_hi = min(s13h, r01h), max(s13h, r01h)

    base = a.compute_fault_affected_nodes(s)
    aff = a._display_affected_nodes(s)
    polys = a.get_outage_polygons_cached(s)
    co, _, _ = a.build_live_conductors(s)

    main_off = main_on = 0
    for feat in co:
        if feat["properties"]["feeder"] != "KUA01":
            continue
        keys = None
        for cw, k in zip(s.conductor_wgs, s.conductor_keys):
            if cw["geometry"] == feat["geometry"]:
                keys = k
                break
        if not keys:
            continue
        keys_h = [hop.get(k) for k in keys if k in hop]
        if not keys_h:
            continue
        if max(keys_h) < h_lo or min(keys_h) > h_hi:
            continue
        if feat["properties"]["status"] == "off":
            main_off += 1
        else:
            main_on += 1

    print(
        f"step2 isolation: base={len(base)} aff={len(aff)} polys={len(polys)} "
        f"main_band off={main_off} on={main_on}"
    )
    print(
        f"S13 in base/aff {s13 in base}/{s13 in aff} "
        f"R01 in base/aff {r01 in base}/{r01 in aff}"
    )
    assert s13 in base, "S-13 corridor must be in fault zone"
    assert main_off > 0, "main-line segments must be OFF (polygon source)"
    assert len(polys) > 0, "outage polygons must be visible"

    s.kua_line_end_display_ack = True
    a._invalidate_compute_cache(s)
    aff3 = a._display_affected_nodes(s)
    polys3 = a.get_outage_polygons_cached(s)
    s08 = s.switch_node["PDA10S-08"]
    live3 = a.compute_live_energization(s)
    print(
        f"step3 ack: aff={len(aff3)} polys={len(polys3)} "
        f"S08 aff/live={s08 in aff3}/{s08 in live3} "
        f"S13 aff/live={s13 in aff3}/{s13 in live3}"
    )
    assert s08 in aff3, "PDA-ward blocked main must stay in display"
    assert s13 in live3, "S-13 is fed from line end after ack"
    assert s13 not in aff3, "S-13 must not stay dark once line-end feeds"
    assert r01 in aff3, "open RC section must stay in outage display"
    print("OK R62 isolation polygon")

    s.switch_status["PDA02S-08"] = 1
    a._invalidate_compute_cache(s)
    aff4 = a._display_affected_nodes(s)
    polys4 = a.get_outage_polygons_cached(s)
    co4, _, _ = a.build_live_conductors(s)
    live4 = a.compute_live_energization(s)
    r01h = hop[r01]
    h13 = hop[s13]
    off_band = sum(
        1 for f in co4
        if f["properties"]["feeder"] == "KUA01"
        and f["properties"]["status"] == "off"
        and any(
            r01h <= hop.get(k, -1) <= h13
            for cw, keys in zip(s.conductor_wgs, s.conductor_keys)
            if cw["geometry"] == f["geometry"]
            for k in keys
            if k in hop
        )
    )
    print(
        f"step4 PDA02 close: aff={len(aff4)} polys={len(polys4)} "
        f"off_R01-S13={off_band} R01 live={r01 in live4} S08 live={s08 in live4}"
    )
    assert len(polys4) > 5, f"outage polygons must remain after step 4, got {len(polys4)}"
    assert off_band > 10, f"main-line R01-S13 must stay OFF, got {off_band}"
    assert r01 not in live4, "R-01 must stay dark — supply stops at open RC"
    assert s08 not in live4, "S-08 must stay dark until past R-01"
    past = {n for n, h in hop.items() if h > h13}
    assert len(past & live4) > 500, "line-end past S-13 must be live after step 4"
    off_past = sum(
        1 for f in co4
        if f["properties"]["feeder"] == "KUA01"
        and f["properties"]["status"] == "off"
        and all(hop.get(k, -1) > h13 for cw, keys in zip(s.conductor_wgs, s.conductor_keys)
                if cw["geometry"] == f["geometry"] for k in keys if k in hop)
    )
    assert off_past == 0, f"no OFF segments past S-13 after step 4, got {off_past}"
    print("OK R63 step4 polygon")


if __name__ == "__main__":
    main()

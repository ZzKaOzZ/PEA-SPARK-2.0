"""Check polygon/conductor bleed past PDA10S-13 after step 4."""
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import app as a


def prep_step4(s):
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
    s.kua_line_end_display_ack = True
    s.switch_status["PDA02S-08"] = 1
    a._invalidate_compute_cache(s)
    return hop, h13


def main() -> None:
    s = a.build_state()
    hop, h13 = prep_step4(s)
    past = {n for n, h in hop.items() if h > h13}
    live = a.compute_live_energization(s)
    aff = a._display_affected_nodes(s)
    co, _, _ = a.build_live_conductors(s)
    polys = a.get_outage_polygons_cached(s)

    off_past = on_past = span = 0
    for feat in co:
        if feat["properties"]["feeder"] != "KUA01":
            continue
        keys = next(
            k for cw, k in zip(s.conductor_wgs, s.conductor_keys)
            if cw["geometry"] == feat["geometry"]
        )
        kh = [hop.get(k) for k in keys if k in hop]
        if not kh or min(kh) <= h13:
            continue
        st = feat["properties"]["status"]
        if st == "off":
            off_past += 1
        else:
            on_past += 1
        if any(k in aff for k in keys):
            span += 1

    print(
        f"past S13 nodes: total={len(past)} in_live={len(past & live)} "
        f"in_aff={len(past & aff)}"
    )
    print(
        f"segs wholly past S13: off={off_past} on={on_past} "
        f"touch_aff={span} polys={len(polys)}"
    )
    assert len(past & live) > 1000, "line-end past S-13 must be live"
    assert off_past == 0, f"no OFF segments past S-13, got {off_past}"
    assert len(past & aff) == 0, f"no affected nodes past S-13, got {len(past & aff)}"
    print("OK past S-13")


if __name__ == "__main__":
    main()

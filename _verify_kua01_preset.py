"""Verify KUA01 preset switching plans for zones 1–3."""
import app as a


def run_zone(s, zone: int, target_hop: int) -> None:
    hop = a._kua_feeder_hop_from_seed(s, "KUA01")
    cands = [(n, h) for n, h in hop.items() if abs(h - target_hop) <= 2]
    cands.sort(key=lambda x: abs(x[1] - target_hop))
    node, node_hop = cands[0]
    x, y = s.node_xy[node]
    lon, lat = a.to_wgs(x, y)
    s.fault_node = node
    s.fault_feeder = "KUA01"
    s.fault_feeders = ["KUA01"]
    s.fault_lat = lat
    s.fault_lon = lon
    s.fault_cause = "line_break"
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_recloser = dict(s.recloser_status)
    a._invalidate_compute_cache(s)
    seg = a._kua01_mainline_segment(s)
    plan = a.generate_switching_plan(s)
    print(f"=== zone {zone} hop={node_hop} seg={seg} preset={plan.get('kua01PresetSegment')} ===")
    for st in plan.get("steps", []):
        print(st["step"], st["action"], st.get("switchId"), st["reason"][:95])


def main() -> None:
    s = a.build_state()
    a.apply_startup_cb_closed(s)
    hops = {
        "PDA10S-08": a._kua01_device_hop(s, "PDA10S-08"),
        "PDA10S-13": a._kua01_device_hop(s, "PDA10S-13"),
        "PDA10S-14": a._kua01_device_hop(s, "PDA10S-14"),
        "KUA01R-04": a._kua01_device_hop(s, "KUA01R-04"),
    }
    print("boundary hops:", hops)
    pairs = [
        (1, hops["PDA10S-08"], hops["PDA10S-13"]),
        (2, hops["PDA10S-13"], hops["PDA10S-14"]),
        (3, hops["PDA10S-14"], hops["KUA01R-04"]),
    ]
    for zone, lo, hi in pairs:
        run_zone(s, zone, (lo + hi) // 2)


if __name__ == "__main__":
    main()

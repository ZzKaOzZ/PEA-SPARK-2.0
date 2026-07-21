"""Verify KUA01 plan execute display gating (R53)."""
import app as a


def prep_zone1(s):
    hop = a._kua_feeder_hop_from_seed(s, "KUA01")
    h08 = a._kua01_device_hop(s, "PDA10S-08")
    h13 = a._kua01_device_hop(s, "PDA10S-13")
    target = (h08 + h13) // 2
    node = min(
        (n for n, h in hop.items() if abs(h - target) <= 2),
        key=lambda n: abs(hop[n] - target),
    )
    s.fault_node = node
    s.fault_feeder = "KUA01"
    s.fault_feeders = ["KUA01"]
    s.fault_lat, s.fault_lon = 11.9, 99.7
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_recloser = dict(s.recloser_status)
    a._invalidate_compute_cache(s)
    plan = a.generate_switching_plan(s)
    return plan


def main() -> None:
    s = a.build_state()
    a.apply_startup_cb_closed(s)
    plan = prep_zone1(s)
    assert plan.get("kua01PresetSegment") == 1
    steps = plan["steps"]
    assert steps[2].get("planEffect") == "kuaLineEndAck"

    def show(label):
        a._invalidate_compute_cache(s)
        print(
            f"{label}: restoration={a._display_restoration_live(s)} "
            f"ack={s.kua_line_end_display_ack} "
            f"PDA02={s.switch_status.get('PDA02S-08')} "
            f"S13={s.switch_status.get('PDA10S-13')} "
            f"RC={s.recloser_status.get('PDA10R-01')}"
        )

    show("fault")
    s.recloser_status["PDA10R-01"] = 0
    show("step1 RC open")
    s.switch_status["PDA10S-13"] = 0
    show("step2 S13 open (before NOTE)")
    assert not a._display_restoration_live(s)

    s.kua_line_end_display_ack = True
    show("step3 NOTE ack")
    assert a._display_restoration_live(s)

    s.switch_status["PDA02S-08"] = 1
    show("step4 PDA02 tie close")
    assert a._display_restoration_live(s)
    bf = a._kua_interconnect_backfeed_nodes(s, "KUA01")
    assert len(bf) > 0, "expected PDA02 backfeed nodes"
    print("PDA02 backfeed nodes:", len(bf))
    print("OK")


if __name__ == "__main__":
    main()

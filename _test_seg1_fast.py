"""Segment-1 steps: live energization after NOTE ack + PDA02 tie close."""
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import app as a


def main() -> None:
    s = a.build_state()
    a.apply_startup_cb_closed(s)
    hop = a._kua_feeder_hop_from_seed(s, "KUA01")
    h08, h13 = a._kua01_device_hop(s, "PDA10S-08"), a._kua01_device_hop(s, "PDA10S-13")
    node = min(
        (n for n, h in hop.items() if abs(h - (h08 + h13) // 2) <= 2),
        key=lambda n: abs(hop[n] - (h08 + h13) // 2),
    )
    s.fault_node = node
    s.fault_feeder = "KUA01"
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_recloser = dict(s.recloser_status)

    s.recloser_status["PDA10R-01"] = 0
    s.switch_status["PDA10S-13"] = 0
    a._invalidate_compute_cache(s)
    assert not a._display_restoration_live(s), "before NOTE ack"

    s.kua_line_end_display_ack = True
    a._invalidate_compute_cache(s)
    live3 = a.compute_live_energization(s)
    assert a._display_restoration_live(s), "after NOTE ack"
    assert len(live3) > 5000, f"expected line-end live nodes, got {len(live3)}"

    s.switch_status["PDA02S-08"] = 1
    a._invalidate_compute_cache(s)
    assert s.switch_status["PDA02S-08"] == 1
    bf = a._kua_interconnect_backfeed_nodes(s, "KUA01")
    assert len(bf) > 0, "PDA02 backfeed expected"
    assert a._display_restoration_live(s)
    print("OK", f"live_after_ack={len(live3)} backfeed={len(bf)}")


if __name__ == "__main__":
    main()

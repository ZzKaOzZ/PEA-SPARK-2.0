"""Verify KUA01 line-end display through closed KUA01R-04 with open KUA01S-15 bypass."""
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import app as a


def prep_zone2_fault(s):
    hop = a._kua_feeder_hop_from_seed(s, "KUA01")
    h13 = a._kua01_device_hop(s, "PDA10S-13")
    h14 = a._kua01_device_hop(s, "PDA10S-14")
    target = (h13 + h14) // 2
    node = min(
        (n for n, h in hop.items() if abs(h - target) <= 2),
        key=lambda n: abs(hop[n] - target),
    )
    s.fault_node = node
    s.fault_feeder = "KUA01"
    s.fault_feeders = ["KUA01"]
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_recloser = dict(s.recloser_status)
    a._invalidate_compute_cache(s)
    return node


def main() -> None:
    s = a.build_state()
    a.apply_startup_cb_closed(s)
    assert "KUA01S-15" in s.rc_bypass_switch_ids
    assert s.switch_status.get("KUA01S-15") == 0
    assert s.recloser_status.get("KUA01R-04") == 1

    prep_zone2_fault(s)
    r04 = s.recloser_node["KUA01R-04"]
    s14 = s.switch_node["PDA10S-14"]
    s15 = s.switch_node["KUA01S-15"]

    # Segment 2 restoration: S-13/S-14 open, line-end ack, R-04 still closed.
    s.switch_status["PDA10S-13"] = 0
    s.switch_status["PDA10S-14"] = 0
    s.kua_line_end_display_ack = True
    a._invalidate_compute_cache(s)

    line_on = a._kua_feeder_energization_ex(s, "KUA01", line_end_restore=True)
    live = a.compute_live_energization(s)
    assert r04 in line_on, "closed R-04 must stay on line-end path (open S-15 bypass must not block)"
    assert s14 in line_on
    assert s15 in line_on, "bypass node should be traversable when RC is closed"
    assert r04 in live
    assert a._display_restoration_live(s)
    print("OK — KUA01 line-end reaches R-04 with open bypass S-15")


if __name__ == "__main__":
    main()

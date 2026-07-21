"""HTTP integration test: switching-plan execute steps 1-3."""
import json

import app as a

LAT, LON = 11.92459, 99.73421


def prep_state(s):
    a.apply_startup_cb_closed(s)
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
    s.fault_lat = LAT
    s.fault_lon = LON
    s.fault_cause = "line_break"
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_recloser = dict(s.recloser_status)
    a._invalidate_compute_cache(s)


def conductor_stats(s):
    a._invalidate_compute_cache(s)
    co, _, _ = a.build_live_conductors(s)
    on = sum(1 for c in co if c["properties"]["status"] == "on")
    off = sum(1 for c in co if c["properties"]["status"] == "off")
    colored = sum(1 for c in co if c["properties"].get("supplyFeeder"))
    return on, off, colored


def main() -> None:
    s = a.build_state()
    prep_state(s)
    a._STATE = s
    client = a.app.test_client()

    plan = client.post("/switching-plan").get_json()
    assert not plan.get("error"), plan.get("error")
    steps = plan["steps"]
    print("plan steps", len(steps), "step3 effect", steps[2].get("planEffect"))

    def exec_step(i: int):
        st = steps[i]
        r = client.post(
            f"/switching-plan/execute/{i + 1}",
            data=json.dumps({
                "action": st["action"],
                "switchId": st.get("switchId"),
                "planEffect": st.get("planEffect"),
            }),
            content_type="application/json",
        )
        body = r.get_json()
        print(
            f"exec {i + 1} {st['action']} {st.get('switchId')} "
            f"-> ack={body.get('kuaLineEndAck')} phys={body.get('lineDisplayPhysical')}"
        )
        return body

    print("before", conductor_stats(s))
    exec_step(0)
    print("after 1", conductor_stats(s), "rest", a._display_restoration_live(s))
    exec_step(1)
    print("after 2", conductor_stats(s), "rest", a._display_restoration_live(s))
    exec_step(2)
    print("after 3", conductor_stats(s), "rest", a._display_restoration_live(s))

    bundle = client.get("/live-refresh").get_json()
    sc = bundle["scada"]
    print("live-refresh scada", sc.get("lineDisplayPhysical"), sc.get("appBuild"))
    co = bundle["conductors"]["features"]
    on = sum(1 for c in co if c["properties"]["status"] == "on")
    off = sum(1 for c in co if c["properties"]["status"] == "off")
    print("live-refresh conductors on/off", on, off)


if __name__ == "__main__":
    main()

"""HTTP test KUA01 zone1 steps 1-4 — step 3 display + step 4 PDA02S-08."""
import json

import app as a


def prep(s):
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
    s.fault_lat, s.fault_lon = 11.92459, 99.73421
    a._take_snapshot(s)
    a._invalidate_compute_cache(s)


def stats(label: str, s) -> None:
    a._invalidate_compute_cache(s)
    co, _, _ = a.build_live_conductors(s)
    on = sum(1 for x in co if x["properties"]["status"] == "on")
    off = sum(1 for x in co if x["properties"]["status"] == "off")
    sup = sum(1 for x in co if x["properties"].get("supplyFeeder"))
    print(
        f"{label}: on={on} off={off} supply={sup} "
        f"rest={a._display_restoration_live(s)} ack={s.kua_line_end_display_ack} "
        f"PDA02={s.switch_status.get('PDA02S-08')} S13={s.switch_status.get('PDA10S-13')} "
        f"RC={s.recloser_status.get('PDA10R-01')}"
    )


def main() -> None:
    s = a.build_state()
    prep(s)
    a._STATE = s
    client = a.app.test_client()

    plan = client.post("/switching-plan").get_json()
    steps = plan["steps"]
    print("plan steps", len(steps), "step3", steps[2].get("planEffect"))
    stats("fault", s)

    for i, st in enumerate(steps[:4]):
        body = client.post(
            f"/switching-plan/execute/{i + 1}",
            data=json.dumps({
                "action": st["action"],
                "switchId": st.get("switchId"),
                "planEffect": st.get("planEffect"),
                "instructionTh": st.get("instructionTh") or st.get("reason"),
            }),
            content_type="application/json",
        ).get_json()
        print(
            f"exec {i + 1} {st['action']} {st.get('switchId')} ->",
            {k: body.get(k) for k in (
                "kuaLineEndAck", "lineDisplayPhysical", "newStatus", "state", "switchId",
            ) if k in body},
        )
        stats(f"after {i + 1}", s)
        bundle = client.get("/live-refresh").get_json()
        co = bundle["conductors"]["features"]
        sw = {
            f["properties"]["id"]: f["properties"]["state"]
            for f in bundle["switches"]["features"]
        }
        on = sum(1 for x in co if x["properties"]["status"] == "on")
        pda02 = sw.get("PDA02S-08")
        print(
            f"  live-refresh on={on} phys={bundle['scada']['lineDisplayPhysical']} "
            f"PDA02S-08={pda02} S13={sw.get('PDA10S-13')}"
        )
        if i == 2:
            assert body.get("kuaLineEndAck"), "step 3 should set ack"
            assert on > 6000, f"step 3 should light conductors, got on={on}"
        if i == 3:
            assert s.switch_status.get("PDA02S-08") == 1, "PDA02S-08 should be CLOSE"
            assert pda02 == "CLOSE", f"live-refresh PDA02S-08 should be CLOSE, got {pda02}"
    print("OK")


if __name__ == "__main__":
    main()

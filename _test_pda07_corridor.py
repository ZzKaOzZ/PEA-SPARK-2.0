"""Verify R76: S15→S12 restored corridor has PDA05 tint and no outage-poly bleed."""
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import app as a


def main() -> None:
    s = a.build_state()
    a.apply_startup_cb_closed(s)
    hop = a._feeder_protection_hop_map(s, "PDA07")
    rc = s.recloser_node["PDA07R-01"]
    rh = hop[rc]
    island = a._rc_load_side_island(s, "PDA07R-01", "PDA07")
    s12 = s.switch_node["PDA07S-12"]
    h12 = hop[s12]
    fault = min(
        (n for n in island if rh < hop.get(n, -1) <= h12),
        key=lambda n: abs(hop[n] - (rh + h12) / 2),
    )
    s.fault_node = fault
    s.fault_feeder = "PDA07"
    s.fault_feeders = ["PDA07"]
    if fault in s.node_xy:
        x, y = s.node_xy[fault]
        lon, lat = a.to_wgs(x, y)
        s.fault_lat, s.fault_lon = lat, lon
    s.snapshot_switch = dict(s.switch_status)
    s.snapshot_recloser = dict(s.recloser_status)
    s.recloser_status["PDA07R-01"] = 0
    s.switch_status["PDA07S-12"] = 0
    s.switch_status["PDA05S-15"] = 1
    a._invalidate_compute_cache(s)

    bundle = a._build_live_map_bundle(s)
    zone = a._pda_interconnect_backfeed_nodes(s)

    # Highway segs that must be ON / PDA05
    must_on = (240, 241, 242, 244, 245, 2147)
    for idx in must_on:
        p = bundle["conductors"][idx]["properties"]
        assert p["status"] == "on", f"{idx} status={p['status']}"
        assert p.get("supplyFeeder") == "PDA05", f"{idx} sf={p.get('supplyFeeder')}"

    # Bleed OFF segs must not create outage polys in the S15–S12 view box
    bleed = (852, 853, 2148, 4222)
    view_polys = 0
    for f in bundle["outage_polys"]:
        ring = f["geometry"]["coordinates"][0]
        xs, ys = [], []
        for lon, lat in ring[:-1]:
            x, y = a.to_utm(lon, lat)
            xs.append(x)
            ys.append(y)
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        if 585900 <= cx <= 586200 and 1299050 <= cy <= 1299450:
            view_polys += 1

    assert view_polys == 0, f"outage poly bleed still in view box: {view_polys}"

    # Those OFF segs are near restored zone — poly skip path must fire
    for idx in bleed:
        keys = s.conductor_keys[idx]
        assert a._segment_near_nodes(s, keys, zone, snap_m=160.0), (
            f"expected bleed seg {idx} near restored zone"
        )

    # Closed tie PDA05S-15 itself must stay PDA05-tinted / not under a poly disc
    s15 = s.switch_node["PDA05S-15"]
    assert s15 in zone
    near_s15_poly = 0
    sx, sy = s.node_xy[s15]
    for f in bundle["outage_polys"]:
        ring = f["geometry"]["coordinates"][0]
        xs, ys = [], []
        for lon, lat in ring[:-1]:
            x, y = a.to_utm(lon, lat)
            xs.append(x)
            ys.append(y)
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        if ((cx - sx) ** 2 + (cy - sy) ** 2) ** 0.5 < 120:
            near_s15_poly += 1
    assert near_s15_poly == 0, f"outage poly still near PDA05S-15: {near_s15_poly}"

    print(
        f"OK highway_on={len(must_on)} view_box_polys={view_polys} "
        f"s15_near_polys={near_s15_poly} total_polys={len(bundle['outage_polys'])} "
        f"zone={len(zone)}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)

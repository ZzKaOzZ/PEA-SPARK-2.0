"""Fast check: S-13 + R-01 in live energization after step 3/4."""
import os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
import app as a

s = a.build_state()
a.apply_startup_cb_closed(s)
hop = a._kua_feeder_hop_from_seed(s, "KUA01")
h08, h13 = a._kua01_device_hop(s, "PDA10S-08"), a._kua01_device_hop(s, "PDA10S-13")
node = min((n for n, h in hop.items() if abs(h - (h08 + h13) // 2) <= 2),
           key=lambda n: abs(hop[n] - (h08 + h13) // 2))
s.fault_node = node
s.fault_feeder = "KUA01"
s.snapshot_switch = dict(s.switch_status)
s.snapshot_recloser = dict(s.recloser_status)
s.recloser_status["PDA10R-01"] = 0
s.switch_status["PDA10S-13"] = 0

s13, r01 = s.switch_node["PDA10S-13"], s.recloser_node["PDA10R-01"]
s13h, r01h = hop[s13], hop[r01]

def show(label):
    a._invalidate_compute_cache(s)
    live = a.compute_live_energization(s)
    load_past_s13 = {n for n, h in hop.items() if h < s13h}
    past_r01_sub = {n for n, h in hop.items() if h > r01h}
    print(label,
          "live", len(live),
          "S13", s13 in live,
          "load<h S13 in live", len(load_past_s13 & live),
          "R01", r01 in live,
          "hop>R01 in live", len(past_r01_sub & live),
          "rest", a._display_restoration_live(s))

show("step2")
s.kua_line_end_display_ack = True
show("step3")
s.switch_status["PDA02S-08"] = 1
past_r01_sub = {n for n, h in hop.items() if h > r01h}
show("step4")
bf = a._kua_interconnect_backfeed_nodes(s, "KUA01")
live = a.compute_live_energization(s)
print("backfeed", len(bf), "past R01 in bf", len(past_r01_sub & bf))
sm = a._compute_node_supply_feeders(s, live)
print("PDA02 supply nodes", sum(1 for v in sm.values() if v == "PDA02"))
print("past R01 PDA02 supply", sum(1 for n in past_r01_sub if sm.get(n) == "PDA02"))

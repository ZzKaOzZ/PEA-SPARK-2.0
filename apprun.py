"""
PEA SPARK · RUN MODE (optional — not the primary app)
=====================================================
Canonical stack: ``python app.py`` + ``templates/indexpro.html``.

This file only swaps the home template to ``indexrun.html`` for legacy
demos. Prefer ``app.py`` for normal operation.

Run
---
    cd pea-spark
    PORT=8001 python3 apprun.py
"""
from __future__ import annotations

import os
import sys

# Re-use the real app — every route, model and helper.
import app as base  # noqa: E402


def force_all_cbs_closed(s: "base.NetworkState") -> int:
    """Flip every CB (real + virtual) to CLOSE / status=1 and keep the
    `substations` GeoJSON in lock-step so the marker popups also show
    the new state. Returns how many CBs were flipped."""
    flipped = 0
    for fid in list(s.cb_status.keys()):
        if s.cb_status[fid] != 1:
            s.cb_status[fid] = 1
            flipped += 1
    for feat in s.substations:
        p = feat["properties"]
        if p.get("status") != 1:
            p["status"] = 1
            p["state"] = "CLOSE"
    # The snapshot is what `/restore` reverts to. In RUN MODE we want
    # "restore" to bring the operator back to the all-closed baseline,
    # not to the original PRESENTPOS state.
    s.snapshot_cb     = dict(s.cb_status)
    s.snapshot_switch = dict(s.switch_status)
    return flipped


# ---------------------------------------------------------------------------
# Patch `get_state` so the very first build flips every CB closed exactly
# once. Subsequent calls just return the cached, already-patched state.
# ---------------------------------------------------------------------------
_original_get_state = base.get_state
_run_mode_applied   = {"done": False}


def get_state_run_mode() -> "base.NetworkState":
    s = _original_get_state()
    if not _run_mode_applied["done"]:
        n = force_all_cbs_closed(s)
        print(f"  [RUN MODE] forced {n} CB(s) → CLOSE  "
              f"(total CBs: {len(s.cb_status)})", flush=True)
        _run_mode_applied["done"] = True
    return s


base.get_state = get_state_run_mode  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Override the index route to render the RUN-MODE template (banner + same
# UI). Everything else (/substations, /switches, /scada, /fault, etc.)
# stays exactly as defined in app.py.
# ---------------------------------------------------------------------------
from flask import render_template, session, redirect  # noqa: E402

app = base.app  # expose for gunicorn / WSGI runners


def index_run():
    if not session.get("logged_in"):
        return redirect("/login")
    return render_template("indexrun.html")


# Replace the production "/" view with the RUN-MODE one. Keep the same
# endpoint name ("index") so `url_for('index')` from other handlers and
# templates keeps working — only the handler body changes.
app.view_functions["index"] = index_run


if __name__ == "__main__":
    base.init_db()
    # Warm the cache so the "[RUN MODE] forced N CB(s)" line appears
    # before the server starts accepting traffic.
    get_state_run_mode()

    port = int(os.environ.get("PORT", "5001"))
    print(f"\n  PEA SPARK [RUN MODE] listening on 0.0.0.0:{port}", flush=True)
    print( "  (all CBs forced CLOSED; toggle in the UI to open them)\n",
          flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

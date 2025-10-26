# main.py
import os
import json
import time
import threading
from collections import deque
from typing import Deque, Dict, Any

import requests
from flask import Flask, render_template, jsonify, request

# ---------------- CONFIG ----------------
CAM_DISPLAY_URL = "http://192.168.1.5:8000/"           # shown in iframe (your camera page)
ESP_SENSOR_URL  = "http://192.168.1.50/sensor"         # <-- replace with your ESP JSON endpoint
POLL_INTERVAL_S = 1.0
STALE_AFTER_S   = 3.0

# Google Maps (pass to template so <script ... key={{ gmap_key }}> works)
GMAP_KEY = os.environ.get("GMAP_KEY", "AIzaSyA9XxbALHU15k1DwM_bbD5sowkwJvV5Elk")

# Bot control
BOT_BASE = "http://10.238.124.20"                      # your ESP UI / controller IP
CONTROL_PATHS = {
    "F": "/forward",
    "B": "/backward",
    "L": "/left",
    "R": "/right",
    "S": "/stop",
    "SLOW": "/speed?val=80",
    "FAST": "/speed?val=180",
}

# Data persistence
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(DATA_DIR, "sensor_history.json")
HISTORY_MAX = 5000
# ----------------------------------------

app = Flask(__name__)

# ------------- In-memory store -------------
_latest_lock = threading.Lock()
_latest: Dict[str, Any] = {}
_history: Deque[Dict[str, Any]] = deque(maxlen=HISTORY_MAX)


def _load_history():
    if os.path.isfile(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                arr = json.load(f)
            if isinstance(arr, list):
                for item in arr[-HISTORY_MAX:]:
                    _history.append(item)
                if arr:
                    with _latest_lock:
                        _latest.clear()
                        _latest.update(arr[-1])
        except Exception as e:
            print("History load error:", e)


def _save_history():
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(list(_history), f, ensure_ascii=False)
    except Exception as e:
        print("History save error:", e)


def _now_ts() -> float:
    return time.time()


def _poll_loop():
    """Poll ESP for JSON sensor data, keep latest + history, persist to file."""
    while True:
        try:
            r = requests.get(ESP_SENSOR_URL, timeout=2)
            if r.ok:
                d = r.json()
                # Normalize keys you mentioned
                rec = {
                    "timestamp": _now_ts(),
                    "temp":      d.get("temp"),
                    "gas":       d.get("gas"),
                    "pressure":  d.get("pressure"),
                    "vibration": d.get("vibration"),
                    "latitude":  d.get("latitude"),
                    "longitude": d.get("longitude"),
                    "battery":   d.get("battery"),
                    "mode":      d.get("mode"),
                    # optional extras if provided by ESP
                    "rssi":      d.get("rssi"),
                    "quality":   d.get("quality"),
                    "survivors": d.get("survivors") or d.get("people"),
                }
                with _latest_lock:
                    _latest.clear()
                    _latest.update(rec)
                _history.append(rec)
                _save_history()
            # if not ok, keep previous latest; frontend will see stale flag
        except Exception as e:
            # network hiccup; keep last, let frontend use fallback/history
            # print("Poll error:", e)
            pass
        time.sleep(POLL_INTERVAL_S)


def start_polling():
    _load_history()
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()


def get_latest() -> Dict[str, Any]:
    with _latest_lock:
        data = dict(_latest)
    if not data:
        return {"error": "no_data", "stale": True}
    # mark stale if too old
    data["stale"] = (_now_ts() - float(data.get("timestamp", 0))) > STALE_AFTER_S
    return data


def get_history(limit: int = 200):
    limit = max(1, min(limit, HISTORY_MAX))
    return list(_history)[-limit:]


# ----------------- Routes -----------------
@app.route("/")
def index():
    return render_template(
        "dashboard.html",
        cam_url=CAM_DISPLAY_URL,
        gmap_key=GMAP_KEY
    )


@app.route("/sensor_data")
def sensor_data():
    return jsonify(get_latest())


@app.route("/sensor_history")
def sensor_history():
    n = int(request.args.get("n", 200))
    return jsonify(get_history(n))


@app.route("/network")
def network():
    # Prefer network from latest sensor if present; else synthesize realistic
    data = get_latest()
    rssi = data.get("rssi")
    qual = data.get("quality")
    if rssi is None or qual is None:
        import random
        rssi = rssi if rssi is not None else random.randint(-80, -55)
        qual = qual if qual is not None else max(0, min(100, 2 * (rssi + 90)))  # crude map
    return jsonify({"rssi": rssi, "quality": qual})


@app.route("/control", methods=["POST"])
def control():
    try:
        body = request.get_json(force=True, silent=True) or {}
        cmd = body.get("cmd")
        if cmd not in CONTROL_PATHS:
            return jsonify({"ok": False, "error": "unknown_command"}), 400
        path = CONTROL_PATHS[cmd]
        url = f"{BOT_BASE}{path}"
        resp = requests.get(url, timeout=2)
        if resp.ok:
            return jsonify({"ok": True})
        else:
            return jsonify({"ok": False, "status": resp.status_code}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# -------------- App start --------------
if __name__ == "__main__":
    print("🚀 Starting ESP polling & dashboard ...")
    start_polling()
    app.run(host="0.0.0.0", port=5000, debug=True)

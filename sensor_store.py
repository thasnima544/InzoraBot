# modules/sensor_store.py
import json, time, threading, requests, os
from typing import Dict, Any, List

# ---------- CONFIG ----------
# Replace with your ESP JSON endpoint (e.g., http://<esp-ip>/sensors)
ESP_SENSOR_URL = os.environ.get("ESP_SENSOR_URL", "http://192.168.1.60/sensors")
POLL_SECONDS = 1.0

# Project-relative data dir
ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
CURRENT_PATH = os.path.join(DATA_DIR, "current.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.jsonl")

_lock = threading.Lock()
_running = False
_last_ok_ts = 0.0

def _ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CURRENT_PATH):
        with open(CURRENT_PATH, "w", encoding="utf-8") as f:
            json.dump({"status":"init"}, f)
    if not os.path.exists(HISTORY_PATH):
        open(HISTORY_PATH, "a", encoding="utf-8").close()

def _fetch_from_esp() -> Dict[str, Any]:
    r = requests.get(ESP_SENSOR_URL, timeout=2)
    r.raise_for_status()
    data = r.json()
    # Encourage a standard schema. ESP should return these if available:
    # temp, gas, pressure, vibration,
    # ax, ay, az, gx, gy, gz, latitude, longitude, battery, mode
    now = int(time.time())
    data.setdefault("timestamp", now)
    return data

def _write_current(data: Dict[str, Any]) -> None:
    tmp = CURRENT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, CURRENT_PATH)

def _append_history(data: Dict[str, Any]) -> None:
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")

def _safe_read_current() -> Dict[str, Any]:
    try:
        with open(CURRENT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_latest() -> Dict[str, Any]:
    with _lock:
        data = _safe_read_current()
        ts = data.get("timestamp", 0)
        data["stale"] = (time.time() - ts) > 5
        data["last_ok_ts"] = _last_ok_ts
        return data

def get_history(limit: int = 200) -> List[Dict[str, Any]]:
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out

def poll_loop():
    global _running, _last_ok_ts
    _ensure_dirs()
    backoff = POLL_SECONDS
    while _running:
        try:
            data = _fetch_from_esp()
            with _lock:
                _write_current(data)
                _append_history(data)
                _last_ok_ts = time.time()
            backoff = POLL_SECONDS
        except Exception as e:
            # Update current with the error (no history spam)
            with _lock:
                cur = _safe_read_current()
                cur.update({"error": str(e), "timestamp": int(time.time())})
                _write_current(cur)
            backoff = min(max(backoff * 1.6, POLL_SECONDS), 5.0)
        time.sleep(backoff)

def start_polling():
    global _running
    if _running: return
    _running = True
    threading.Thread(target=poll_loop, daemon=True).start()

def stop_polling():
    global _running
    _running = False

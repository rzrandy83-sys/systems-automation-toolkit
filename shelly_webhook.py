"""
Shelly Gen4 webhook receiver (v2)
---------------------------------
Run this on your Linux desktop. The Shelly's webhooks just ping this
server with a bare GET -- they don't carry the actual switch state or
temperature value. So instead of parsing the webhook body, this script
reacts to the ping by immediately asking the Shelly for its real,
current status via its own RPC API. That guarantees the numbers here
are always live and accurate.

Requirements:
    pip install flask requests

Run:
    python shelly_webhook.py
"""

from flask import Flask, jsonify
from datetime import datetime
import requests as http

app = Flask(__name__)

SHELLY_IP = "192.168.1.68"

fireplace_status = {
    "switch_on": None,
    "temperature_c": None,
    "last_updated": None,
}


def fetch_shelly_status():
    """Ask the Shelly directly for its real current state."""
    try:
        r = http.get(f"http://{SHELLY_IP}/rpc/Shelly.GetStatus", timeout=3)
        data = r.json()

        switch_data = data.get("switch:0", {})
        fireplace_status["switch_on"] = switch_data.get("output")

        temp_data = data.get("temperature:100", {})
        fireplace_status["temperature_c"] = temp_data.get("tC")

        fireplace_status["last_updated"] = datetime.now().isoformat()

        print(f"[{datetime.now()}] Updated -> "
              f"Switch: {'ON' if fireplace_status['switch_on'] else 'OFF'}, "
              f"Temp: {fireplace_status['temperature_c']}\u00b0C")

    except Exception as e:
        print(f"[{datetime.now()}] Error fetching Shelly status: {e}")


@app.route("/shelly-update", methods=["GET", "POST"])
def shelly_update():
    fetch_shelly_status()
    return jsonify({"status": "received"}), 200


@app.route("/status", methods=["GET"])
def get_status():
    return jsonify(fireplace_status)


if __name__ == "__main__":
    # Grab the real state once at startup too, so /status isn't null
    # before the first webhook ever fires.
    fetch_shelly_status()
    app.run(host="0.0.0.0", port=5000)

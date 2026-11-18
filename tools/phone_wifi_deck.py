#!/usr/bin/env python3
"""S.P.E.C.T.R.A. Live Wi-Fi Phone Toggle Deck + RAD-DAES HIL Runner.

Lets you toggle SW1 (Source), SW2 (Fault), and SW3 (DAES/Static Mode) live from
your smartphone browser over Wi-Fi without soldering switches or re-flashing
the ESP32, while logging full RAD-DAES telemetry on your Linux PC.
"""
from __future__ import annotations

import csv
import json
import os
import socket
import sys
import threading
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAD = ROOT.parent / "rad-daes"
for p in (ROOT, ROOT / "communication", RAD / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from communication.serial.serial_reader import SpectraSerialReader
from rad_daes.background.model import BackgroundModel
from spectra_app.engine import SpectraRADEngine

PORT = os.environ.get("SPECTRA_PORT", "/dev/ttyUSB0")
BAUD = 115200
HTTP_PORT = int(os.environ.get("SPECTRA_HTTP_PORT", "8080"))

STATE_LOCK = threading.Lock()
LATEST_STATE = {
    "sample": 0,
    "src": False,
    "flt": False,
    "daes": True,
    "gate": 0,
    "alarm": False,
    "m2": 0.0,
    "alpha": 0.08,
    "eig": 10.0,
    "cov_min": 0.0,
    "stage": "WAITING_FOR_PACKET",
    "channels": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
}
SERIAL_READER: SpectraSerialReader | None = None

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>S.P.E.C.T.R.A. Phone Toggle Deck</title>
<style>
  :root {
    --bg: #0f172a; --card: #1e293b; --border: #334155;
    --text: #f8fafc; --muted: #94a3b8;
    --green: #22c55e; --red: #ef4444; --amber: #f59e0b; --blue: #38bdf8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, -apple-system, sans-serif; }
  body { background: var(--bg); color: var(--text); padding: 14px; max-width: 460px; margin: 0 auto; }
  .hdr { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 12px; }
  .title { font-size: 1.05rem; font-weight: 800; letter-spacing: 0.04em; }
  .sub { font-size: 0.74rem; color: var(--muted); margin-top: 2px; }
  .badge { padding: 6px 10px; border-radius: 8px; font-weight: 800; font-size: 0.78rem; color: #000; background: var(--green); }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 14px; }
  .metric { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 10px; text-align: center; }
  .metric .lbl { font-size: 0.68rem; color: var(--muted); text-transform: uppercase; }
  .metric .val { font-size: 1.12rem; font-weight: 800; margin-top: 3px; font-variant-numeric: tabular-nums; }
  .sw-card { background: var(--card); border: 2px solid var(--border); border-radius: 14px; padding: 15px 16px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; user-select: none; -webkit-tap-highlight-color: transparent; transition: transform 0.08s, border-color 0.15s; }
  .sw-card:active { transform: scale(0.98); }
  .sw-name { font-size: 0.96rem; font-weight: 700; }
  .sw-desc { font-size: 0.74rem; color: var(--muted); margin-top: 3px; }
  .pill { min-width: 88px; text-align: center; padding: 8px 12px; border-radius: 999px; font-weight: 800; font-size: 0.8rem; background: #334155; color: var(--text); }
  .on-src { border-color: var(--red); }
  .on-src .pill { background: var(--red); color: #fff; }
  .on-flt { border-color: var(--amber); }
  .on-flt .pill { background: var(--amber); color: #000; }
  .on-daes { border-color: var(--blue); }
  .on-daes .pill { background: var(--blue); color: #000; }
  .reset-btn { width: 100%; padding: 13px; border-radius: 12px; border: 1px solid var(--border); background: #1e293b; color: var(--text); font-weight: 700; font-size: 0.82rem; cursor: pointer; margin-top: 4px; }
  .reset-btn:active { background: #334155; }
</style>
</head>
<body>
  <div class="hdr">
    <div>
      <div class="title">S.P.E.C.T.R.A. DECK</div>
      <div class="sub">Sample #<span id="smp">0</span> &bull; <span id="stg">CONNECTING</span></div>
    </div>
    <div id="gateBadge" class="badge">GATE: OK</div>
  </div>

  <div class="grid">
    <div class="metric"><div class="lbl">M&sup2; Score</div><div class="val" id="m2">0.0</div></div>
    <div class="metric"><div class="lbl">DAES &alpha;</div><div class="val" id="alp">0.080</div></div>
    <div class="metric"><div class="lbl">Min Eig</div><div class="val" id="eig">0.00</div></div>
  </div>

  <div id="cardSrc" class="sw-card" onclick="toggleSw('1')">
    <div>
      <div class="sw-name">SW1: SOURCE INJECT</div>
      <div class="sw-desc">Synthetic Cs-137 Anomaly (Serial '1')</div>
    </div>
    <div id="pillSrc" class="pill">OFF</div>
  </div>

  <div id="cardFlt" class="sw-card" onclick="toggleSw('2')">
    <div>
      <div class="sw-name">SW2: FAULT INJECT</div>
      <div class="sw-desc">Frozen Count / Dropout (Serial '2')</div>
    </div>
    <div id="pillFlt" class="pill">OFF</div>
  </div>

  <div id="cardDaes" class="sw-card on-daes" onclick="toggleSw('3')">
    <div>
      <div class="sw-name">SW3: ADAPTATION MODE</div>
      <div class="sw-desc">DAES Eigen-Scaling vs. Static (Serial '3')</div>
    </div>
    <div id="pillDaes" class="pill">DAES ON</div>
  </div>

  <button class="reset-btn" onclick="toggleSw('reset')">RESET TO CLEAN DAES BASELINE (1, 0, 0)</button>

<script>
function render(d) {
  document.getElementById('smp').textContent = d.sample;
  document.getElementById('stg').textContent = d.stage;
  document.getElementById('m2').textContent = Number(d.m2).toFixed(1);
  document.getElementById('alp').textContent = Number(d.alpha).toFixed(3);
  document.getElementById('eig').textContent = Number(d.cov_min).toFixed(2);

  const b = document.getElementById('gateBadge');
  if (d.alarm) { b.textContent = 'ALARM!'; b.style.background = '#ef4444'; b.style.color = '#fff'; }
  else if (d.gate === 1) { b.textContent = 'FLT:GATE'; b.style.background = '#f59e0b'; b.style.color = '#000'; }
  else if (d.gate === 2) { b.textContent = 'HOLD:SRC'; b.style.background = '#fb923c'; b.style.color = '#000'; }
  else { b.textContent = 'GATE:OK'; b.style.background = '#22c55e'; b.style.color = '#000'; }

  const cSrc = document.getElementById('cardSrc'), pSrc = document.getElementById('pillSrc');
  cSrc.className = 'sw-card' + (d.src ? ' on-src' : '');
  pSrc.textContent = d.src ? 'ACTIVE' : 'OFF';

  const cFlt = document.getElementById('cardFlt'), pFlt = document.getElementById('pillFlt');
  cFlt.className = 'sw-card' + (d.flt ? ' on-flt' : '');
  pFlt.textContent = d.flt ? 'FAULT ON' : 'OFF';

  const cDaes = document.getElementById('cardDaes'), pDaes = document.getElementById('pillDaes');
  cDaes.className = 'sw-card' + (d.daes ? ' on-daes' : '');
  pDaes.textContent = d.daes ? 'DAES ON' : 'STATIC';
}

async function toggleSw(cmd) {
  try {
    const r = await fetch('/toggle?sw=' + cmd);
    render(await r.json());
  } catch (e) {}
}

async function poll() {
  try {
    const r = await fetch('/status');
    render(await r.json());
  } catch (e) {}
}
setInterval(poll, 700);
poll();
</script>
</body>
</html>
"""


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def send_serial_cmd(cmd: str) -> None:
    global SERIAL_READER
    if SERIAL_READER and SERIAL_READER.is_connected and SERIAL_READER.connection:
        SERIAL_READER.connection.write(cmd.encode("ascii"))
        SERIAL_READER.connection.flush()
        print(f"  [PHONE WI-FI TOGGLE] Sent command '{cmd}' to ESP32")


class DeckHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return  # Keep terminal telemetry output clean

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/toggle":
            qs = parse_qs(parsed.query)
            sw = qs.get("sw", [""])[0]
            with STATE_LOCK:
                if sw in ("1", "2", "3"):
                    send_serial_cmd(sw)
                    if sw == "1":
                        LATEST_STATE["src"] = not LATEST_STATE["src"]
                    elif sw == "2":
                        LATEST_STATE["flt"] = not LATEST_STATE["flt"]
                    elif sw == "3":
                        LATEST_STATE["daes"] = not LATEST_STATE["daes"]
                elif sw == "reset":
                    if LATEST_STATE["src"]:
                        send_serial_cmd("1")
                        LATEST_STATE["src"] = False
                    if LATEST_STATE["flt"]:
                        send_serial_cmd("2")
                        LATEST_STATE["flt"] = False
                    if not LATEST_STATE["daes"]:
                        send_serial_cmd("3")
                        LATEST_STATE["daes"] = True
                payload = json.dumps(LATEST_STATE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/status":
            with STATE_LOCK:
                payload = json.dumps(LATEST_STATE).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(404)
        self.end_headers()


def stage_name(packet) -> str:
    if packet.source and packet.fault:
        return "SOURCE_AND_FAULT_INJECTION"
    if packet.source:
        return "SOURCE_INJECTION"
    if packet.fault:
        return "FAULT_INJECTION"
    if packet.mode == 0:
        return "STATIC_MODE"
    if packet.firmware_gate == 1:
        return "FIRMWARE_FAULT"
    if packet.firmware_gate == 2:
        return "FIRMWARE_HOLD"
    return "CLEAN_DAES"


def main() -> None:
    global SERIAL_READER
    model_dir = ROOT / "data" / "processed"
    export_dir = ROOT / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    models = sorted(
        model_dir.glob("background_model_*.npz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not models:
        raise FileNotFoundError(f"No calibrated background model found in {model_dir}")
    config = RAD / "configs" / "model.yaml"
    with np.load(models[0], allow_pickle=False) as data:
        model = BackgroundModel(
            data["mean"].astype(float), data["covariance"].astype(float)
        )
    engine = SpectraRADEngine(model, config)

    SERIAL_READER = SpectraSerialReader(PORT, BAUD, timeout=3.0)
    SERIAL_READER.connect()

    httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), DeckHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    lan_ip = get_lan_ip()

    print("\n========================================================")
    print("  S.P.E.C.T.R.A. WI-FI PHONE TOGGLE DECK IS LIVE!")
    print(f"  >>> OPEN ON YOUR PHONE: http://{lan_ip}:{HTTP_PORT} <<<")
    print("  (Make sure your phone & PC are on the same Wi-Fi)")
    print("  Press Ctrl+C in this terminal when finished.")
    print("========================================================\n")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = export_dir / f"spectra_wifi_session_{stamp}.csv"
    fields = [
        "sample", "timestamp_ms", "interval_ms", "mode", "mode_label",
        "source", "fault", "control_state", "test_stage", "firmware_gate",
        "firmware_m2", "firmware_eigenvalue", "firmware_alpha",
        "firmware_background_level", "score", "threshold", "alarm",
        "telemetry_valid", "adaptation_allowed", "adaptation_applied",
        "eta_applied", "daes_raw_rayleigh", "daes_filtered_lambda",
        "daes_drift_score", "daes_alpha", "covariance_min_eigenvalue",
        "covariance_trace", "reason", "W0", "W1", "W2", "W3", "W4", "W5",
        "raw_packet",
    ]
    rows = []
    try:
        with csv_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for packet in SERIAL_READER.stream():
                result = engine.process(packet)
                stg = stage_name(packet)
                with STATE_LOCK:
                    LATEST_STATE.update({
                        "sample": int(packet.sample),
                        "src": bool(packet.source),
                        "flt": bool(packet.fault),
                        "daes": bool(packet.mode == 1),
                        "gate": int(packet.firmware_gate),
                        "alarm": bool(result.alarm),
                        "m2": float(result.score),
                        "alpha": float(result.daes_alpha),
                        "eig": float(packet.firmware_eigenvalue),
                        "cov_min": float(result.covariance_min_eigenvalue),
                        "stage": stg,
                        "channels": list(packet.channels),
                    })
                row = {
                    "sample": packet.sample,
                    "timestamp_ms": packet.timestamp_ms,
                    "interval_ms": packet.interval_ms,
                    "mode": packet.mode,
                    "mode_label": "DAES" if packet.mode == 1 else "STATIC",
                    "source": packet.source,
                    "fault": packet.fault,
                    "control_state": result.control_state,
                    "test_stage": stg,
                    "firmware_gate": packet.firmware_gate,
                    "firmware_m2": packet.firmware_m2,
                    "firmware_eigenvalue": packet.firmware_eigenvalue,
                    "firmware_alpha": packet.firmware_alpha,
                    "firmware_background_level": packet.background_level,
                    "score": result.score,
                    "threshold": result.threshold,
                    "alarm": result.alarm,
                    "telemetry_valid": result.telemetry_valid,
                    "adaptation_allowed": result.adaptation_allowed,
                    "adaptation_applied": result.adaptation_applied,
                    "eta_applied": result.eta,
                    "daes_raw_rayleigh": result.daes_raw_rayleigh,
                    "daes_filtered_lambda": result.daes_filtered_lambda,
                    "daes_drift_score": result.daes_drift_score,
                    "daes_alpha": result.daes_alpha,
                    "covariance_min_eigenvalue": result.covariance_min_eigenvalue,
                    "covariance_trace": result.covariance_trace,
                    "reason": result.reason,
                    "raw_packet": packet.raw,
                }
                for i, val in enumerate(packet.channels):
                    row[f"W{i}"] = val
                writer.writerow(row)
                stream.flush()
                rows.append(row)
                print(
                    f"[{stg}] Sample={result.sample} | M2={result.score:.2f} | "
                    f"Mode={packet.mode} Src={packet.source} Flt={packet.fault} "
                    f"Gate={packet.firmware_gate} | Adapt={result.adaptation_applied}"
                )
    except KeyboardInterrupt:
        print("\n[SPECTRA] Stopping Wi-Fi Phone Deck session...")
    finally:
        httpd.shutdown()
        SERIAL_READER.close()
        print(f"[SPECTRA] Saved {len(rows)} samples to {csv_path}")


if __name__ == "__main__":
    main()

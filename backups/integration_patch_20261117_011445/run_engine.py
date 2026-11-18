"""Live S.P.E.C.T.R.A. RAD-DAES hardware-in-the-loop runner."""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from communication.serial.serial_reader import SpectraSerialReader
from rad_daes.background.model import BackgroundModel
from spectra_app.engine import SpectraRADEngine


def main():
    root = Path(__file__).resolve().parents[1]
    repo = Path.cwd()

    model_dir = root / "data" / "processed"
    export_dir = root / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    models = sorted(
        model_dir.glob("background_model_*.npz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not models:
        raise FileNotFoundError("No calibrated background model found.")

    config_path = repo / "configs" / "model.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"RAD-DAES config not found: {config_path}")

    with np.load(models[0], allow_pickle=False) as data:
        mean = data["mean"].astype(float)
        covariance = data["covariance"].astype(float)

    model = BackgroundModel(mean=mean, covariance=covariance)
    engine = SpectraRADEngine(model, config_path)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = export_dir / f"spectra_engine_{stamp}.csv"

    fields = [
        "sample", "score", "threshold", "alarm",
        "telemetry_valid", "adaptation_allowed",
        "adaptation_applied", "eta", "firmware_gate", "reason",
    ]

    reader = SpectraSerialReader("COM4", 115200, timeout=3.0)

    print("\n========== S.P.E.C.T.R.A. RAD-DAES ENGINE ==========")
    print("Model:", models[0])
    print("Config:", config_path)
    print("Alarm threshold:", engine.threshold)
    print("Persistence:", engine.persistence)
    print("Opening COM4. Press Ctrl+C to stop.\n")

    try:
        with log_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            reader.connect()

            for packet in reader.stream():
                result = engine.process(packet)

                row = {
                    "sample": result.sample,
                    "score": result.score,
                    "threshold": result.threshold,
                    "alarm": result.alarm,
                    "telemetry_valid": result.telemetry_valid,
                    "adaptation_allowed": result.adaptation_allowed,
                    "adaptation_applied": result.adaptation_applied,
                    "eta": result.eta,
                    "firmware_gate": result.firmware_gate,
                    "reason": result.reason,
                }

                writer.writerow(row)
                f.flush()

                status = "ALARM" if result.alarm else "NORMAL"

                print(
                    f"Sample={result.sample} | "
                    f"M2={result.score:.3f} | "
                    f"{status} | "
                    f"Adapt={result.adaptation_applied} | "
                    f"eta={result.eta:.6f} | "
                    f"{result.reason}"
                )

    except KeyboardInterrupt:
        print("\nEngine stopped by user.")

    finally:
        reader.close()

    print("\n========== ENGINE SESSION SUMMARY ==========")
    print("Processed:", engine.processed)
    print("Adaptations:", engine.adaptations)
    print("Alarms:", engine.alarms)
    print("Final mean:", np.round(engine.mean, 4))
    print("Log:", log_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nENGINE FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)

"""Capture a clean synthetic HIL baseline for S.P.E.C.T.R.A."""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from communication.serial.serial_reader import SpectraSerialReader
from spectra_app.algorithms.calibration import build_background_model

SAMPLE_COUNT = 120
WARMUP_COUNT = 12
PORT = "/dev/ttyUSB0"
BAUD = 115200
MIN_INTERVAL_MS = 750
MAX_INTERVAL_MS = 1350
MAX_REJECTED_PACKETS = 60


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    raw_dir = root / "data" / "raw"
    processed_dir = root / "data" / "processed"

    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    baseline_path = raw_dir / f"baseline_{stamp}.csv"
    rejected_path = raw_dir / f"baseline_rejected_{stamp}.csv"
    model_path = processed_dir / f"background_model_{stamp}.npz"

    accepted: list[dict] = []
    rejected: list[dict] = []
    warmup_seen = 0
    total_seen = 0

    reader = SpectraSerialReader(PORT, BAUD, timeout=3.0)

    print("\n========== S.P.E.C.T.R.A. BASELINE CAPTURE ==========")
    print(f"Port: {PORT} | Baud: {BAUD}")
    print(f"Startup warm-up: {WARMUP_COUNT} packets")
    print(f"Required clean baseline: {SAMPLE_COUNT} packets")
    print("Keep source and fault injection OFF.")
    print("Keep DAES mode ON.\n")

    try:
        reader.connect()

        while len(accepted) < SAMPLE_COUNT:
            packet = reader.read_packet()

            if packet is None:
                continue

            total_seen += 1

            if packet.mode != 1 or packet.source != 0 or packet.fault != 0:
                raise RuntimeError(
                    "Unsafe capture state: expected DAES mode ON, "
                    "source OFF and fault OFF. Capture aborted."
                )

            if not MIN_INTERVAL_MS <= packet.interval_ms <= MAX_INTERVAL_MS:
                rejected.append({
                    "sample": packet.sample,
                    "reason": "invalid_timing",
                    "firmware_gate": packet.firmware_gate,
                    "interval_ms": packet.interval_ms,
                    **{f"W{i}": packet.channels[i] for i in range(6)},
                })
                print(
                    f"[REJECT] Sample {packet.sample}: "
                    f"invalid interval {packet.interval_ms} ms"
                )
                continue

            if warmup_seen < WARMUP_COUNT:
                warmup_seen += 1
                print(
                    f"[WARMUP {warmup_seen:02d}/{WARMUP_COUNT}] "
                    f"Sample={packet.sample} | Gate={packet.firmware_gate}"
                )
                continue

            if packet.firmware_gate != 0:
                rejected.append({
                    "sample": packet.sample,
                    "reason": f"firmware_gate_{packet.firmware_gate}",
                    "firmware_gate": packet.firmware_gate,
                    "interval_ms": packet.interval_ms,
                    **{f"W{i}": packet.channels[i] for i in range(6)},
                })
                print(
                    f"[REJECT] Sample {packet.sample}: "
                    f"firmware gate={packet.firmware_gate}"
                )

                if len(rejected) > MAX_REJECTED_PACKETS:
                    raise RuntimeError(
                        "Too many rejected packets. Firmware integrity "
                        "is unstable; refusing to calibrate."
                    )
                continue

            record = {
                "sample": packet.sample,
                "timestamp_ms": packet.timestamp_ms,
                "interval_ms": packet.interval_ms,
                "firmware_gate": packet.firmware_gate,
                "firmware_m2": packet.firmware_m2,
                "firmware_eigenvalue": packet.firmware_eigenvalue,
                "firmware_alpha": packet.firmware_alpha,
                "background_level": packet.background_level,
            }

            for i in range(6):
                record[f"W{i}"] = packet.channels[i]

            accepted.append(record)

            print(
                f"[BASELINE {len(accepted):03d}/{SAMPLE_COUNT}] "
                f"Sample={packet.sample} | "
                f"Channels={packet.channels}"
            )

    except KeyboardInterrupt:
        print("\nCapture interrupted. No model will be generated.")
        return 1

    except Exception as exc:
        print(f"\nCAPTURE FAILED: {exc}")
        return 1

    finally:
        reader.close()

    if len(accepted) != SAMPLE_COUNT:
        print("Incomplete baseline. No model generated.")
        return 1

    with baseline_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=accepted[0].keys())
        writer.writeheader()
        writer.writerows(accepted)

    if rejected:
        with rejected_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rejected[0].keys())
            writer.writeheader()
            writer.writerows(rejected)

    samples = np.asarray(
        [[row[f"W{i}"] for i in range(6)] for row in accepted],
        dtype=float,
    )

    model = build_background_model(samples)

    eigenvalues = np.linalg.eigvalsh(model.covariance)

    if not np.all(np.isfinite(model.mean)):
        raise RuntimeError("Generated mean contains non-finite values.")

    if not np.all(np.isfinite(model.covariance)):
        raise RuntimeError("Generated covariance contains non-finite values.")

    if eigenvalues.min() <= 0:
        raise RuntimeError("Generated covariance is not positive definite.")

    np.savez(
        model_path,
        mean=model.mean,
        covariance=model.covariance,
        sample_count=len(accepted),
        channels=6,
        source="synthetic_poisson_hil_baseline",
        created_at=stamp,
    )

    print("\n========== BASELINE COMPLETE ==========")
    print("Accepted samples:", len(accepted))
    print("Warm-up packets:", warmup_seen)
    print("Rejected packets:", len(rejected))
    print("Mean:", np.round(model.mean, 4))
    print("Covariance diagonal:", np.round(np.diag(model.covariance), 4))
    print("Minimum covariance eigenvalue:", float(eigenvalues.min()))
    print("Baseline CSV:", baseline_path)
    print("Background model:", model_path)

    if rejected:
        print("Rejected-packet audit:", rejected_path)

    print("\nNOTE: This is a synthetic HIL baseline, not a physical")
    print("radiation-background calibration or a validated FAR estimate.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""One-pass automated S.P.E.C.T.R.A. synthetic Poisson HIL validation."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

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
SAMPLES_PER_STAGE = int(os.environ.get("SPECTRA_SAMPLES_PER_STAGE", "12"))
MAX_MISMATCH_PACKETS = 5

STAGES = [
    {"name": "CLEAN_DAES", "mode": 1, "source": 0, "fault": 0, "command": None},
    {"name": "SOURCE_INJECTION", "mode": 1, "source": 1, "fault": 0, "command": "1"},
    {"name": "SOURCE_RECOVERY", "mode": 1, "source": 0, "fault": 0, "command": "1"},
    {"name": "FAULT_INJECTION", "mode": 1, "source": 0, "fault": 1, "command": "2"},
    {"name": "FAULT_RECOVERY", "mode": 1, "source": 0, "fault": 0, "command": "2"},
    {"name": "STATIC_MODE", "mode": 0, "source": 0, "fault": 0, "command": "3"},
    {"name": "DAES_RECOVERY", "mode": 1, "source": 0, "fault": 0, "command": "3"},
]


def emit_command(reader: SpectraSerialReader, command: str) -> None:
    if not reader.is_connected or reader.connection is None:
        raise RuntimeError("Serial connection is not open; cannot actuate firmware.")
    reader.connection.write(command.encode("ascii"))
    reader.connection.flush()
    print(f"[CONTROL] Sent firmware toggle command {command!r}")


def packet_state(packet) -> tuple[int, int, int]:
    return int(packet.mode), int(packet.source), int(packet.fault)


def stage_match(packet, stage) -> bool:
    return packet_state(packet) == (stage["mode"], stage["source"], stage["fault"])


def stage_for(packet) -> str:
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


def main() -> int:
    print("\n========== S.P.E.C.T.R.A. ONE-PASS VALIDATION ==========")
    print(f"Project: {ROOT}")
    print(f"RAD-DAES: {RAD}")
    print(f"Serial: {PORT} @ {BAUD}")
    print("Classification: SYNTHETIC POISSON HARDWARE-IN-THE-LOOP")

    model_dir = ROOT / "data" / "processed"
    export_dir = ROOT / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    models = sorted(model_dir.glob("background_model_*.npz"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not models:
        raise FileNotFoundError(f"No background_model_*.npz found in {model_dir}")
    config = RAD / "configs" / "model.yaml"
    if not config.is_file():
        raise FileNotFoundError(f"RAD-DAES config missing: {config}")

    with np.load(models[0], allow_pickle=False) as data:
        model = BackgroundModel(data["mean"].astype(float), data["covariance"].astype(float))
    engine = SpectraRADEngine(model, config)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = export_dir / f"spectra_full_validation_{stamp}.csv"
    json_path = export_dir / f"spectra_full_validation_{stamp}.json"
    md_path = export_dir / f"spectra_full_validation_{stamp}.md"

    fields = [
        "stage_requested", "sample", "timestamp_ms", "interval_ms", "mode", "source", "fault",
        "firmware_gate", "firmware_m2", "firmware_eigenvalue", "firmware_alpha", "background_level",
        "score", "threshold", "alarm", "telemetry_valid", "adaptation_allowed", "adaptation_applied",
        "eta", "daes_raw_rayleigh", "daes_filtered_lambda", "daes_drift_score", "daes_alpha",
        "covariance_min_eigenvalue", "covariance_trace", "control_state", "reason",
        "W0", "W1", "W2", "W3", "W4", "W5", "raw_packet",
    ]
    rows = []
    stage_counts = Counter()
    stage_adaptations = Counter()
    stage_mismatches = Counter()
    reader = SpectraSerialReader(PORT, BAUD, timeout=3.0)
    current_stage_index = 0
    current_stage_count = 0
    mismatch_count = 0
    completed = False
    start_state_checked = False
    command_sent_for_stage = False
    commanded_state = None

    try:
        reader.connect()
        print("\n[PRECHECK] First packet must confirm physical SOURCE=OFF, FAULT=OFF, MODE=DAES.")
        print("[PRECHECK] Do not touch physical switches during the automated run.\n")

        with csv_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            stream.flush()

            for packet in reader.stream():
                if not start_state_checked:
                    start_state_checked = True
                    if packet_state(packet) != (1, 0, 0):
                        raise RuntimeError(
                            "Initial hardware state is not DAES / SOURCE OFF / FAULT OFF. "
                            f"Observed mode/source/fault={packet_state(packet)}. "
                            "Set physical switches to the required baseline and rerun."
                        )
                    commanded_state = list(packet_state(packet))
                    print(f"[PRECHECK PASS] Initial state mode/source/fault={packet_state(packet)}")

                if current_stage_index >= len(STAGES):
                    completed = True
                    break

                stage = STAGES[current_stage_index]
                if current_stage_count == 0 and stage["command"] is not None and not command_sent_for_stage:
                    # Command is sent once at stage entry. The stage is counted only after
                    # the packet itself confirms the requested state.
                    emit_command(reader, stage["command"])
                    commanded_state = [stage["mode"], stage["source"], stage["fault"]]
                    command_sent_for_stage = True

                matched = stage_match(packet, stage)
                if matched:
                    mismatch_count = 0
                    current_stage_count += 1
                    stage_counts[stage["name"]] += 1
                else:
                    mismatch_count += 1
                    stage_mismatches[stage["name"]] += 1
                    if mismatch_count >= MAX_MISMATCH_PACKETS:
                        raise RuntimeError(
                            f"Firmware did not confirm stage {stage['name']} after "
                            f"{MAX_MISMATCH_PACKETS} packets. Last observed state={packet_state(packet)}; "
                            f"expected={(stage['mode'], stage['source'], stage['fault'])}. "
                            "Check physical switch overrides and firmware serial connection."
                        )

                result = engine.process(packet)
                row = {
                    "stage_requested": stage["name"], "sample": packet.sample,
                    "timestamp_ms": packet.timestamp_ms, "interval_ms": packet.interval_ms,
                    "mode": packet.mode, "source": packet.source, "fault": packet.fault,
                    "firmware_gate": packet.firmware_gate, "firmware_m2": packet.firmware_m2,
                    "firmware_eigenvalue": packet.firmware_eigenvalue,
                    "firmware_alpha": packet.firmware_alpha, "background_level": packet.background_level,
                    "score": result.score, "threshold": result.threshold, "alarm": result.alarm,
                    "telemetry_valid": result.telemetry_valid,
                    "adaptation_allowed": result.adaptation_allowed,
                    "adaptation_applied": result.adaptation_applied, "eta": result.eta,
                    "daes_raw_rayleigh": result.daes_raw_rayleigh,
                    "daes_filtered_lambda": result.daes_filtered_lambda,
                    "daes_drift_score": result.daes_drift_score, "daes_alpha": result.daes_alpha,
                    "covariance_min_eigenvalue": result.covariance_min_eigenvalue,
                    "covariance_trace": result.covariance_trace,
                    "control_state": result.control_state, "reason": result.reason,
                    "raw_packet": packet.raw,
                }
                for i, value in enumerate(packet.channels):
                    row[f"W{i}"] = value
                writer.writerow(row)
                stream.flush()
                rows.append(row)
                if result.adaptation_applied and matched:
                    stage_adaptations[stage["name"]] += 1

                print(
                    f"[{stage['name']}] {current_stage_count}/{SAMPLES_PER_STAGE if matched else 'waiting'} "
                    f"sample={packet.sample} mode={packet.mode} src={packet.source} fault={packet.fault} "
                    f"gate={packet.firmware_gate} adapt={result.adaptation_applied} "
                    f"M2={result.score:.3f} cov_min_eig={result.covariance_min_eigenvalue:.6g}"
                )

                if current_stage_count >= SAMPLES_PER_STAGE:
                    print(f"[STAGE PASS] {stage['name']} observed for {current_stage_count} packets.")
                    current_stage_index += 1
                    current_stage_count = 0
                    mismatch_count = 0
                    command_sent_for_stage = False
                    if current_stage_index >= len(STAGES):
                        completed = True
                        break

    except KeyboardInterrupt:
        print("\n[STOP] User interrupted the live test; a partial report will be written.")
    finally:
        # Best-effort restore of serial-controlled state to the clean DAES baseline.
        # Physical switches must remain in their prechecked OFF/OFF/DAES positions.
        if reader.is_connected and commanded_state is not None:
            try:
                for index, command in ((1, "1"), (2, "2"), (0, "3")):
                    baseline_value = 1 if index == 0 else 0
                    if int(commanded_state[index]) != baseline_value:
                        emit_command(reader, command)
                        commanded_state[index] = baseline_value
                print("[CLEANUP] Sent best-effort commands to restore DAES / SOURCE OFF / FAULT OFF.")
            except Exception as cleanup_exc:
                print(f"[CLEANUP WARNING] Could not restore serial state: {cleanup_exc}")
        reader.close()

    unsafe = [r for r in rows if bool(r["adaptation_applied"]) and (
        int(r["firmware_gate"]) != 0 or not 500 <= int(r["interval_ms"]) <= 1500
        or int(r["source"]) != 0 or int(r["fault"]) != 0 or int(r["mode"]) != 1
    )]
    bad_cov = [r for r in rows if not np.isfinite(float(r["covariance_min_eigenvalue"]))
               or float(r["covariance_min_eigenvalue"]) <= 0]
    required_stages = [s["name"] for s in STAGES]
    stage_observed = {name: stage_counts[name] >= SAMPLES_PER_STAGE for name in required_stages}
    clean_resume = stage_adaptations["CLEAN_DAES"] > 0 and stage_adaptations["DAES_RECOVERY"] > 0
    checks = {
        "all_seven_stages_observed": all(stage_observed.values()),
        "no_adaptation_during_injection_or_static": len(unsafe) == 0,
        "covariance_positive_definite_for_all_samples": len(bad_cov) == 0,
        "adaptation_observed_in_clean_and_recovered_DAES": clean_resume,
        "live_test_completed_without_manual_interruption": completed,
    }
    summary = {
        "project": "S.P.E.C.T.R.A. / RAD-DAES",
        "classification": "SYNTHETIC_POISSON_HARDWARE_IN_THE_LOOP",
        "port": PORT, "baud": BAUD, "samples_per_stage_target": SAMPLES_PER_STAGE,
        "completed": completed, "samples_recorded": len(rows),
        "engine_processed": engine.processed, "adaptations": engine.adaptations,
        "alarms": engine.alarms, "stage_sample_counts": dict(stage_counts),
        "stage_adaptation_counts": dict(stage_adaptations),
        "stage_mismatch_counts": dict(stage_mismatches),
        "stage_observed": stage_observed, "automated_checks": checks,
        "unsafe_adaptation_rows": len(unsafe), "non_positive_covariance_rows": len(bad_cov),
        "serial_parse_errors": reader.parse_errors, "serial_ignored_lines": reader.ignored_lines,
        "final_covariance_min_eigenvalue": float(np.linalg.eigvalsh(engine.covariance).min()),
        "final_mean": np.asarray(engine.mean).tolist(),
        "scientific_limitations": (
            "Synthetic Poisson HIL only. No physical radiation sensor measurements, "
            "field validation, detection-accuracy claim, or validated false-alarm rate."
        ),
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md = [
        "# S.P.E.C.T.R.A. Automated HIL Validation", "",
        f"- Completion: **{'COMPLETE' if completed else 'PARTIAL'}**",
        f"- Recorded samples: **{len(rows)}**", f"- Adaptations: **{engine.adaptations}**",
        f"- Alarms: **{engine.alarms}**", "", "## Stage observations", "",
    ]
    md += [f"- {name}: {stage_counts[name]} samples; {stage_adaptations[name]} adaptations"
           for name in required_stages]
    md += ["", "## Automated checks", ""]
    md += [f"- {name}: **{'PASS' if passed else 'FAIL'}**" for name, passed in checks.items()]
    md += [
        "", f"- Unsafe adaptation rows: {len(unsafe)}",
        f"- Non-positive covariance rows: {len(bad_cov)}",
        f"- Serial parse errors: {reader.parse_errors}",
        f"- Ignored serial lines: {reader.ignored_lines}", "",
        "## Scientific limitations", "", summary["scientific_limitations"],
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    print("\n========== FINAL VALIDATION SUMMARY ==========")
    for name, passed in checks.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print(f"Samples={len(rows)} Adaptations={engine.adaptations} Alarms={engine.alarms}")
    print(f"CSV: {csv_path}\nJSON: {json_path}\nMarkdown: {md_path}")
    return 0 if all(checks.values()) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nVALIDATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)

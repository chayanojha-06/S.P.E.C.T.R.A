"""Live S.P.E.C.T.R.A. RAD-DAES HIL runner with complete telemetry audit."""
from __future__ import annotations
import csv, json, sys
from collections import Counter
from datetime import datetime
from pathlib import Path
import numpy as np
from communication.serial.serial_reader import SpectraSerialReader
from rad_daes.background.model import BackgroundModel
from spectra_app.engine import SpectraRADEngine

def find_config(root):
    candidates = [
        Path.cwd() / "configs" / "model.yaml",
        root.parent / "rad-daes" / "configs" / "model.yaml",
        root.parent / "rad_daes" / "configs" / "model.yaml",
    ]
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError("Original RAD-DAES configs/model.yaml not found.")

def stage(packet):
    if packet.source and packet.fault: return "SOURCE_AND_FAULT_INJECTION"
    if packet.source: return "SOURCE_INJECTION"
    if packet.fault: return "FAULT_INJECTION"
    if packet.mode == 0: return "STATIC_MODE"
    if packet.firmware_gate == 1: return "FIRMWARE_FAULT"
    if packet.firmware_gate == 2: return "FIRMWARE_HOLD"
    return "CLEAN_DAES"

def main():
    root = Path(__file__).resolve().parents[1]
    model_dir = root / "data" / "processed"
    export_dir = root / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    models = sorted(model_dir.glob("background_model_*.npz"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    if not models: raise FileNotFoundError("No calibrated background model found.")
    config = find_config(root)
    with np.load(models[0], allow_pickle=False) as data:
        model = BackgroundModel(data["mean"].astype(float), data["covariance"].astype(float))
    engine = SpectraRADEngine(model, config)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = export_dir / f"spectra_engine_{stamp}.csv"
    report_path = export_dir / f"spectra_validation_{stamp}.md"
    fields = [
        "sample","timestamp_ms","interval_ms","mode","mode_label","source","fault",
        "control_state","test_stage","firmware_gate","firmware_m2","firmware_eigenvalue",
        "firmware_alpha","firmware_background_level","score","threshold","alarm",
        "telemetry_valid","adaptation_allowed","adaptation_applied","eta_applied",
        "daes_raw_rayleigh","daes_filtered_lambda","daes_drift_score","daes_alpha",
        "covariance_min_eigenvalue","covariance_trace","reason",
        "W0","W1","W2","W3","W4","W5","raw_packet"
    ]
    reader = SpectraSerialReader("/dev/ttyUSB0", 115200, timeout=3.0)
    rows = []
    print("\n========== S.P.E.C.T.R.A. INTEGRATED RAD-DAES ENGINE ==========")
    print("Model:", models[0], "\nConfig:", config)
    print("Classification: SYNTHETIC POISSON HIL")
    print("Close Arduino Serial Monitor. Press Ctrl+C to stop.\n")
    try:
        with csv_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            reader.connect()
            for packet in reader.stream():
                result = engine.process(packet)
                row = {
                    "sample":packet.sample, "timestamp_ms":packet.timestamp_ms,
                    "interval_ms":packet.interval_ms, "mode":packet.mode,
                    "mode_label":"DAES" if packet.mode == 1 else "STATIC",
                    "source":packet.source, "fault":packet.fault,
                    "control_state":result.control_state, "test_stage":stage(packet),
                    "firmware_gate":packet.firmware_gate, "firmware_m2":packet.firmware_m2,
                    "firmware_eigenvalue":packet.firmware_eigenvalue,
                    "firmware_alpha":packet.firmware_alpha,
                    "firmware_background_level":packet.background_level,
                    "score":result.score, "threshold":result.threshold, "alarm":result.alarm,
                    "telemetry_valid":result.telemetry_valid,
                    "adaptation_allowed":result.adaptation_allowed,
                    "adaptation_applied":result.adaptation_applied,
                    "eta_applied":result.eta,
                    "daes_raw_rayleigh":result.daes_raw_rayleigh,
                    "daes_filtered_lambda":result.daes_filtered_lambda,
                    "daes_drift_score":result.daes_drift_score,
                    "daes_alpha":result.daes_alpha,
                    "covariance_min_eigenvalue":result.covariance_min_eigenvalue,
                    "covariance_trace":result.covariance_trace,
                    "reason":result.reason, "raw_packet":packet.raw,
                }
                for i, value in enumerate(packet.channels): row[f"W{i}"] = value
                writer.writerow(row); stream.flush(); rows.append(row)
                print(
                    f"Sample={result.sample} | M2={result.score:.3f} | "
                    f"Mode={packet.mode} Source={packet.source} Fault={packet.fault} "
                    f"Gate={packet.firmware_gate} | Adapt={result.adaptation_applied} "
                    f"| eta={result.eta:.6f} | {result.control_state} | {result.reason}"
                )
    except KeyboardInterrupt:
        print("\nEngine stopped by user.")
    finally:
        reader.close()

    counts = Counter(r["test_stage"] for r in rows)
    source_n = sum(int(r["source"]) == 1 for r in rows)
    fault_n = sum(int(r["fault"]) == 1 for r in rows)
    static_n = sum(int(r["mode"]) == 0 for r in rows)
    daes_n = sum(int(r["mode"]) == 1 for r in rows)
    unsafe = [r for r in rows if r["adaptation_applied"] and (
        int(r["firmware_gate"]) != 0 or not 500 <= int(r["interval_ms"]) <= 1500
        or int(r["source"]) != 0 or int(r["fault"]) != 0 or int(r["mode"]) != 1)]
    bad_cov = [r for r in rows if not np.isfinite(float(r["covariance_min_eigenvalue"]))
               or float(r["covariance_min_eigenvalue"]) <= 0]
    controls = {
        "source_switch_observed": source_n > 0,
        "fault_switch_observed": fault_n > 0,
        "static_mode_observed": static_n > 0,
        "daes_mode_observed": daes_n > 0,
    }
    checks = {
        "no_adaptation_during_invalid_gate_or_control": len(unsafe) == 0,
        "covariance_positive_definite": len(bad_cov) == 0,
        "all_control_states_exercised": all(controls.values()),
    }
    summary = {
        "project":"S.P.E.C.T.R.A. / RAD-DAES",
        "classification":"SYNTHETIC_POISSON_HARDWARE_IN_THE_LOOP",
        "samples":len(rows), "adaptations":engine.adaptations, "alarms":engine.alarms,
        "test_stage_counts":dict(counts),
        "firmware_gate_counts":dict(Counter(str(r["firmware_gate"]) for r in rows)),
        "source_on_samples":source_n, "fault_on_samples":fault_n,
        "static_mode_samples":static_n, "daes_mode_samples":daes_n,
        "control_verification":controls, "automated_checks":checks,
        "unsafe_adaptation_rows":len(unsafe), "non_positive_covariance_rows":len(bad_cov),
        "serial_parse_errors":reader.parse_errors, "serial_ignored_lines":reader.ignored_lines,
        "final_mean":np.asarray(engine.mean).tolist(),
        "final_covariance_min_eigenvalue":float(np.linalg.eigvalsh(engine.covariance).min()),
        "note":"Synthetic HIL only; not physical radiation measurement, field validation, or validated FAR."
    }
    json_path = report_path.with_suffix(".json")
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# S.P.E.C.T.R.A. HIL Integration Report","",
        "- Classification: **Synthetic Poisson hardware-in-the-loop**",
        f"- Samples: **{len(rows)}**",f"- Adaptations: **{engine.adaptations}**",
        f"- Alarms: **{engine.alarms}**","","## Hardware control observations","",
        f"- Source ON: {source_n} ({'OBSERVED' if source_n else 'NOT OBSERVED'})",
        f"- Fault ON: {fault_n} ({'OBSERVED' if fault_n else 'NOT OBSERVED'})",
        f"- Static mode: {static_n} ({'OBSERVED' if static_n else 'NOT OBSERVED'})",
        f"- DAES mode: {daes_n} ({'OBSERVED' if daes_n else 'NOT OBSERVED'})",
        "","## Test-stage counts",""
    ]
    lines += [f"- {k}: {v}" for k,v in sorted(counts.items())]
    lines += ["","## Automated checks",""]
    lines += [f"- {k}: **{'PASS' if v else 'NOT PASS'}**" for k,v in checks.items()]
    lines += [
        f"- Unsafe adaptation rows: {len(unsafe)}",
        f"- Non-positive covariance rows: {len(bad_cov)}",
        f"- Serial parse errors: {reader.parse_errors}",
        f"- Ignored serial lines: {reader.ignored_lines}","","## Scientific limitations","",
        summary["note"],
        "A control is verified only when its flag appears in recorded packets.",
        "No false-alarm-rate, detection-accuracy, or physical radiation-performance claim is made."
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n========== INTEGRATION SESSION SUMMARY ==========")
    print("Processed:",engine.processed," Adaptations:",engine.adaptations," Alarms:",engine.alarms)
    print("Source/Fault/Static/DAES samples:",source_n,fault_n,static_n,daes_n)
    print("Firmware gates:",summary["firmware_gate_counts"])
    print("CSV:",csv_path,"\nReport:",report_path,"\nJSON:",json_path)

if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"\nENGINE FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)
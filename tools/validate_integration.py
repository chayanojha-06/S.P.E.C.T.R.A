from pathlib import Path
from types import SimpleNamespace
import sys, numpy as np
ROOT = Path(__file__).resolve().parents[1]
RAD = ROOT.parent / "rad-daes"
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(RAD / "src"))
from communication.protocols.packet_parser import parse_packet
from rad_daes.background.model import BackgroundModel
from spectra_app.engine import SpectraRADEngine

def packet(**updates):
    d = dict(sample=1,timestamp_ms=1000,interval_ms=1000,mode=1,source=0,fault=0,
             firmware_gate=0,firmware_m2=1.0,firmware_eigenvalue=1.0,
             firmware_alpha=0.2,background_level=10.0,
             channels=(27.25,20.9417,12.9,8.85,6.3,4.025),raw="TEST")
    d.update(updates); return SimpleNamespace(**d)

def engine():
    mean=np.array([27.25,20.9417,12.9,8.85,6.3,4.025])
    cov=np.diag([33.3151,21.3663,10.9311,11.8933,5.7748,4.3607])
    return SpectraRADEngine(BackgroundModel(mean,cov),RAD/"configs"/"model.yaml")

def blocked(changes,label):
    e=engine(); m=e.mean.copy(); c=e.covariance.copy()
    r=e.process(packet(**changes))
    assert not r.adaptation_applied, label
    assert np.array_equal(e.mean,m) and np.array_equal(e.covariance,c),label+" mutated model"
    return r

def main():
    p=parse_packet("DATA,1,1000,1000,1,0,0,0,1,1,0.2,10,27,21,13,9,6,4")
    assert p is not None and len(p.channels)==6
    print("[PASS] 18-field packet parser")
    assert not blocked({"firmware_gate":1},"firmware fault").telemetry_valid
    print("[PASS] Firmware FAULT blocks adaptation")
    assert not blocked({"firmware_gate":2},"firmware hold").telemetry_valid
    print("[PASS] Firmware HOLD blocks adaptation")
    assert "SOURCE_INJECTION" in blocked({"source":1},"source").reason
    print("[PASS] Source flag blocks adaptation")
    assert "FAULT_INJECTION" in blocked({"fault":1},"fault").reason
    print("[PASS] Fault flag blocks adaptation")
    assert "STATIC_MODE" in blocked({"mode":0},"static").reason
    print("[PASS] Static mode blocks adaptation")
    assert not blocked({"interval_ms":2000},"timing").telemetry_valid
    print("[PASS] Invalid timing blocks adaptation")
    e=engine(); r=e.process(packet(sample=2))
    assert r.adaptation_allowed and r.adaptation_applied
    assert r.covariance_min_eigenvalue>0 and np.isfinite(r.daes_filtered_lambda)
    print("[PASS] Clean DAES update, diagnostics and positive covariance")
    print("\nALL OFFLINE INTEGRATION CHECKS PASSED.")
    print("Live switch actuation must still be observed on COM4.")
    print("No physical radiation sensor or FAR validation is implied.")

if __name__=="__main__": main()
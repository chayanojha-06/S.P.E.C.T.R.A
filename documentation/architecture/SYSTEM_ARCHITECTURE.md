# S.P.E.C.T.R.A. System Architecture

## 1. System Identity

S.P.E.C.T.R.A. is the overall system.
RAD-DAES is the computational intelligence engine.

## 2. Main Layers

### Computational Layer
RAD-DAES algorithms, adaptive background estimation,
covariance tracking and anomaly scoring.

### Embedded Layer
ESP32 firmware, display, controls, indicators and buzzer.

### Communication Layer
Serial telemetry, commands and structured data exchange.

### Application Layer
Research dashboard, experiment controls and visualization.

### Physical Layer
Enclosure, power system, electronics and detector interface.

## 3. Data Integrity

Synthetic observations and physical detector measurements
must always be identified separately.

## 4. Integration Principle

Existing working implementations must be preserved.
Integration should be incremental and testable.

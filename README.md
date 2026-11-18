# S.P.E.C.T.R.A.

**Streaming Probabilistic Estimation and Change Tracking for Radiation Anomalies**

S.P.E.C.T.R.A. is the main research and hardware-software system.

RAD-DAES is its computational intelligence engine.

## Core Architecture

- RAD-DAES: Adaptive estimation and anomaly detection.
- ESP32: Embedded hardware controller.
- TFT: Local monitoring interface.
- Communication: Serial telemetry and data exchange.
- Dashboard: Experiment monitoring and visualization.
- Hardware: Enclosure, electronics and sensor interfaces.

## Development Rules

1. Preserve the original firmware in firmware/baseline.
2. Perform modifications in firmware/development.
3. Keep integrated builds in firmware/integrated.
4. Do not overwrite existing working implementations.
5. Distinguish synthetic observations from physical sensor readings.
6. Record experiment configurations and results.
7. Validate changes before treating them as research results.

## Current Status

- [x] Project workspace initialized
- [ ] Original ESP32 firmware archived
- [ ] RAD-DAES source integrated
- [ ] Serial communication protocol established
- [ ] Dashboard integration completed
- [ ] Physical detector interface implemented
- [ ] Integrated demonstrator validated

## Hardware

Current firmware targets an ESP32-WROOM-32 DevKit V1
with an ST7735 SPI display.

Refer to hardware/documentation for verified wiring
and component information.

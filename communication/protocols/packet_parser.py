"""Parser for S.P.E.C.T.R.A. ESP32 telemetry packets."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SpectraPacket:
    sample: int
    timestamp_ms: int
    interval_ms: int
    mode: int
    source: int
    fault: int
    firmware_gate: int
    firmware_m2: float
    firmware_eigenvalue: float
    firmware_alpha: float
    background_level: float
    channels: tuple[float, float, float, float, float, float]
    raw: str

    @property
    def timestamp_seconds(self) -> float:
        return self.timestamp_ms / 1000.0

    @property
    def interval_seconds(self) -> float:
        return self.interval_ms / 1000.0


class PacketParseError(ValueError):
    """Raised when a DATA packet is malformed."""


def parse_packet(line: str) -> SpectraPacket | None:
    """Parse one serial line. Return None for non-DATA messages."""

    if not isinstance(line, str):
        raise PacketParseError("Input must be a string")

    raw = line.strip()

    if not raw:
        return None

    fields = [field.strip() for field in raw.split(",")]

    if fields[0] != "DATA":
        return None

    if len(fields) != 18:
        raise PacketParseError(
            f"Expected 18 fields, received {len(fields)}"
        )

    try:
        sample = int(fields[1])
        timestamp_ms = int(fields[2])
        interval_ms = int(fields[3])

        mode = int(fields[4])
        source = int(fields[5])
        fault = int(fields[6])
        firmware_gate = int(fields[7])

        diagnostics = [float(value) for value in fields[8:12]]
        channels = tuple(float(value) for value in fields[12:18])

    except (ValueError, OverflowError) as exc:
        raise PacketParseError(
            f"Invalid numeric field: {exc}"
        ) from exc

    if sample < 0 or timestamp_ms < 0:
        raise PacketParseError("Sample and timestamp must be non-negative")

    if interval_ms <= 0:
        raise PacketParseError("Sampling interval must be positive")

    if mode not in (0, 1):
        raise PacketParseError("Mode must be 0 or 1")

    if source not in (0, 1) or fault not in (0, 1):
        raise PacketParseError("Source and fault flags must be 0 or 1")

    if firmware_gate not in (0, 1, 2):
        raise PacketParseError("Unknown firmware gate status")

    if not all(math.isfinite(value) for value in diagnostics + list(channels)):
        raise PacketParseError("Packet contains non-finite values")

    if any(value < 0 for value in channels):
        raise PacketParseError("Channel observations cannot be negative")

    if diagnostics[0] < 0 or diagnostics[1] < 0:
        raise PacketParseError("Firmware M2/eigenvalue cannot be negative")

    if not 0.0 <= diagnostics[2] <= 1.0:
        raise PacketParseError("Firmware alpha must be between 0 and 1")

    if diagnostics[3] < 0:
        raise PacketParseError("Background level cannot be negative")

    return SpectraPacket(
        sample=sample,
        timestamp_ms=timestamp_ms,
        interval_ms=interval_ms,
        mode=mode,
        source=source,
        fault=fault,
        firmware_gate=firmware_gate,
        firmware_m2=diagnostics[0],
        firmware_eigenvalue=diagnostics[1],
        firmware_alpha=diagnostics[2],
        background_level=diagnostics[3],
        channels=channels,
        raw=raw,
    )

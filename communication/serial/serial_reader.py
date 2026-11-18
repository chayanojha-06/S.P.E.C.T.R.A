"""USB serial reader for the S.P.E.C.T.R.A. ESP32."""

from __future__ import annotations

import time
from collections.abc import Iterator

import serial
from serial import SerialException

from communication.protocols.packet_parser import (
    PacketParseError,
    SpectraPacket,
    parse_packet,
)


class SpectraSerialReader:
    """Read and parse telemetry from an ESP32 serial connection."""

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        timeout: float = 1.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection: serial.Serial | None = None
        self.parse_errors = 0
        self.ignored_lines = 0
        self.received_packets = 0
        self.last_sample: int | None = None
        self.last_timestamp_ms: int | None = None

    @property
    def is_connected(self) -> bool:
        return self.connection is not None and self.connection.is_open

    def connect(self) -> None:
        """Open the serial port."""
        if self.is_connected:
            return

        try:
            self.connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )
            # Allow the ESP32 serial interface to settle after opening.
            time.sleep(1.5)
            self.connection.reset_input_buffer()
            print(
                f"[SPECTRA] Connected to {self.port} "
                f"at {self.baudrate} baud"
            )
        except SerialException as exc:
            self.connection = None
            raise ConnectionError(
                f"Could not open {self.port}. "
                "Close Arduino Serial Monitor and check the USB connection."
            ) from exc

    def read_packet(self) -> SpectraPacket | None:
        """Read one line and return a valid telemetry packet."""
        if not self.is_connected:
            raise ConnectionError("Serial reader is not connected")

        try:
            raw_line = self.connection.readline()

            if not raw_line:
                return None

            line = raw_line.decode("utf-8", errors="replace").strip()

            try:
                packet = parse_packet(line)
            except PacketParseError as exc:
                self.parse_errors += 1
                print(f"[SPECTRA] Rejected packet: {exc}")
                return None

            if packet is None:
                self.ignored_lines += 1
                return None

            if self.last_sample is not None:
                if packet.sample <= self.last_sample:
                    self.parse_errors += 1
                    print("[SPECTRA] Rejected non-increasing sample counter")
                    return None

            if self.last_timestamp_ms is not None:
                if packet.timestamp_ms <= self.last_timestamp_ms:
                    self.parse_errors += 1
                    print("[SPECTRA] Rejected non-increasing timestamp")
                    return None

            self.last_sample = packet.sample
            self.last_timestamp_ms = packet.timestamp_ms
            self.received_packets += 1

            return packet

        except SerialException as exc:
            raise ConnectionError(
                f"Serial communication with {self.port} failed"
            ) from exc

    def stream(self) -> Iterator[SpectraPacket]:
        """Yield valid packets continuously until interrupted."""
        if not self.is_connected:
            self.connect()

        while self.is_connected:
            packet = self.read_packet()
            if packet is not None:
                yield packet

    def close(self) -> None:
        """Close the serial connection safely."""
        if self.connection is not None:
            if self.connection.is_open:
                self.connection.close()

            self.connection = None
            print(f"[SPECTRA] Disconnected from {self.port}")

    def __enter__(self) -> "SpectraSerialReader":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

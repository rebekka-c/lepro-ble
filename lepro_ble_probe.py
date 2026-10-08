#!/usr/bin/env python3
"""Read-only BLE probe for Lepro smart bulbs (e.g. B3).

What it does:
  1. Scans and logs every advertisement from candidate devices (name, RSSI,
     service UUIDs, manufacturer data, service data).
  2. Optionally connects to one device, dumps its GATT table, reads readable
     characteristics and subscribes to every notify/indicate characteristic.
  3. Tags notifications that look like Lepro framing (0x5A header + CRC-16/ARC),
     as described in public reverse-engineering notes for Lepro ZB1 lights.

What it never does:
  - Write to any characteristic or descriptor (beyond the CCCD subscribe that
    bleak performs for start_notify).
  - Call pair(), decrypt payloads, or send undocumented commands.

Caveats:
  - If a characteristic demands an encrypted link, the OS Bluetooth stack (not
    this script) may start pairing on read/subscribe. Decline any pairing prompt,
    or use --no-read --no-subscribe for a pure GATT-table dump.
  - Most bulbs accept one central at a time and stop advertising while a phone is
    connected. Close the Lepro app (or turn off phone Bluetooth) before probing,
    and trigger state changes via the cloud/voice assistant or wall switch.

Output: human-readable log on stderr + one JSON object per event in a JSONL file.

Usage:
  pip install "bleak>=0.22"
  python lepro_ble_probe.py --ads-only --scan-seconds 60
  python lepro_ble_probe.py --listen-seconds 120
  python lepro_ble_probe.py --address AA:BB:CC:DD:EE:FF --no-read
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

# Custom GATT service seen on Lepro ZB1 string lights (public, unverified on B3).
LEPRO_SERVICE_UUID = "1e2aa501-7292-4263-a8f1-be907f039a1f"
LEPRO_CMD_UUID = "1e2aa502-7292-4263-a8f1-be907f039a1f"
LEPRO_RSP_UUID = "1e2aa503-7292-4263-a8f1-be907f039a1f"

# Bluetooth SIG Mesh services. Their presence would indicate Bluetooth Mesh.
MESH_PROVISIONING_UUID = "00001827-0000-1000-8000-00805f9b34fb"
MESH_PROXY_UUID = "00001828-0000-1000-8000-00805f9b34fb"

DEFAULT_NAME_PREFIXES = ("LP", "LEPRO")
GATT_OP_TIMEOUT = 10.0  # seconds per read/subscribe, so a pending OS pairing prompt cannot hang the probe
FRAME_HEADER_LEN = 10
FRAME_SYNC = 0x5A

# Opcode labels from public notes (hardware/lepro in nickyblackburn/CYNX-AI).
KNOWN_OPCODES = {
    0x1000: "searchDeviceInfo",
    0x1001: "deviceInfoResponse",
    0x1002: "requestBond",
    0x1003: "bondResponse",
    0x1008: "wifiMqttInfo",
    0x1009: "wifiMqttInfoResponse",
    0x100B: "wifiProgress",
    0x1100: "dpValue",
    0x1101: "dpValueAck",
    0x1102: "getDpState",
    0x1103: "dpResponse",
    0x2000: "certConfig",
}

FRAME_KINDS = {
    0x50: "single",
    0x51: "fragment-first",
    0x52: "fragment-middle",
    0x53: "fragment-last",
    0x54: "single-encrypted",
    0xD1: "fragment-first-encrypted",
    0xD2: "fragment-middle-encrypted",
}

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")
UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}$")

log = logging.getLogger("lepro_probe")


# ── Pure helpers (unit-tested) ───────────────────────────────────────────────


def crc16_arc(data: bytes) -> int:
    """CRC-16/ARC (poly 0xA001 reflected, init 0)."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def describe_frame(data: bytes) -> dict[str, Any] | None:
    """Return header fields if data looks like a Lepro frame, else None.

    Layout: crc16(2, BE, over bytes[2:]) | 0x5A | kind | seq(2) | opcode(2) | len(2) | payload
    The payload is not decoded; it is usually encrypted.
    """
    if len(data) < FRAME_HEADER_LEN or data[2] != FRAME_SYNC:
        return None
    stored_crc = int.from_bytes(data[0:2], "big")
    kind = data[3]
    opcode = int.from_bytes(data[6:8], "big")
    declared_len = int.from_bytes(data[8:10], "big")
    payload_len = len(data) - FRAME_HEADER_LEN
    return {
        "crc_ok": stored_crc == crc16_arc(data[2:]),
        "kind": FRAME_KINDS.get(kind, f"unknown-0x{kind:02x}"),
        "seq": int.from_bytes(data[4:6], "big"),
        "opcode": f"0x{opcode:04x}",
        "opcode_name": KNOWN_OPCODES.get(opcode, "unknown"),
        "declared_len": declared_len,
        "payload_len": payload_len,
        "payload_multiple_of_16": payload_len > 0 and payload_len % 16 == 0,
    }


def is_candidate(name: str | None, service_uuids: list[str], prefixes: tuple[str, ...]) -> bool:
    """True if the advert looks like a Lepro device."""
    uuids = {u.lower() for u in service_uuids}
    if LEPRO_SERVICE_UUID in uuids:
        return True
    if not name:
        return False
    upper = name.upper()
    return any(upper.startswith(p) for p in prefixes) or "LEPRO" in upper


def advert_record(address: str, name: str | None, rssi: int | None, adv: Any) -> dict[str, Any]:
    """Build a JSON-safe record from a bleak AdvertisementData-like object."""
    uuids = [u.lower() for u in (adv.service_uuids or [])]
    return {
        "event": "advert",
        "address": address,
        "name": name,
        "rssi": rssi,
        "tx_power": getattr(adv, "tx_power", None),
        "service_uuids": uuids,
        "manufacturer_data": {str(k): bytes(v).hex() for k, v in (adv.manufacturer_data or {}).items()},
        "service_data": {k: bytes(v).hex() for k, v in (adv.service_data or {}).items()},
        "has_lepro_service": LEPRO_SERVICE_UUID in uuids,
        "has_mesh_service": bool({MESH_PROVISIONING_UUID, MESH_PROXY_UUID} & set(uuids)),
    }


# ── Event log ────────────────────────────────────────────────────────────────


@dataclass
class EventLog:
    """Append-only JSONL sink. Late writes (e.g. from BLE callbacks after shutdown) are dropped."""

    stream: TextIO

    def write(self, record: dict[str, Any]) -> None:
        if self.stream.closed:
            return
        stamped = {"ts": round(time.time(), 3), **record}
        self.stream.write(json.dumps(stamped) + "\n")
        self.stream.flush()


# ── Scanning ─────────────────────────────────────────────────────────────────


@dataclass
class ScanResult:
    best: dict[str, tuple[int, Any]] = field(default_factory=dict)  # address -> (rssi, BLEDevice)
    last_payload: dict[str, str] = field(default_factory=dict)


async def scan(args: argparse.Namespace, events: EventLog) -> ScanResult:
    """Scan for scan_seconds, logging adverts whose payload changed."""
    from bleak import BleakScanner

    result = ScanResult()
    prefixes = tuple(p.upper() for p in args.name_prefix)
    target = args.address.upper() if args.address else None

    def on_advert(device: Any, adv: Any) -> None:
        name = adv.local_name or device.name
        address = device.address.upper()
        connectable = address == target if target else is_candidate(name, adv.service_uuids or [], prefixes)
        if not (connectable or args.all):
            return
        record = advert_record(address, name, adv.rssi, adv)
        fingerprint = json.dumps({k: record[k] for k in ("name", "service_uuids", "manufacturer_data", "service_data")})
        if result.last_payload.get(address) != fingerprint:
            log.info("ADV %s %-20s rssi=%s uuids=%s mfr=%s", address, name, adv.rssi,
                     record["service_uuids"], record["manufacturer_data"])
            events.write(record)
            result.last_payload[address] = fingerprint
        if not connectable:  # --all logs everything but only candidates may be connected to
            return
        previous = result.best.get(address)
        if previous is None or (adv.rssi or -999) > previous[0]:
            result.best[address] = (adv.rssi or -999, device)

    log.info("Scanning for %.0f s (Ctrl+C to stop early)...", args.scan_seconds)
    async with BleakScanner(detection_callback=on_advert):
        await asyncio.sleep(args.scan_seconds)
    return result


def pick_target(result: ScanResult, address: str | None) -> Any | None:
    """Return the BLEDevice to connect to: the requested address or the strongest candidate."""
    if address:
        entry = result.best.get(address.upper())
        return entry[1] if entry else None
    if not result.best:
        return None
    return max(result.best.values(), key=lambda item: item[0])[1]


# ── GATT inspection ──────────────────────────────────────────────────────────


async def dump_gatt(client: Any, events: EventLog, do_read: bool) -> list[Any]:
    """Log services/characteristics/descriptors; return notifiable characteristics."""
    notifiable = []
    for service in client.services:
        log.info("SERVICE %s (%s)", service.uuid, service.description)
        events.write({"event": "service", "uuid": service.uuid, "description": service.description})
        if service.uuid.lower() in (MESH_PROVISIONING_UUID, MESH_PROXY_UUID):
            log.warning("  Bluetooth Mesh service present: %s", service.uuid)
        for char in service.characteristics:
            await _log_characteristic(client, char, events, do_read)
            if {"notify", "indicate"} & set(char.properties):
                notifiable.append(char)
    return notifiable


async def _log_characteristic(client: Any, char: Any, events: EventLog, do_read: bool) -> None:
    record: dict[str, Any] = {
        "event": "characteristic",
        "service": char.service_uuid,
        "uuid": char.uuid,
        "handle": char.handle,
        "properties": list(char.properties),
        "descriptors": [d.uuid for d in char.descriptors],
    }
    if do_read and "read" in char.properties:
        try:
            value = bytes(await asyncio.wait_for(client.read_gatt_char(char), GATT_OP_TIMEOUT))
            record["value_hex"] = value.hex()
            record["value_ascii"] = value.decode("ascii", errors="replace")
        except Exception as exc:  # noqa: BLE001 - report every read failure, keep probing
            record["read_error"] = f"{type(exc).__name__}: {exc}"
    log.info("  CHAR %s handle=%s props=%s %s", char.uuid, char.handle, ",".join(char.properties),
             record.get("value_hex", record.get("read_error", "")))
    events.write(record)


def make_notify_handler(events: EventLog, char_uuid: str):
    """Build a notification callback that logs raw bytes and any frame header."""

    def handler(_sender: Any, data: bytearray) -> None:
        raw = bytes(data)
        frame = describe_frame(raw)
        log.info("NOTIFY %s len=%d %s %s", char_uuid, len(raw), raw.hex(), frame or "")
        events.write({"event": "notify", "uuid": char_uuid, "hex": raw.hex(), "frame": frame})

    return handler


async def probe_device(device: Any, args: argparse.Namespace, events: EventLog) -> None:
    """Connect, dump GATT, subscribe to notifications and listen."""
    from bleak import BleakClient

    disconnected = asyncio.Event()
    closing = False

    def on_disconnect(_client: Any) -> None:
        if closing:  # our own clean disconnect at the end of the run
            return
        log.warning("Device disconnected")
        events.write({"event": "disconnected", "address": device.address})
        disconnected.set()

    log.info("Connecting to %s (%s)...", device.address, device.name)
    async with BleakClient(device, disconnected_callback=on_disconnect, timeout=args.connect_timeout) as client:
        events.write({"event": "connected", "address": device.address})
        notifiable = await dump_gatt(client, events, do_read=not args.no_read)
        if not args.no_subscribe:
            await subscribe_all(client, notifiable, events)
        log.info("Listening for %.0f s. Change the bulb via cloud/voice/wall switch now.", args.listen_seconds)
        try:
            await asyncio.wait_for(disconnected.wait(), timeout=args.listen_seconds)
        except asyncio.TimeoutError:
            log.info("Listen window finished")
        closing = True


async def subscribe_all(client: Any, chars: list[Any], events: EventLog) -> None:
    """Subscribe to each notify/indicate characteristic; failures are logged, not fatal."""
    for char in chars:
        try:
            await asyncio.wait_for(client.start_notify(char, make_notify_handler(events, char.uuid)), GATT_OP_TIMEOUT)
            log.info("Subscribed to %s", char.uuid)
        except Exception as exc:  # noqa: BLE001 - some chars need bonding; log and continue
            log.warning("Could not subscribe to %s: %s", char.uuid, exc)
            events.write({"event": "subscribe_error", "uuid": char.uuid, "error": f"{type(exc).__name__}: {exc}"})


# ── CLI ──────────────────────────────────────────────────────────────────────


def positive_float(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return value


def mac_address(text: str) -> str:
    # Windows/Linux use MACs; macOS uses CoreBluetooth UUIDs, so accept both.
    if not (MAC_RE.match(text) or UUID_RE.match(text)):
        raise argparse.ArgumentTypeError(f"not a MAC address or CoreBluetooth UUID: {text!r}")
    return text.replace("-", ":").upper() if MAC_RE.match(text) else text.upper()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only BLE probe for Lepro bulbs")
    parser.add_argument("--address", type=mac_address, help="connect to this device only")
    parser.add_argument("--name-prefix", nargs="+", default=list(DEFAULT_NAME_PREFIXES),
                        help="advertised-name prefixes treated as candidates (default: LP LEPRO)")
    parser.add_argument("--all", action="store_true",
                        help="also log adverts from non-candidate devices (never connects to them)")
    parser.add_argument("--ads-only", action="store_true", help="scan and log adverts only; never connect")
    parser.add_argument("--no-read", action="store_true", help="do not read characteristic values")
    parser.add_argument("--no-subscribe", action="store_true", help="do not subscribe to notifications")
    parser.add_argument("--scan-seconds", type=positive_float, default=15.0)
    parser.add_argument("--listen-seconds", type=positive_float, default=60.0)
    parser.add_argument("--connect-timeout", type=positive_float, default=20.0)
    parser.add_argument("--log-file", type=Path, default=Path(f"lepro_probe_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"))
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    try:
        stream = args.log_file.open("a", encoding="utf-8")
    except OSError as exc:
        log.error("Cannot open log file %s: %s", args.log_file, exc)
        return 4
    with stream:
        events = EventLog(stream)
        events.write({"event": "start", "args": {k: str(v) for k, v in vars(args).items()}})
        try:
            code = await scan_and_probe(args, events)
        except Exception as exc:  # noqa: BLE001 - top-level: adapter off, permissions, connect errors
            log.error("Probe failed: %s: %s", type(exc).__name__, exc)
            events.write({"event": "error", "error": f"{type(exc).__name__}: {exc}"})
            code = 1
    log.info("Log written to %s", args.log_file.resolve())
    return code


async def scan_and_probe(args: argparse.Namespace, events: EventLog) -> int:
    result = await scan(args, events)
    if args.ads_only:
        log.info("Done. %d candidate device(s).", len(result.best))
        return 0
    device = pick_target(result, args.address)
    if device is None:
        log.error("No candidate device found. The bulb may be connected to a phone (close the Lepro app), "
                  "or try --all with --ads-only to see what is advertising, a longer --scan-seconds, or move closer.")
        return 2
    await probe_device(device, args, events)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", stream=sys.stderr)
    try:
        import bleak  # noqa: F401
    except ImportError:
        log.error('bleak is not installed. Run: pip install "bleak>=0.22"')
        return 3
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        log.info("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())

"""Tests for lepro_ble_probe. Bluetooth is replaced with fakes, so no adapter is needed."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
from types import SimpleNamespace
from typing import ClassVar

import pytest

import lepro_ble_probe as probe

# Frame published in nickyblackburn/CYNX-AI hardware/lepro/lib/lepro/protocol.py
PUBLIC_HELLO = bytes.fromhex(
    "8a015a50000010000020c4012a79a0dd031c727eea6cf7c736dc45a764086a2bd4ce293aea2f0264a166"
)


def build_frame(kind: int, seq: int, opcode: int, payload: bytes) -> bytes:
    body = bytes([0x5A, kind]) + seq.to_bytes(2, "big") + opcode.to_bytes(2, "big")
    body += len(payload).to_bytes(2, "big") + payload
    return probe.crc16_arc(body).to_bytes(2, "big") + body


def test_crc16_arc_check_value():
    assert probe.crc16_arc(b"123456789") == 0xBB3D


def test_describe_frame_matches_public_capture():
    frame = probe.describe_frame(PUBLIC_HELLO)
    assert frame["crc_ok"] is True
    assert frame["opcode"] == "0x1000"
    assert frame["opcode_name"] == "searchDeviceInfo"
    assert frame["kind"] == "single"
    assert frame["declared_len"] == frame["payload_len"] == 32


def test_describe_frame_detects_bad_crc():
    corrupted = bytes([PUBLIC_HELLO[0] ^ 0xFF]) + PUBLIC_HELLO[1:]
    assert probe.describe_frame(corrupted)["crc_ok"] is False


def test_describe_frame_synthetic_dp_response():
    frame = probe.describe_frame(build_frame(0x54, 7, 0x1103, bytes(16)))
    assert frame["crc_ok"] and frame["seq"] == 7
    assert frame["opcode_name"] == "dpResponse"
    assert frame["kind"] == "single-encrypted"
    assert frame["payload_multiple_of_16"] is True


def test_describe_frame_unknown_values():
    frame = probe.describe_frame(build_frame(0x99, 0, 0xBEEF, b""))
    assert frame["kind"] == "unknown-0x99"
    assert frame["opcode_name"] == "unknown"
    assert frame["payload_multiple_of_16"] is False


@pytest.mark.parametrize("data", [b"", b"\x00" * 9, b"\x00\x00\x00" + b"\x00" * 10])
def test_describe_frame_rejects_non_frames(data):
    assert probe.describe_frame(data) is None


@pytest.mark.parametrize(
    ("name", "uuids", "expected"),
    [
        ("LP", [], True),
        ("lp-b3", [], True),
        ("My Lepro Bulb", [], True),
        (None, [probe.LEPRO_SERVICE_UUID.upper()], True),
        ("Govee", [], False),
        (None, [], False),
    ],
)
def test_is_candidate(name, uuids, expected):
    assert probe.is_candidate(name, uuids, ("LP", "LEPRO")) is expected


def test_advert_record_flags_services():
    adv = SimpleNamespace(
        service_uuids=[probe.LEPRO_SERVICE_UUID, probe.MESH_PROXY_UUID],
        manufacturer_data={0x02E5: b"\x01\x02"},
        service_data={probe.MESH_PROXY_UUID: b"\xff"},
        tx_power=None,
    )
    record = probe.advert_record("AA:BB:CC:DD:EE:FF", "LP", -60, adv)
    assert record["has_lepro_service"] and record["has_mesh_service"]
    assert record["manufacturer_data"] == {"741": "0102"}
    json.dumps(record)  # must be JSON-serialisable


def test_event_log_writes_jsonl():
    stream = io.StringIO()
    probe.EventLog(stream).write({"event": "x"})
    line = json.loads(stream.getvalue())
    assert line["event"] == "x" and "ts" in line


def test_pick_target_prefers_strongest_or_requested():
    result = probe.ScanResult(best={"A": (-80, "dev-a"), "B": (-50, "dev-b")})
    assert probe.pick_target(result, None) == "dev-b"
    assert probe.pick_target(result, "a") == "dev-a"
    assert probe.pick_target(result, "C") is None
    assert probe.pick_target(probe.ScanResult(), None) is None


def test_parse_args_validation():
    args = probe.parse_args(["--address", "aa-bb-cc-dd-ee-ff", "--scan-seconds", "5"])
    assert args.address == "AA:BB:CC:DD:EE:FF" and args.scan_seconds == 5.0
    with pytest.raises(SystemExit):
        probe.parse_args(["--address", "not-a-mac"])
    with pytest.raises(SystemExit):
        probe.parse_args(["--scan-seconds", "0"])


def test_mac_address_accepts_corebluetooth_uuid():
    uuid = "12345678-1234-1234-1234-1234567890ab"
    assert probe.mac_address(uuid) == uuid.upper()
    with pytest.raises(argparse.ArgumentTypeError):
        probe.mac_address("12:34")


# ── I/O paths with fake bleak objects ────────────────────────────────────────


class FakeChar:
    def __init__(self, uuid, props, handle=1):
        self.uuid, self.properties, self.handle = uuid, props, handle
        self.service_uuid, self.descriptors = probe.LEPRO_SERVICE_UUID, []


class FakeClient:
    """Stands in for BleakClient; records calls, never touches Bluetooth."""

    def __init__(self, device, disconnected_callback=None, timeout=None):
        notify = FakeChar(probe.LEPRO_RSP_UUID, ["notify"], 3)
        readable = FakeChar("00002a29-0000-1000-8000-00805f9b34fb", ["read"], 5)
        broken = FakeChar("00002a24-0000-1000-8000-00805f9b34fb", ["read", "indicate"], 7)
        self.services = [
            SimpleNamespace(uuid=probe.LEPRO_SERVICE_UUID, description="Lepro", characteristics=[notify]),
            SimpleNamespace(uuid=probe.MESH_PROXY_UUID, description="Mesh", characteristics=[readable, broken]),
        ]
        self.subscribed, self.mtu_size, self.writes = [], 23, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read_gatt_char(self, char):
        if char.handle == 7:
            raise OSError("read not permitted")
        return bytearray(b"Lepro")

    async def start_notify(self, char, handler):
        if char.handle == 7:
            raise OSError("needs bonding")
        self.subscribed.append(char.uuid)
        handler(None, bytearray(PUBLIC_HELLO))

    # Traps: any write or pairing attempt is recorded and must never happen.
    async def write_gatt_char(self, *args, **kwargs):
        self.writes.append(("write_gatt_char", args))

    async def write_gatt_descriptor(self, *args, **kwargs):
        self.writes.append(("write_gatt_descriptor", args))

    async def pair(self, *args, **kwargs):
        self.writes.append(("pair", args))


def make_args(**overrides):
    base = {"address": None, "name_prefix": ["LP"], "all": False, "ads_only": False, "no_read": False,
            "no_subscribe": False, "scan_seconds": 0.01, "listen_seconds": 0.01, "connect_timeout": 1.0}
    return argparse.Namespace(**{**base, **overrides})


def read_events(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_dump_gatt_reads_and_reports_errors():
    stream = io.StringIO()
    client = FakeClient(None)
    notifiable = asyncio.run(probe.dump_gatt(client, probe.EventLog(stream), do_read=True))
    assert [c.handle for c in notifiable] == [3, 7]
    chars = [e for e in read_events(stream) if e["event"] == "characteristic"]
    assert chars[1]["value_hex"] == b"Lepro".hex()
    assert "OSError" in chars[2]["read_error"]


def test_notify_handler_logs_frame():
    stream = io.StringIO()
    probe.make_notify_handler(probe.EventLog(stream), "x")(None, bytearray(PUBLIC_HELLO))
    event = read_events(stream)[0]
    assert event["frame"]["opcode_name"] == "searchDeviceInfo"


def test_probe_device_subscribes_and_never_writes(monkeypatch):
    import bleak

    created = []
    monkeypatch.setattr(bleak, "BleakClient", lambda *a, **k: created.append(FakeClient(*a, **k)) or created[-1])
    stream = io.StringIO()
    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="LP")
    asyncio.run(probe.probe_device(device, make_args(), probe.EventLog(stream)))
    kinds = [e["event"] for e in read_events(stream)]
    assert created[0].subscribed == [probe.LEPRO_RSP_UUID]
    assert created[0].writes == []
    assert {"connected", "notify", "subscribe_error"} <= set(kinds)


class FakeScanner:
    adverts: ClassVar[list] = []

    def __init__(self, detection_callback):
        self.callback = detection_callback

    async def __aenter__(self):
        for device, adv in self.adverts:
            self.callback(device, adv)
        return self

    async def __aexit__(self, *exc):
        return False


def fake_advert(name, rssi, uuids=()):
    return SimpleNamespace(local_name=name, rssi=rssi, service_uuids=list(uuids),
                           manufacturer_data={}, service_data={}, tx_power=None)


def test_scan_filters_dedupes_and_tracks_best(monkeypatch):
    import bleak

    lp = SimpleNamespace(address="aa:bb:cc:dd:ee:01", name=None)
    other = SimpleNamespace(address="aa:bb:cc:dd:ee:02", name=None)
    FakeScanner.adverts = [(lp, fake_advert("LP", -70)), (lp, fake_advert("LP", -60)),
                           (other, fake_advert("Govee", -40))]
    monkeypatch.setattr(bleak, "BleakScanner", FakeScanner)
    stream = io.StringIO()
    result = asyncio.run(probe.scan(make_args(), probe.EventLog(stream)))
    assert list(result.best) == ["AA:BB:CC:DD:EE:01"]
    assert result.best["AA:BB:CC:DD:EE:01"][0] == -60
    assert len(read_events(stream)) == 1  # identical payload logged once


def test_run_paths(monkeypatch, tmp_path):
    async def fake_scan(args, events):
        return probe.ScanResult(best={"A": (-50, "dev")}) if args.address != "NONE" else probe.ScanResult()

    probed = []

    async def fake_probe(device, args, events):
        if args.listen_seconds == 99:
            raise TimeoutError("connect timed out")
        probed.append(device)

    monkeypatch.setattr(probe, "scan", fake_scan)
    monkeypatch.setattr(probe, "probe_device", fake_probe)
    log_file = tmp_path / "out.jsonl"
    assert asyncio.run(probe.run(make_args(log_file=log_file, ads_only=True))) == 0
    assert asyncio.run(probe.run(make_args(log_file=log_file))) == 0 and probed == ["dev"]
    assert asyncio.run(probe.run(make_args(log_file=log_file, address="NONE"))) == 2
    assert asyncio.run(probe.run(make_args(log_file=log_file, listen_seconds=99))) == 1
    assert "connect timed out" in log_file.read_text()


def test_main_runs_with_patched_run(monkeypatch, tmp_path):
    async def fake_run(args):
        return 0

    monkeypatch.setattr(probe, "run", fake_run)
    assert probe.main(["--ads-only", "--log-file", str(tmp_path / "x.jsonl")]) == 0


def test_source_never_calls_write_or_pair():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(probe.__file__).read_text(encoding="utf-8"))
    forbidden = {"write_gatt_char", "write_gatt_descriptor", "pair", "unpair"}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & forbidden
    pair_kwargs = [k for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords if k.arg == "pair"]
    assert pair_kwargs == []


def test_scan_all_logs_everything_but_never_targets_non_candidates(monkeypatch):
    import bleak

    other = SimpleNamespace(address="aa:bb:cc:dd:ee:02", name=None)
    FakeScanner.adverts = [(other, fake_advert("Phone", -30))]
    monkeypatch.setattr(bleak, "BleakScanner", FakeScanner)
    stream = io.StringIO()
    result = asyncio.run(probe.scan(make_args(all=True), probe.EventLog(stream)))
    assert result.best == {}
    assert read_events(stream)[0]["name"] == "Phone"


def test_probe_device_no_subscribe(monkeypatch):
    import bleak

    created = []
    monkeypatch.setattr(bleak, "BleakClient", lambda *a, **k: created.append(FakeClient(*a, **k)) or created[-1])
    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="LP")
    asyncio.run(probe.probe_device(device, make_args(no_subscribe=True), probe.EventLog(io.StringIO())))
    assert created[0].subscribed == [] and created[0].writes == []


def test_run_reports_scan_failure_and_bad_log_path(monkeypatch, tmp_path):
    async def failing_scan(args, events):
        raise OSError("Bluetooth adapter is off")

    monkeypatch.setattr(probe, "scan", failing_scan)
    log_file = tmp_path / "out.jsonl"
    assert asyncio.run(probe.run(make_args(log_file=log_file))) == 1
    assert "adapter is off" in log_file.read_text()
    assert asyncio.run(probe.run(make_args(log_file=tmp_path / "missing" / "x.jsonl"))) == 4


def test_event_log_ignores_writes_after_close():
    stream = io.StringIO()
    events = probe.EventLog(stream)
    stream.close()
    events.write({"event": "late"})  # must not raise

# lepro-ble

Research into **local Bluetooth LE control of Lepro B3 smart bulbs** from Home Assistant, plus a **read-only BLE probe** for gathering evidence from bulbs you own.

> Not affiliated with or endorsed by Lepro. Lepro names are trademarks of their respective owners.

## Status

**Research and evidence gathering. There is no working integration yet.**

| Question | Current answer |
|---|---|
| Does the B3 have Bluetooth LE? | **Yes.** FCC ID [2A3MAB3](https://fccid.io/2A3MAB3) certifies a 2402–2480 MHz BLE radio alongside Wi-Fi. |
| Does the Lepro app control lights over BLE, or only use it for setup? | The app's native library has BLE set/get/report functions (per public third-party analysis). **Not yet confirmed on a B3.** |
| Protocol type | Proprietary point-to-point **GATT** with framed, app-encrypted payloads, as reported for Lepro ZB1 lights. **Not** Bluetooth Mesh, **not** advertisement-based. |
| Existing Home Assistant integrations | Cloud only ([Lepro Cloud](https://github.com/Wheemer/lepro-cloud), [Lepro LED](https://github.com/Sanji78/lepro_led)). |
| Good for whole-house lighting? | No. BLE connection-slot limits make Zigbee a better choice at scale. |

The full write-up covers evidence and sources, architecture, proxies vs mesh, scaling, alternatives, an integration design and a PoC plan. It is in **[lepro-b3-ble-feasibility.md](lepro-b3-ble-feasibility.md)**.

## The probe

[`lepro_ble_probe.py`](lepro_ble_probe.py) scans for Lepro devices and logs:

- **advertisements:** name, RSSI, service UUIDs, manufacturer and service data, and whether Bluetooth Mesh services are present;
- **the GATT table:** services, characteristics, properties, descriptors and readable values;
- **notifications:** raw bytes, plus a decoded frame header (sequence, opcode, CRC check) when the data matches the reported Lepro framing.

Everything is written to a JSONL file for later analysis.

### Safety

- **It never writes** to characteristics or descriptors. The only exception is the standard notification subscription (CCCD) made by `start_notify`, which `--no-subscribe` disables.
- **It never calls `pair()`**, never decrypts payloads and never sends commands.
- It only connects to devices that look like Lepro bulbs or to the `--address` you give. `--all` widens logging only.
- If a characteristic requires an encrypted link, your **operating system** may offer to pair when the probe reads or subscribes. Decline the prompt, or use `--no-read --no-subscribe`.
- The tests enforce the no-write rule with write/pair traps on a fake client and a static check of the source.

### Requirements

- Python 3.10+ (tested on 3.13)
- [`bleak`](https://github.com/hbldh/bleak) 0.22 or newer
- A Bluetooth adapter on Windows, Linux (BlueZ) or macOS

```bash
pip install "bleak>=0.22"
```

### Usage

Close the Lepro app first, or turn off Bluetooth on your phone. Most bulbs accept one connection at a time and stop advertising while connected.

Log advertisements only, without connecting:

```bash
python lepro_ble_probe.py --ads-only --scan-seconds 120
```

Connect to the strongest Lepro candidate, dump GATT and listen for notifications:

```bash
python lepro_ble_probe.py --listen-seconds 120
```

Target one bulb and dump the GATT table only, with no reads or subscriptions:

```bash
python lepro_ble_probe.py --address AA:BB:CC:DD:EE:FF --no-read --no-subscribe
```

While it listens, change the bulb through the cloud, a voice assistant or the wall switch, then check the log for notifications.

| Option | Default | Purpose |
|---|---|---|
| `--address` | — | Probe only this MAC (or CoreBluetooth UUID on macOS) |
| `--name-prefix` | `LP LEPRO` | Advertised-name prefixes treated as candidates |
| `--all` | off | Also log adverts from non-candidate devices |
| `--ads-only` | off | Scan and log adverts, never connect |
| `--no-read` | off | Don't read characteristic values |
| `--no-subscribe` | off | Don't subscribe to notifications |
| `--scan-seconds` | 15 | Scan duration |
| `--listen-seconds` | 60 | How long to stay connected listening |
| `--connect-timeout` | 20 | Connection timeout in seconds |
| `--log-file` | `lepro_probe_<timestamp>.jsonl` | JSONL output path |
| `-v` | off | Debug logging |

Exit codes: `0` success · `1` probe or adapter error · `2` no candidate found · `3` bleak missing · `4` cannot open log file · `130` interrupted (Ctrl+C).

> **Privacy:** logs contain your devices' MAC addresses. `*.jsonl` is git-ignored, so don't commit logs or attach them publicly without redacting them.

**Running on Home Assistant hardware:** if HA is running on the same machine, its Bluetooth integration owns the adapter. Run the probe from a laptop, or temporarily disable HA's Bluetooth integration.

## Suggested next steps

The full hardware test plan, with results tables, is in **[TESTING.md](TESTING.md)**. In short:

1. **Airplane-mode test.** Put the phone in airplane mode, turn Bluetooth back on, and see whether the Lepro app still controls the bulb.
2. **Internet-block test.** Block the bulb's internet access at the router and see whether the app still works nearby.
3. Run the probe with `--ads-only`, then in connect mode.
4. Capture an Android HCI snoop log while using the app and compare the frames with the reported format.

If your results confirm or refute the reported protocol on a B3, opening an issue is welcome.

## Development

```bash
pip install pytest pytest-cov ruff "bleak>=0.22"
pytest --cov=lepro_ble_probe --cov-report=term-missing
ruff check .
```

The tests replace Bluetooth with fakes, so no adapter is needed (30 tests, 95% coverage).

## Scope and ethics

This project aims at **interoperability with devices you own**. It does not include key material, decryption code, firmware patching or anything that bypasses security controls. Decompiling or reimplementing a vendor protocol is permitted only in narrow circumstances (for example UK CDPA s.50B, EU Software Directive art. 6), and app terms may restrict it further. Check what applies to you. Nothing here is legal advice.

## Sources

The main sources are listed in the [evidence table](lepro-b3-ble-feasibility.md#2-evidence-table). The protocol details come mostly from one third-party hobby project ([nickyblackburn/CYNX-AI `hardware/lepro`](https://github.com/nickyblackburn/CYNX-AI/tree/main/hardware/lepro)) that targets Lepro ZB1 string lights. Treat them as unverified for the B3.

# Test plan: Lepro B3 (BLE) vs Lepro cloud vs Zigbee

How to test once the hardware arrives. Each step has a pass/fail gate and a results table to fill in.

There are three tracks:

- **A — Can the B3 be controlled locally over Bluetooth LE?** This decides whether a local integration is worth building.
- **B — Zigbee baseline** using a SONOFF ZBDongle-E with Zigbee2MQTT.
- **C — Side-by-side comparison** in Home Assistant: Lepro cloud vs Zigbee (and BLE-local, if Track A passes).

Background and sources are in [lepro-b3-ble-feasibility.md](lepro-b3-ble-feasibility.md). Probe usage is in the [README](README.md).

---

## Test environment

| Item | Setup |
|---|---|
| Home Assistant | HA Container in Docker Desktop on a Windows PC (temporary). Later HA OS on a Pi or home server |
| MQTT | Mosquitto in Docker |
| Zigbee | ZBDongle-E with Zigbee2MQTT running natively on Windows (COM port, no USB passthrough into Docker) |
| BLE probing | `lepro_ble_probe.py` run **directly on Windows**. HA in Docker on Windows can't use the PC's Bluetooth |
| Phone | Android preferred (needed for HCI snoop in step A4) |

**Record before starting:**

| Field | Value |
|---|---|
| Date | |
| Lepro app version | |
| B3 firmware version (from app) | |
| B3 model on label (e.g. B3-UK) | |
| Home Wi-Fi 2.4 GHz channel | |
| Zigbee channel (Zigbee2MQTT config) | |
| Zigbee bulb model(s) | |

---

## Track A: B3 local Bluetooth

### A0. Before setup (factory state), 5 min

Power one B3 **before** adding it in the Lepro app.

```bash
python lepro_ble_probe.py --ads-only --scan-seconds 60 --log-file b3_unprovisioned.jsonl
```

Pass: a device advertising a name like `LP…` appears.

| Result | Value |
|---|---|
| Advertised name | |
| Service UUIDs in advert | |
| Manufacturer data (hex) | |
| `has_lepro_service` | |
| `has_mesh_service` | |

### A1. Normal setup

Add the bulb in the Lepro app over Wi-Fi as usual. Note its firmware version in the environment table above.

### A2. Zero-code tests, 10 min

1. **Airplane mode:** phone in airplane mode, **Bluetooth back on**, standing near the bulb. Try on/off, brightness, white temperature and colour.
2. **Internet blocked:** block the bulb's internet access at the router (or unplug the router's WAN cable) and repeat from a phone on the same Wi-Fi. Then repeat in airplane mode with Bluetooth on.

| Test | On/off | Brightness | CCT | Colour | Notes |
|---|---|---|---|---|---|
| Airplane mode + BT | | | | | |
| Bulb internet blocked, phone on Wi-Fi | | | | | |
| Bulb internet blocked, phone airplane + BT | | | | | |

**Gate:**
- **Works in airplane mode + BT:** the app controls the bulb over BLE. Continue.
- **Fails everywhere offline:** BLE is likely setup-only on this firmware. **Stop Track A.** Use the Lepro cloud integration and/or Zigbee.

### A3. Probe the provisioned bulb

Fully close the Lepro app first. Bulbs often accept a single BLE connection and stop advertising while connected.

```bash
python lepro_ble_probe.py --ads-only --scan-seconds 120 --log-file b3_provisioned_ads.jsonl
```
```bash
python lepro_ble_probe.py --listen-seconds 180 --log-file b3_gatt.jsonl
```

While it listens, change the bulb through a non-BLE path: a voice assistant, the Lepro cloud integration in HA, or a wall-switch power cycle.

| Check | Result |
|---|---|
| Still advertises after Wi-Fi setup? | |
| Connectable? | |
| Service `1e2aa501-7292-4263-a8f1-be907f039a1f` present? | |
| Write characteristic `…a502` properties | |
| Notify characteristic `…a503` properties | |
| Other services (e.g. `0x180A` Device Information) | |
| Notifications received on state change? | |
| Any OS pairing prompt? (decline it) | |

### A4. Capture the app's BLE traffic (Android)

1. Turn on Developer options → **Enable Bluetooth HCI snoop log**, then toggle Bluetooth off and on.
2. Repeat the airplane-mode test. Do these actions with about 5 seconds between each, noting the time of each: **on → off → brightness 50% → warm white → red**.
3. Run `adb bugreport` and extract `btsnoop_hci.log`. It's under `FS/data/misc/bluetooth/logs/` in the zip; the path varies by vendor.
4. Open it in Wireshark with the filter `btatt`.

Look for:

- ATT **Write Command** (opcode `0x52`) to the `…a502` handle.
- Bytes 2–3 = `5A 50` (plain) or `5A 54` (encrypted single frame).
- Opcode bytes 6–7 = `11 00` (dpValue) once per action.
- A connect-time handshake: `10 00` search, `10 02` bond, `11 02` getDpState.
- Notifications on `…a503` with `10 01`, `11 01` or `11 03`.

To decode frame headers from copied hex, use the probe's parser:

```bash
python -c "import lepro_ble_probe as p; print(p.describe_frame(bytes.fromhex('PASTE_HEX')))"
```

| Action | Time | Frames seen (opcode / kind / len) | CRC ok? |
|---|---|---|---|
| Connect | | | |
| On | | | |
| Off | | | |
| Brightness 50% | | | |
| Warm white | | | |
| Red | | | |

**Gate:** if the framing and opcodes match the reported ZB1 protocol, the B3 uses the same protocol, and BLE-local control is feasible on this firmware. If they don't, record the differences and stop there.

### A5. Decision

| Outcome | Next step |
|---|---|
| A2 + A3 + A4 all pass | Phase 3 of the PoC plan (report §10): standalone on/off client |
| A2 passes, A4 shows a different protocol | Document the new framing; reassess |
| A2 fails | Track A closed. Cloud integration + Zigbee |

---

## Track B: Zigbee baseline (ZBDongle-E + Zigbee2MQTT)

1. Plug the dongle in **on a USB extension cable**, in a USB 2.0 port if possible, away from the PC and the router.
2. Set the COM port and confirm the channel in the Zigbee2MQTT `configuration.yaml`. **The channel is hard to change after pairing.**
3. Start Zigbee2MQTT. On the first start it generates the network key. **Back up its data folder now.**
4. Pair one Zigbee bulb (Permit join in the Zigbee2MQTT UI). Confirm it appears in HA through MQTT discovery.
5. Pair a second bulb and create a **group** in Zigbee2MQTT.

| Check | Result |
|---|---|
| Dongle detected (COM port) | |
| Zigbee2MQTT starts, adapter firmware version | |
| Bulb 1 paired and visible in HA | |
| Bulb 2 paired | |
| Group switches bulbs simultaneously? | |
| Survives Zigbee2MQTT restart | |
| Survives bulb power cycle | |

---

## Track C: Side-by-side in Home Assistant

Add the B3s with the **Lepro Cloud** HACS integration ([Wheemer/lepro-cloud](https://github.com/Wheemer/lepro-cloud)) as the cloud baseline. Its author is looking for B3 testers, so report results upstream too.

| Test | Method | Lepro cloud | Zigbee | BLE-local (if built) |
|---|---|---|---|---|
| Single bulb on/off latency | Toggle in HA; film the phone screen and bulb, or compare logbook timestamps. Repeat 5×, take the median | | | |
| Brightness change latency | As above | | | |
| Room change (all bulbs) | One automation turning all bulbs on; note simultaneous vs one-after-another | | | |
| Internet down | Unplug the router WAN; try control from HA | | | |
| Recovery after power cut | Power-cycle the bulb; time until available and controllable in HA | | | |
| State accuracy | Change via wall switch or another app; does HA reflect it, and how fast? | | | |
| 24 h reliability | Count unavailable periods in History | | | |

---

## What to collect

- `.jsonl` logs from A0 and A3. **They contain device MAC addresses**, so redact them before sharing publicly (`*.jsonl` is git-ignored).
- The `btsnoop_hci.log` file, or screenshots of the relevant Wireshark rows, from A4.
- The completed tables in this file.

If your results confirm or refute the reported protocol on a B3, opening an issue on this repo is welcome. Leave out MACs, tokens and account details.

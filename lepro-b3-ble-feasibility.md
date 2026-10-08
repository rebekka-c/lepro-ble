# Lepro B3 — local Bluetooth control for Home Assistant: feasibility study

*Researched 2026-10-08. Bulb: Lepro B3-UK, B22, RGB + tunable white, 1521 lm.*

---

## 1. Verdict

**Probably feasible, not yet proven for the B3, and not worth it for whole-house lighting.**

- **Confirmed:** the B3 has a certified Bluetooth LE radio as well as Wi-Fi. Its FCC grant lists a 2402–2480 MHz BLE transmitter alongside 2412–2462 MHz Wi-Fi.
- **Confirmed for other Lepro lights:** the Lepro app ships a native BLE control library. It can send state changes (`bleDpValue`), query state (`bleGetDpState`) and receive state reports, not just provision Wi-Fi. One public hobby repo claims working local BLE control of Lepro **ZB1** string lights using that protocol.
- **Inferred for the B3:** it very likely speaks the same protocol. It uses the same app, the same `d1`–`d5` datapoint model as the cloud MQTT API, and the same Espressif chip family. **Nobody has publicly confirmed this on a B3.**
- **Architecture:** a proprietary, point-to-point **GATT** protocol. Frames carry a CRC, payloads are AES-encrypted with keys derived from the bulb's MAC plus constants built into the app, and sessions need a bond/auth step. It is **not Bluetooth Mesh** and **not advertisement-based control**.
- **Practical ceiling:** every command needs a GATT connection, and Home Assistant has only a handful of connection slots per adapter or proxy. That makes BLE a reasonable fit for **a few bulbs in one or two rooms** and a poor fit for whole-house lighting. For that, Zigbee on your ZBDongle-E is better on every axis except reusing bulbs you already own.

**Recommendation:** run the two zero-code tests in §8 (phone in airplane mode with Bluetooth on; bulb blocked from the internet). If the app still controls the bulb, BLE control is live on your firmware, and a local integration is a realistic hobby project of several weekends. In the meantime, use the existing cloud integration for the Lepros and buy Zigbee bulbs for new rooms.

---

## 2. Evidence table

Confidence key: **C** = confirmed from a primary source, **S** = strong secondary evidence, **I** = inference, **U** = unverified claim.

| # | Finding | Source | Conf. |
|---|---|---|---|
| 1 | B3 FCC grant 2A3MAB3 (12 Sep 2025). Two 15C transmitters: **2402–2480 MHz (BLE)** and 2412–2462 MHz (Wi-Fi). Separate BLE and Wi-Fi test reports. Schematics, BOM, block diagram and operational description are under **long-term confidentiality**. Internal photos are public. | [fccid.io/2A3MAB3](https://fccid.io/2A3MAB3) | C |
| 2 | B3 sold as "Wi-Fi + Bluetooth", 2.4 GHz only, Lepro app, Alexa and Google. No mention of Matter or local control. | [Currys B3 B22 listing](https://www.currys.co.uk/products/lepro-ai-smart-b3-led-light-bulb-b22-10299266.html) | C |
| 3 | Sister model **B1** uses an **Espressif ESP8684-WROOM** (= ESP32-C2: Wi-Fi 4 + BLE 5, RISC-V). Bluetooth is described as being for setup. | [gstylemag B1 review](https://gstylemag.com/2026/05/04/lepro-b1-ai-smart-bulbs-make-home-automation-effortless-review/) | S (B1, not B3) |
| 4 | The Lepro app's native library `libiot-core.so` (APK 1.0.9.258) exposes the JNI methods `bleInit`, `bleSearchDeviceInfo`, `bleRequestBond`, **`bleDpValue`**, **`bleGetDpState`**, `bleSendWifiMqttInfo`, `bleQuitOnboardingMode` and `bleOTAStart`. It also has the callbacks **`processRevLeDeviceDpPrpReport`** and `…DpPrpGetResponse`. In other words, BLE carries state get, set *and* report, not only onboarding. | [nickyblackburn/CYNX-AI `hardware/lepro/lib/lepro/apk_analysis.py`](https://github.com/nickyblackburn/CYNX-AI/tree/main/hardware/lepro) | U (third-party decompilation notes; I did not decompile the APK) |
| 5 | Reported GATT layout on ZB1: custom service **`1e2aa501-7292-4263-a8f1-be907f039a1f`**, command characteristic `…a502` (write without response), response characteristic `…a503` (notify). Advertised name **"LP"**. | same repo, `protocol.py`, `devices.json`, `discovery.py` | U |
| 6 | Reported frame format: `CRC16 | 0x5A | kind | seq(2) | opcode(2) | len(2) | payload`. Opcodes `0x1000` search, `0x1002` bond, `0x1100` dpValue, `0x1102` getDpState, `0x1103` dpResponse, `0x1008` Wi-Fi/MQTT provisioning, `0x1010+` OTA. **I checked independently** that the two published sample frames carry a valid **CRC-16/ARC** over bytes 2 onward, so at least the framing description is internally consistent. | same repo plus my check (`test_lepro_ble_probe.py`) | S |
| 7 | Reported crypto: AES-128-CBC with a key built from the bulb's MAC and constants in the app, a per-session random value, and a bond step that yields per-device static tokens. In practice this is app-embedded obfuscation, not per-user security. | same repo, `crypto.py`, `bond.py` | U |
| 8 | MAC prefixes in that repo (`10:20:BA`, `FC:01:2C`) are **Espressif** OUIs. The repo's firmware tooling assumes ESP-IDF images. | [maclookup 1020BA](https://maclookup.app/macaddress/1020ba), [FC012C](https://maclookup.app/macaddress/fc012c) | C (OUI) |
| 9 | Cloud API: regional REST hosts `api-{na,eu,fe}-iot.lepro.com`, MQTT topics `le/{deviceId}/prp/{get,set,rpt,getr,setr}`, datapoints `d1` power, `d2` mode, `d3` brightness, `d4` CCT, `d5` HSV/effect. | [Wheemer/lepro-cloud `docs/PROTOCOL.md`](https://github.com/Wheemer/lepro-cloud/blob/main/docs/PROTOCOL.md) | S |
| 10 | B-series bulbs: RGB mode is `d2=1` + `d5`, white mode is `d2=0` + `d3`/`d4` (seen in the app's MQTT traffic). | [Sanji78/lepro_led README](https://github.com/Sanji78/lepro_led) | S |
| 11 | Existing Home Assistant options are **cloud only**: Lepro Cloud (announced 6 Oct 2026, asking for B3 testers) and Lepro LED. No local integration exists. | [HA forum: Lepro Cloud](https://community.home-assistant.io/t/lepro-cloud-home-assistant-integration-for-lepro-wi-fi-devices/1027623), [HA forum: Lepro+ integration](https://community.home-assistant.io/t/lepro-integration/796480) | C |
| 12 | An **older** Lepro GU10 was a Tuya product (BK7231N + BP5758) and was flashed with OpenBeken. This shows Lepro has changed platforms over time. It says nothing about the B3. | [Elektroda teardown](https://www.elektroda.com/news/news4045670.html) | C (GU10 only) |
| 13 | No Lepro Matter product, Matter certification or local LAN API found. | searches (negative result) | — |
| 14 | ESPHome Bluetooth proxy: 3 connection slots by default, up to 9, recommended no more than 5 (Ethernet boards handle about 4). GATT needs active connections. Use ESP-IDF; place proxies near the devices. | [ESPHome bluetooth_proxy](https://esphome.io/components/bluetooth_proxy/) | C |
| 15 | HA local adapters: CSR adapters hold about 5 connections, Broadcom about 7. Onboard Pi adapters sit on UART and "may limit performance". HA chooses the adapter or proxy by best signal and free slots. | [HA Bluetooth integration](https://www.home-assistant.io/integrations/bluetooth/) | C |

**Quality warning on the key source (rows 4–7):** CYNX-AI is a one-star hobby repo created in July 2026 by one person, inside an unrelated "AI personality" project, with commit messages like "got stuff wworking". It targets **ZB1 string lights**, not bulbs. Treat it as a map of what to look for, not as ground truth. It also contains firmware-patching, OTA and certificate-hijack tooling, which I deliberately did not use or reproduce (see §11).

---

## 3. Likely protocol architecture (B3)

```
Lepro Home app ──(HTTPS)──► api-eu-iot.lepro.com     account, device list
       │
       ├──(MQTT/TLS)──► Lepro broker ◄──(MQTT/TLS)── B3 (ESP32-C2-class, Wi-Fi)
       │                 le/{id}/prp/set|get|rpt
       │
       └──(BLE GATT, point-to-point)──────────────► B3 (same chip, BLE 5)
             svc 1e2aa501-…  write …a502 / notify …a503      [reported for ZB1]
             frames: CRC16 | 5A | kind | seq | opcode | len | AES-CBC(JSON)
             JSON body = same datapoints as MQTT: {"d1":1}, {"d2":0,"d3":800,"d4":300}
```

| Question | Best answer |
|---|---|
| BLE GATT, Mesh, advertising or provisioning only? | **Proprietary BLE GATT** (I). The app library supports control as well as provisioning (S). No Mesh service UUIDs (`0x1827`/`0x1828`) are reported. |
| Is BLE still active after Wi-Fi setup? | **Unknown for the B3.** The ZB1 notes describe device-info "provisioned" states and an "already bonded" bond result, which suggests BLE stays up after provisioning (U). Your probe scan with the bulb on Wi-Fi will answer this in minutes. |
| Encryption and authentication | App-layer AES-CBC with app-embedded key material, plus a bond step. **No BLE-level pairing** is reported. |
| State reporting | The `dpPrpReport` callback implies push reports over notify while connected (U). Whether adverts carry state is unknown. |
| Effects and scenes | Bulb scenes are DP payloads (`d5` effect strings, `d6` legacy bulb scenes). The cloud lists them in `config.series.json`. "AI" scene *generation* is cloud-side, but the resulting payloads could be replayed locally. |

---

## 4. Reverse-engineering toolkit (owner's own devices, for interoperability)

| Method | What it can reveal | Notes |
|---|---|---|
| **BLE advert scan** (`lepro_ble_probe.py --ads-only`, nRF Connect) | Advertised name, connectable or not, service UUIDs, manufacturer data, and whether adverts change when the bulb's state changes. | Zero risk. Do this first. |
| **nRF Connect (Android)** GATT browser | Full service and characteristic table, properties, readable values (Device Information `0x180A`?). | Read-only use. Do not write. |
| **`lepro_ble_probe.py` connect mode** | Same as nRF Connect, plus JSONL logs and frame-header tagging of notifications. | Delivered with this report. |
| **Android HCI snoop log** (Developer options → "Enable Bluetooth HCI snoop log", then `adb bugreport`) | Every ATT write and notify the app makes, with timings. Shows whether the app uses BLE when you tap a control, which opcode it uses, and whether there is a bond handshake on connect. | The decisive experiment. Open in Wireshark with filter `btatt`. |
| **`adb logcat`** | App log lines (if the app logs) around BLE vs MQTT decisions. | Often stripped in release builds. |
| **btmon / BlueZ** (Linux, Pi) | HCI-level trace of your *own* client's traffic. Useful when debugging the integration. | Doesn't see phone↔bulb traffic. |
| **Wireshark** | Dissects snoop logs and btmon captures. Use `btatt.handle`, `btatt.opcode == 0x52` (write command), `0x1b` (notify). | — |
| **Passive air sniffer** (nRF52840 dongle + nRF Sniffer) | Phone↔bulb traffic without rooting or snoop logs. Can follow connections. | Optional. HCI snoop is easier. |
| **Static APK analysis** (jadx for Java/Kotlin, Ghidra for `libiot-core.so`) | DP names, JNI surface, frame building. | UK CDPA s.50B and EU Software Directive art. 6 allow decompilation for interoperability only under narrow conditions (information not otherwise available, only the parts needed, not shared beyond that purpose). Check the app's terms. Not legal advice. |

---

## 5. Bluetooth Mesh, proxies and Zigbee

- **Standard BLE (point-to-point):** one central (HA, a proxy or a phone) connects to one peripheral (the bulb) at a time and exchanges GATT reads, writes and notifies. Bulbs don't relay for each other. **This is what the B3 appears to do.**
- **Bluetooth Mesh:** a separate SIG specification with managed-flood relaying, its own provisioning, network and app keys, and the GATT services `0x1827`/`0x1828` for phones. A device must be built for it. **Having Bluetooth, or even BLE 5, does not make a bulb a Mesh node.** No evidence suggests the B3 implements Mesh, and the probe flags those UUIDs if they appear. Home Assistant has no native Bluetooth Mesh integration anyway.
- **BLE proxies (generic):** any device that relays BLE traffic to another system over IP.
- **ESPHome Bluetooth proxy:** an ESP32 that forwards adverts (passively, no slots used) and, with active connections, opens **GATT connections on HA's behalf** (3 slots by default, about 5 sensible). It extends **range**, not mesh. HA picks whichever proxy or adapter has the best RSSI and a free slot. **So yes: proxies extend coverage even though the bulbs are not mesh devices.** Each bulb still needs to be within a few rooms of *some* proxy.
- **HA Bluetooth architecture:** the `bluetooth` integration aggregates local adapters and proxies into one scanner and connection manager. Integrations ask for a `BLEDevice` by address and connect through `bleak-retry-connector`. HA handles routing and failover.
- **Zigbee mesh:** a different radio stack (IEEE 802.15.4). Mains-powered Zigbee bulbs **are routers** and genuinely extend the network. Group commands are multicast, so a room changes at once. Your ZBDongle-E is a Zigbee coordinator. It cannot talk to BLE devices, and the B3 has no Zigbee radio.

---

## 6. Coverage and scalability

| Factor | BLE (B3) | Notes |
|---|---|---|
| Connection slots | Local adapter about 5–7. Each ESPHome proxy about 3–5. | Persistent connections hold slots. |
| Persistent connections (push state, fast commands) | ≈ (proxies × 4) + adapter. **4 proxies ≈ 16–20 bulbs.** | Best UX, but slot-hungry. |
| Connect-on-demand | Unlimited bulbs in principle, but each command pays connect + session handshake. The ZB1 notes use delays of 0.4–3 s between steps, so expect **about 1–4 s per bulb** for a cold command. | No live state between connections. |
| Group or room control | **Sequential** per bulb. Slots and handshakes cause a visible "popcorn" effect across 6+ bulbs. | Zigbee groups are simultaneous. |
| Interference | 2.4 GHz is shared with Wi-Fi, the bulbs' own Wi-Fi radios, Zigbee and USB 3. A single-antenna combo chip like the ESP32-C2 time-shares Wi-Fi and BLE, so BLE responsiveness can suffer while the bulb is busy on Wi-Fi. | Put proxies on Ethernet where possible. |
| Pi Zero 2 W onboard BT | BT 4.2 combo chip on UART, sharing the antenna with the Pi's Wi-Fi. Weak for active GATT. | Use ESPHome proxies instead, or a CSR USB adapter (note the Zero has one OTG port, which the ZBDongle-E wants too). |

**Rule of thumb:** BLE local control is fine for **≤ 6 bulbs near one or two proxies**. Beyond that, reliability and group latency get worse fast. For whole-house lighting, Zigbee is the right tool.

---

## 7. Alternative local-control routes

| Route | Applies to B3? | Effort / risk | Worth it? |
|---|---|---|---|
| **Lepro cloud integration** (Lepro Cloud / Lepro LED) | Yes (B3 support is being tested now). | Low effort. Uses MQTT push, so it's fast, but it depends on Lepro's cloud and on credentials and keys taken from the app. | **Yes, as the stop-gap.** |
| **Local LAN API** | None found. The bulb appears to connect *outbound* to a TLS MQTT broker. | Redirecting it to a local broker would mean defeating certificate validation. | **No.** Out of scope (security bypass). |
| **Matter** | No evidence of a B3 Matter build or certification. | — | Watch for firmware news, nothing more. |
| **Tuya / LocalTuya / tuya-cloudcutter** | **No.** The B3 uses Lepro's own platform (own REST, MQTT and app), not Tuya. The Tuya-based Lepro GU10 is an older, different product. | — | No. |
| **OpenBeken** | Built for BK72xx, LN882H and similar. ESP32-family support exists but ESP32-C2 support is limited or unverified. | Needs opening the bulb. | No. |
| **ESPHome / Tasmota replacement firmware** | Both support the ESP32-C2 family (check the current status). | **Opening a glued, mains-powered bulb**, soldering to UART pads on the driver board, a possibly small (2 MB?) flash, and **secure boot / flash encryption may be enabled**, which would block flashing or brick it. Driver-IC pin mapping is unknown (the schematics are confidential). | **No.** A Zigbee bulb costs less than an hour of this. |
| **OTA replacement or patched firmware over BLE** | The CYNX repo has tooling for this on ZB1. | High brick risk, tampers with security mechanisms. | **No.** |

---

## 8. Recommended next experiments (in order)

1. **Airplane-mode test (5 min, no tools).** Phone in airplane mode with Bluetooth turned back on, standing near the bulb. Can the Lepro app still switch it, dim it and change colour? **Yes** means the app controls it over BLE locally. **No** may mean BLE is setup-only on your firmware, or the app refuses to work offline.
2. **Internet-block test.** Block the bulb's internet access at the router (keep it on Wi-Fi). Does the app still work nearby over Bluetooth? Does the bulb keep working from wall-switch power cycles? Restore access afterwards.
3. **Advert scan:** `python lepro_ble_probe.py --ads-only --scan-seconds 120`, with the bulb provisioned and on. Is it advertising? Under what name? Is it connectable? Is service `1e2aa501…` listed? Do adverts change when you toggle it from the app?
4. **GATT dump:** `python lepro_ble_probe.py --listen-seconds 120`. Fully close the Lepro app first, or turn off phone Bluetooth: many bulbs accept one connection only and stop advertising while connected. Confirm the service and characteristics. Leave it subscribed, then change the bulb via the cloud (e.g. Alexa) and see whether notifications arrive.
5. **HCI snoop capture:** do test 1 again with snoop logging on. In Wireshark, check for writes to `…a502` starting with the `5A 50`/`5A 54` framing and opcode `0x1100` on each tap. This confirms or rejects the ZB1 protocol on the B3. Feed the notify hex into `describe_frame()` from the script.
6. **Decision point:** if steps 1 and 5 are positive, you have the evidence to build a local integration (§9/§10). If BLE is setup-only, stop: the remaining local routes are firmware replacement or Zigbee bulbs.

---

## 9. Proposed Home Assistant integration architecture

Follow HA's split of a **PyPI protocol library** (`lepro-ble`) plus a **thin integration** (`custom_components/lepro_ble`), modelled on core BLE light integrations such as `led_ble` and `govee_ble`.

**Library `lepro-ble` (no HA imports):**
- `frame.py`: build and parse, CRC-16/ARC, fragmentation and reassembly.
- `session.py`: async state machine (connect → search hello → bond/auth → ready), sequence counters, one `asyncio.Lock` per device so commands are serialised.
- `device.py`: `LeproBleDevice(ble_device, credentials)` with `turn_on(brightness, kelvin, hs, effect)`, `turn_off()`, `update()`, a state-change callback, and `set_ble_device()` so HA can swap the adapter path. It connects through **`bleak_retry_connector.establish_connection`** with `BleakClientWithServiceCache`, uses an **idle-disconnect timer** (e.g. 30–60 s) to free slots, and backs off on reconnect.
- `models.py`: frozen dataclasses for state, plus DP translation (`d1`–`d6`) shared with the cloud protocol.

**Integration:**
- `manifest.json`: `"bluetooth": [{"service_uuid": "1e2aa501-7292-4263-a8f1-be907f039a1f"}, {"local_name": "LP*", "connectable": true}]`, `"dependencies": ["bluetooth_adapters"]`, `"iot_class": "local_push"` (or `local_polling` if the bulb has no reports), `"requirements": ["lepro-ble==x.y"]`.
- **Discovery:** HA's Bluetooth matcher feeds `async_step_bluetooth`. `async_step_user` lists unconfigured discovered bulbs.
- **Config flow and credentials:** this is the hard part. Options, in order of preference: (a) a bond flow that works on an *already provisioned* bulb, if one exists; (b) obtain per-device BLE credentials from your own Lepro account via the cloud device list, if it exposes them (*TBD, needs research*); (c) a reset-and-bond flow (loses the cloud pairing). Validate by running `update()` before creating the entry. Unique ID = MAC.
- **Runtime:** `entry.runtime_data` holds the device. `bluetooth.async_register_callback` updates the `BLEDevice` when a better path appears. `bluetooth.async_track_unavailable` drives availability. Use an `ActiveBluetoothDataUpdateCoordinator` for polling fallback when there are no push reports.
- **`light` platform:** `supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}` (the bulb's white and colour modes are exclusive). Brightness maps 0–255 ↔ 10–1000. Colour temperature maps `d4` 0–1000 ↔ Kelvin (*range TBD, measure it*). HS maps ↔ `d5` `HHHHSSSSVVVV`. `effect_list` comes from known `d6` scenes. `assumed_state` stays False only if the bulb reports state.
- **Unavailable handling:** mark unavailable on `async_track_unavailable` or after N failed connects, and keep the last state. Don't hammer the bulb: use exponential backoff capped at about 5 min.
- **Diagnostics:** `async_get_config_entry_diagnostics` returns the last N frames (headers only), RSSI, adapter/proxy source, connection timings and firmware version, with MAC, tokens and keys **redacted**.
- **Tests:** `pytest-homeassistant-custom-component`. Cover frame and crypto vectors, the config flow (bluetooth, user, errors, abort when already configured), light service calls mapped to DP JSON, unavailable and recovery, and reconnect with a mocked `BleakClient` / `establish_connection`. Aim for 80%+ coverage.

**Direct connection vs advertisements:**

| | GATT connection (the B3's apparent model) | Advertisement commands/state (other bulb brands) |
|---|---|---|
| Commands | Reliable, acknowledged, encrypted | Fire-and-forget broadcasts, no ack |
| Slots | Uses a slot per bulb while connected | None. Scales to many bulbs |
| State | Notifies while connected | Only if the bulb advertises state |
| Fit for B3 | **Required**, as far as the evidence shows | No evidence the B3 supports it |

---

## 10. Minimal proof-of-concept plan

| Phase | Goal | Output | Gate |
|---|---|---|---|
| 0 | Airplane-mode and internet-block tests (§8 steps 1–2) | Yes/no on local BLE control | If no, stop |
| 1 | `lepro_ble_probe.py --ads-only`, then connect mode | Advert and GATT JSONL; confirm UUIDs and connectability when provisioned | Service present? |
| 2 | HCI snoop of app taps; parse with `describe_frame()` | Opcode sequence for connect, bond and set; latency | Matches ZB1 framing? |
| 3 | Standalone `lepro-ble` CLI: on/off only | Local on/off from a laptop | Works while the Lepro cloud is blocked? |
| 4 | Add brightness, CCT, HS, state query; notify-driven state | Full `light` feature set | Stable for 24 h |
| 5 | HA integration skeleton + one ESPHome proxy near the bulbs | Entities, availability, diagnostics, tests | — |

Phases 3–5 mean reimplementing the app's encryption. The evidence suggests it uses app-embedded keys rather than per-user secrets, and you'd be talking only to your own bulbs for interoperability. That's a judgement call for you (legal and terms of service), so I deliberately left key material and decryption out of the delivered code.

---

## 11. Risks and unknowns

- **B3 protocol unconfirmed.** Everything protocol-specific comes from one ZB1-focused hobby repo. The B3 firmware may differ (different service, BLE disabled after provisioning, newer crypto).
- **Credential bootstrap.** If a provisioned bulb only accepts the app's bond tokens, HA may need a reset-and-bond flow, which breaks cloud and app pairing.
- **Firmware updates.** Lepro can change or disable the BLE protocol over OTA with no notice. Consider blocking OTA (it's Wi-Fi/MQTT based, so that means blocking internet), but that also kills the cloud path.
- **Single connection.** The bulb may accept only one BLE central, so HA and the phone app would fight over it.
- **Combo-radio contention.** BLE responsiveness may suffer while the bulb's Wi-Fi is active.
- **Legal and ToS.** Decompilation and protocol reimplementation for interoperability are narrowly permitted in the UK/EU. The app's terms may say otherwise. Not legal advice.
- **The CYNX repo** includes OTA, firmware-patch, CDN and "debug_hijack" tooling. **Don't run it against your bulbs.** It's the kind of code that bricks devices or tampers with security mechanisms.
- **Pi Zero 2 W:** the onboard Bluetooth is weak and HA OS on 512 MB of RAM is tight. Plan on ESPHome proxies from day one, and on the home-server migration.

---

## 12. Comparison

| | **BLE-local (B3, DIY)** | **Lepro cloud (HACS)** | **Zigbee (ZBDongle-E + Zigbee bulbs)** |
|---|---|---|---|
| Works offline | Yes (if feasible) | **No** | Yes |
| Exists today | **No.** Needs research and building | Yes | Yes (ZHA / Zigbee2MQTT) |
| Latency, single bulb | ~0.3 s when connected; 1–4 s cold | ~0.3–1 s (MQTT push) | ~0.1–0.3 s |
| Room/group change | Sequential, popcorn effect | Per-device cloud calls | **Simultaneous** (group multicast) |
| State reporting | Notify while connected (likely) | Push via MQTT | Push (attribute reports) |
| Scale | ~5 per proxy; poor for whole house | Unlimited (cloud) | 100+; bulbs extend the mesh |
| Fragility | Firmware changes, slot limits, credential bootstrap | Cloud outages, API or key changes | Very low |
| Cost | Your time + £10–20 per ESP32 proxy | Free | ~£10–20 per bulb |
| Fit for you | Experiment for the existing B3s | **Use now** | **Default for new lighting** |

---

## 13. Deliverables in this folder

- `lepro-b3-ble-feasibility.md`: this report.
- `lepro_ble_probe.py`: read-only scanner, GATT dumper and notification logger (bleak ≥ 0.22). It never calls a GATT write or `pair()`. The only write is the standard subscription (CCCD) that `start_notify` makes, and `--no-subscribe` turns that off. Caveat: if a characteristic requires encryption, the **OS** may start pairing on a read or subscribe. Decline any prompt, or use `--no-read --no-subscribe`. `--all` only widens *logging*; the script never connects to non-Lepro devices.
- `test_lepro_ble_probe.py`: 30 pytest tests, 95% coverage. They include write/pair traps on the fake client and a static check of the source for write/pair calls.

Run:

```bash
pip install "bleak>=0.22"
python lepro_ble_probe.py --ads-only --scan-seconds 120
python lepro_ble_probe.py --listen-seconds 120
```

If Home Assistant is already running on the same Pi, its Bluetooth integration owns the adapter. Run the probe from a laptop instead, or temporarily disable HA's Bluetooth integration.

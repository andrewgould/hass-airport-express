# hass-airport-express

> AirPlay activity monitor for a 2nd-gen Apple AirPort Express, bridged to Home Assistant over MQTT.

A small, always-on service that watches whether an **AirPort Express (gen 2)** currently has an
AirPlay/RAOP stream active, and publishes that as a `binary_sensor` in Home Assistant via MQTT
discovery. It gives you a coarse **"is something playing to the Express right now?"** signal for
automations — nothing more, and by design.

## Why this exists

An AirPort Express (gen 2) is a plain AirPlay/RAOP receiver. It does **not** speak Apple's MRP
(Media Remote Protocol) — the protocol Apple TVs and HomePods use to report play state, track
metadata, position, etc. Home Assistant's Apple TV integration (built on
[`pyatv`](https://github.com/postlund/pyatv)) can add the Express as a `media_player`, but per
pyatv's own docs, **play state simply isn't obtainable from a plain AirPlay receiver** — the device
never transmits it. That's a protocol limitation, not a bug.

What *does* exist is a coarser "a stream is currently active" signal:

- AirPlay/RAOP devices advertise via mDNS/Bonjour (`_raop._tcp.local.` and `_airplay._tcp.local.`)
  and include a status/flags field in their TXT records (`sf=` on `_airplay._tcp`; an equivalent on
  `_raop._tcp`) that appears to change when a streaming session opens or closes.
- The same/similar information is exposed via a binary-plist HTTP endpoint at
  `http://<express-ip>:7000/info` (a `statusFlags` field).

Neither is officially documented for gen-2 hardware, so **confirming what the field means is part of
the project** (see [Phase 0](#phase-0--reverse-engineering--validation)).

## Scope

**Goal:** a `binary_sensor` in HA that flips `on` within a few seconds of AirPlay streaming starting
to the Express, and back `off` within a configurable delay after it stops — running continuously as a
Docker container, auto-discovered by HA, and resilient to broker/HA/Express restarts.

**Non-goals** (explicitly out of scope):

- Play/pause distinction *within* an active session
- Track metadata, artwork, or position
- Playback control (play/pause/skip/volume)
- Replacing the Express with different receiver hardware (e.g. Shairport Sync) — this keeps the
  existing Express in place and just adds visibility

## How it works

```
 AirPort Express ──mDNS TXT (_raop / _airplay)──┐
       │                                         ├──► decision function ──► debounce ──► MQTT ──► Home Assistant
       └──HTTP /info (binary plist, fallback)────┘        (Phase 0)        (hysteresis)  (discovery)  binary_sensor
```

- **Event-driven discovery** via `python-zeroconf`'s `AsyncServiceBrowser`, scoped to the Express's
  known service name — state changes are picked up as they're announced, not on a poll timer.
- **Fallback `/info` poll** every 30–60 s as a self-healing cross-check, in case a multicast mDNS
  event is missed. Uses the *same* decision function as the mDNS path.
- **Debounce / hysteresis**: a configurable off-delay (and consecutive-observation requirement) so
  brief AirPlay handshake blips — selecting the device, a volume nudge — don't make automations flap.
  Modelled on Shairport Sync's `active_state_timeout`.
- **MQTT**: publishes `ON`/`OFF` to a state topic only on change, an availability topic (LWT) so HA
  can tell "monitor offline" from "Express idle", and a discovery config so the entity appears
  automatically (`device_class: sound`).

## Status

✅ **Phase 0 complete.** Confirmed against a real gen-2 Express (model AirPort10,115): streaming
sets bit `0x800` on top of the idle baseline (`0x4` → `0x804`) across `_airplay` `flags=`, `_raop`
`sf=`, and `/info` `statusFlags=` alike. See the FINDINGS block in
[`state.py`](src/hass_airport_express/state.py) and [`tests/fixtures/`](tests/fixtures/) for the
captured data. Remaining work is Phase 1 end-to-end validation and deployment — see the
[project issues](../../issues).

## Quick start

```bash
cp config.example.yaml config.yaml     # edit device + MQTT details
docker compose up -d                    # see docker-compose.example.yml
```

> **Networking note:** mDNS multicast generally does **not** traverse Docker's default bridge
> cleanly. Run with **host networking** or attach to the existing **macvlan** network used for other
> IoT-adjacent containers. See [`docker-compose.example.yml`](docker-compose.example.yml).

## Configuration

Config is a **list of devices** from the start (a single container can monitor more than one
Express). See [`config.example.yaml`](config.example.yaml) for the full annotated schema. Every value
can also come from environment variables for container-friendly deployment.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # unit tests for the decision function (fixture-driven)
python scripts/phase0_diagnostic.py --help   # the Phase 0 reverse-engineering logger
```

## Prior art

- [`hass-shairport-sync`](https://github.com/parautenbach/hass-shairport-sync) and
  [`johnneerdael/Airplay-2-for-Home-Assistant`](https://github.com/johnneerdael/Airplay-2-for-Home-Assistant)
  both target **software** AirPlay receivers (Shairport Sync), not physical AirPort Express hardware,
  so their core logic isn't directly reusable — but their MQTT topic structure and HA discovery
  payload shape are good conventions to match, and this project does.

## License

[MIT](LICENSE) © 2026 Andrew Gould

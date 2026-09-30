# hass-airport-express

> Home Assistant custom integration: **is something AirPlaying to this AirPort Express right now?**

Adds one `binary_sensor` per AirPort Express (gen 2) that turns **on** within a second of an AirPlay
stream starting and **off** when it stops. No cloud, no polling of anything but the device itself,
and nothing to run alongside Home Assistant.

## Why this exists

An AirPort Express (gen 2) is a plain AirPlay/RAOP receiver. It does **not** speak Apple's MRP
(Media Remote Protocol) — the protocol Apple TVs and HomePods use to report play state. Home
Assistant's Apple TV integration (built on [`pyatv`](https://github.com/postlund/pyatv)) will happily
add the Express as a `media_player`, but per pyatv's own docs **play state simply isn't obtainable
from a plain AirPlay receiver**. In practice that entity sits at `idle` forever, whatever is playing.

What the hardware *does* expose is a coarser "a stream is currently open" signal, in the status-flags
field of its mDNS TXT records and its `/info` endpoint. This integration watches those and publishes
the one boolean that automations actually need.

## What you get

- **`binary_sensor.<name>_airplay_active`** (`device_class: sound`) — on while a stream is open
- Raw per-source flag values as attributes (`airplay_flags`, `raop_flags`, `info_flags`), because
  when the sources disagree you want to see which said what
- Zeroconf discovery: an Express on the network is offered to you, no YAML
- **`airport_express.join` / `airport_express.unjoin`** actions that add the Express to a HomePod's
  (or Apple TV's) playback and take it out again — see [Grouping](#grouping-with-a-homepod)

**Non-goals**, all of them hardware limits rather than missing features:

- Play/pause distinction *within* a session — the flag is identical either way
- Track metadata, artwork, or position
- Playback control of the Express itself (grouping works by asking the *HomePod*, below)

## How it works

```
 AirPort Express ──mDNS TXT (_airplay flags= / _raop sf=)──┐
       │                                                    ├──► decision fn ──► debounce ──► binary_sensor
       └──HTTP /info (statusFlags, polled as a cross-check)──┘
```

- **Event-driven**: shares Home Assistant's own Zeroconf instance and reacts to TXT updates as
  they're announced — sub-second in practice.
- **`/info` cross-check** every 45s heals a missed multicast packet, through the *same* decision
  function as the mDNS path.
- **Debounce**: a short off-delay so handshake blips don't flap the sensor. Keep it short — see
  [Timing](#timing).

## Confirmed against real hardware

Phase 0 established the encoding; a second capture on 2026-08-19 confirmed it end to end with a real
Apple sender:

```
t+107.5s  _airplay  flags=0x804   streaming        ← stream starts
t+107.6s  _raop     sf=0x804                       (+100ms)
t+108.5s  /info     statusFlags=0x804              (+1s, poll interval)
t+184.2s  _airplay  flags=0x4     idle             ← stream stops
```

Idle is `0x4`; streaming sets `0x800` on top of it, identically across all three sources.
`_airplay` leads `_raop` by ~100ms consistently. Detection and clearing are both sub-second, so all
of the "has it really stopped" delay is yours to choose.

> [!IMPORTANT]
> **The sender matters.** Streams originated by pyatv (including Home Assistant's own
> `tts.speak` and `media_player.play_media` to the device) do **not** set the bit — three separate
> attempts left `statusFlags` at `0x4` throughout. Apple senders do. This is fine for the use case
> (you're streaming from Apple devices) but it means you cannot self-test from Home Assistant: a
> real iPhone/Mac has to do the streaming.

## Timing

Two delays, deliberately in different places:

| Delay | Where | Default | What it's for |
| --- | --- | --- | --- |
| Off delay | This integration's options | 10s | Riding out AirPlay handshake blips so the sensor doesn't flap |
| "Has the music really stopped" | **Your automation's `for:`** | yours | The wait before you act — turning an amplifier off, say |

Keeping the second one in the automation means the sensor stays an honest report of the hardware,
and the delay you actually care about is visible where you use it rather than buried in a config
entry. For example:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.court_yard_airplay_active
    to: "off"
    for: "00:00:30"
```

## Grouping with a HomePod

An Express only plays what it's sent, so "share the kitchen music with the courtyard" is a request
to the **HomePod**: add this speaker to your outputs, exactly as ticking a second speaker in Control
Center does. HomePods accept that over their Media Remote Protocol with no pairing, and
[`pyatv`](https://pyatv.dev) exposes it as `add_output_devices` / `remove_output_devices`. Home
Assistant's Apple TV integration doesn't offer `media_player.join` for HomePods, so this integration
does it: the leader's address (and any credentials) come from its Apple TV config entry, and each
call opens a short connection of its own.

```yaml
actions:
  - action: airport_express.join        # or airport_express.unjoin
    target:
      entity_id: binary_sensor.court_yard_airplay_active
    data:
      leader: media_player.kitchen_homepod
```

Both are idempotent, check the HomePod's output list afterwards, and raise if the HomePod accepted
the request but didn't act on it. With `response_variable` they return
`{"changed": {"<entity_id>": true|false}}` — `false` meaning it was already in (or out of) the group.

**Take it out when you're done.** The HomePod remembers the group, so an Express left in it will
play the next thing the HomePod plays, hours later.

## Installation

**HACS → ⋮ → Custom repositories**, add `https://github.com/andrewgould/hass-airport-express` as an
**Integration**, download it, and restart Home Assistant. Your Express should then appear under
**Settings → Devices & services** as a discovered device; if it doesn't, **Add integration →
AirPort Express** and enter its IP.

Give the Express a DHCP reservation — the `/info` cross-check is addressed by IP.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements_test.txt
pytest -q
```

`state.py` and `monitor.py` are deliberately free of Home Assistant imports, so the decision function
and the debouncer are testable as plain Python with no `hass` fixture. `__init__.py`,
`config_flow.py` and `binary_sensor.py` are the Home Assistant glue.

## History: this used to be an MQTT sidecar

Until 2026-08-19 this shipped as a standalone Docker service that published to MQTT and let Home
Assistant discover the sensor from there. That design assumed a broker worth reusing; when the time
came to deploy, the house's broker turned out not to be running, and the design was carrying a
container, a broker and Docker-multicast problems to deliver one boolean. Rebuilding it as an
integration deleted all three. The detection logic — the part the reverse-engineering went into —
came across unchanged.

## Prior art

- [`hass-shairport-sync`](https://github.com/parautenbach/hass-shairport-sync) and
  [`johnneerdael/Airplay-2-for-Home-Assistant`](https://github.com/johnneerdael/Airplay-2-for-Home-Assistant)
  both target **software** AirPlay receivers (Shairport Sync), not physical AirPort Express hardware.

## License

[MIT](LICENSE) © 2026 Andrew Gould

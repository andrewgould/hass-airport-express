# Changelog

Versions follow [semantic versioning](https://semver.org/). The version in
`manifest.json` is what HACS installs, and each release tag must match it.

## 1.2.1

- **An icon.** The integration now ships its own icon (a base-station box with
  a sound-wave badge, in light and dark versions), so it shows in
  **Settings → Devices & services** and in HACS instead of a blank tile. It
  uses the integration's `brand/` folder, which Home Assistant reads from
  2026.3 onwards. Older versions just carry on without it.
- Release notes now come from this changelog.
- No change to how the sensor or the actions behave.

## 1.2.0

- **Group two HomePods, not just the Express.** `airport_express.join` and
  `airport_express.unjoin` can now target a HomePod (or Apple TV) media player
  from the Apple TV integration as well as an AirPort Express. So you can put
  the bedroom HomePod into what the kitchen HomePod is playing, and take it out
  again, which Home Assistant's own Apple TV integration can't do.

  ```yaml
  - action: airport_express.join
    target:
      entity_id: media_player.bedroom_homepod
    data:
      leader: media_player.kitchen_homepod
  ```

- A leader lists another HomePod by the `psi` in that HomePod's AirPlay TXT
  record, not by its MAC, so that's the id sent. A device with no `psi` falls
  back to its AirPlay device id, which is what the Express uses.
- The leader can't be its own target. Asking for that is a validation error.
- Measured with a HomePod playing Apple Music: a HomePod mini joined in about
  2 seconds and left in about 2.5, and the leader kept playing.
- Nothing changes for existing Express automations.

## 1.1.1

- **Fixed:** `join` could report a failure for a join that had worked. A
  HomePod that's playing takes about 5 seconds to list a new speaker, because
  it opens a stream to it first, and the old fixed 2-second check gave up
  before then. The actions now poll the HomePod's output list for up to 20
  seconds.

## 1.1.0

- **New actions: `airport_express.join` and `airport_express.unjoin`.** They
  add the Express to a HomePod's (or Apple TV's) playback and take it out
  again, the same thing ticking a second speaker in Control Center does.
  HomePods accept this with no pairing. The leader's address and any
  credentials come from its Apple TV config entry.
- Both actions are idempotent and confirm the change against the HomePod's
  output list. With `response_variable` they return
  `{"changed": {"<entity_id>": true|false}}`.
- Once grouped, the Express reports streaming, so automations on its
  `binary_sensor` (an amplifier, say) follow on their own.

## 1.0.1

- **Fixed:** the sensor could stay on long after the music stopped, keeping
  anything that follows it (like an amplifier) switched on. mDNS updates only
  arrive when something changes, so a missed "stream stopped" packet left a
  stale "active" reading that outvoted the correct idle reading from the
  device's `/info` endpoint for ever.
- Readings now expire after 2.5 poll intervals, so a source that has gone
  quiet stops counting. The poll loop also re-asks for the mDNS records instead
  of waiting to be told, so a healthy source keeps itself fresh.

## 1.0.0

First release as a Home Assistant integration. It replaces the earlier MQTT
sidecar, which needed a broker, a container and Docker multicast to deliver
one on/off value.

- One `binary_sensor` per AirPort Express (gen 2), `device_class: sound`, that
  turns on within about a second of an AirPlay stream starting and off when it
  stops.
- Reads the streaming bit (`0x800`) the Express sets in its status flags, on
  its `_airplay` and `_raop` mDNS records and its `/info` endpoint, and shows
  each source's raw value as an attribute.
- Zeroconf discovery, filtered to AirPort hardware, so an Express on the
  network is offered to you and other AirPlay speakers aren't. It can also be
  added by IP address.
- Options for the off delay, how many matching readings confirm a change, and
  the `/info` poll interval.
- Needs Home Assistant 2025.2 or later.
- Only Apple senders (iPhone, Mac, HomePod) set the streaming bit. Streams
  from pyatv, including Home Assistant's own `play_media` and text-to-speech,
  don't show up.

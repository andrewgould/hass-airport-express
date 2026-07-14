"""AirPlay activity decision function.

This module maps the raw signals from an AirPort Express — the mDNS TXT records
of its ``_raop._tcp`` / ``_airplay._tcp`` services, and the ``/info`` binary
plist — onto a single boolean: **is a stream currently active?**

╔══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 0 — CONFIRMED against real hardware (2026-07-14)                      ║
║                                                                              ║
║  Streaming sets bit 0x800 on top of the idle baseline (0x4 -> 0x804) on ALL  ║
║  three sources (_airplay flags=, _raop sf=, /info statusFlags), in lockstep. ║
║  See FINDINGS below for the captured transitions this is based on.           ║
╚══════════════════════════════════════════════════════════════════════════════╝

FINDINGS
--------
- Device under test: AirPort Express gen 2, model AirPort10,115,
  fv=p20.78100.3, hostname Theatre-AirPort-Express.local, mDNS name "Court yard"
- Field NAME: _airplay._tcp has NO ``sf=`` key on this firmware (contrary to
  the project brief's assumption, likely written for different firmware) —
  the equivalent field here is ``flags=``. _raop._tcp does use ``sf=``.
- Bit confirmed: idle = 0x4 on all three sources. Streaming = 0x804 = 0x4 |
  0x800 on all three sources, simultaneously (same encoding shared across
  _airplay flags=, _raop sf=, and /info statusFlags). Captured over one full
  start->stop cycle; see tests/fixtures/ for the raw records.
- Which service updates first: _airplay leads _raop by ~100ms consistently,
  on both the start transition (99ms) and the stop transition (101ms).
  _airplay is the primary signal; _raop is a close, reliable cross-check.
  /info is only as fresh as its poll interval (used as the self-healing
  fallback, not the primary path).
- Cross-source agreement: mostly yes, but NOT always instantaneous — during
  the capture, a single /info poll read statusFlags=4 (idle) for one sample
  while _airplay/_raop still (or again) reported 0x804, immediately followed
  by a session renegotiation (new gid) and a return to 0x804. This coincided
  with a pause/resume action and validates combine()'s "any source active
  wins" rule: a lone contradicting inactive reading did not need to flap the
  sensor off, because at least one source still said active.
- Play vs pause: NOT distinguishable — both produced identical 0x804. Confirms
  the brief's non-goal (no play/pause distinction) is a hardware limit, not a
  missed feature.
"""

from __future__ import annotations

from dataclasses import dataclass

# Confirmed empirically (see FINDINGS above): streaming sets this bit on top of
# the idle baseline, identically across _airplay flags=, _raop sf=, and /info
# statusFlags=.
AIRPLAY_SF_IN_USE_BIT = 0x800


@dataclass(frozen=True)
class Observation:
    """A single point-in-time reading from one source.

    ``active`` is None when the source could not be interpreted (unknown field,
    parse failure, endpoint unreachable) — callers should treat None as "no
    information", NOT as inactive, so a failed /info poll can't force the sensor
    off while mDNS still says it's on.
    """

    source: str            # "airplay" | "raop" | "info"
    active: bool | None
    raw: str               # raw value, kept for logging/diagnostics


def _txt_to_str(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _parse_int(value: str | None) -> int | None:
    """Parse a TXT/flags value that may be decimal or 0x-prefixed hex."""
    if value is None:
        return None
    value = value.strip()
    try:
        return int(value, 16) if value.lower().startswith("0x") else int(value)
    except ValueError:
        try:
            return int(value, 16)  # bare hex, e.g. "0x804" written as "804"
        except ValueError:
            return None


def from_airplay_txt(txt: dict[bytes | str, bytes | str | None]) -> Observation:
    """Decide activity from an ``_airplay._tcp`` TXT record's status-flags field.

    Reads ``flags=`` (the field this hardware actually sends) falling back to
    ``sf=`` for firmware variants that use the brief's originally-assumed name.
    """
    raw = _txt_to_str(txt.get("flags") or txt.get(b"flags") or txt.get("sf") or txt.get(b"sf"))
    flags = _parse_int(raw)
    if flags is None:
        return Observation("airplay", None, raw or "")
    active = bool(flags & AIRPLAY_SF_IN_USE_BIT)
    return Observation("airplay", active, raw or "")


def from_raop_txt(txt: dict[bytes | str, bytes | str | None]) -> Observation:
    """Decide activity from a ``_raop._tcp`` TXT record's ``sf=`` field.

    Lags _airplay's flags= by ~100ms in captures, but uses the identical bit
    encoding — good as a fast cross-check, not as the primary source.
    """
    raw = _txt_to_str(txt.get("sf") or txt.get(b"sf"))
    flags = _parse_int(raw)
    if flags is None:
        return Observation("raop", None, raw or "")
    active = bool(flags & AIRPLAY_SF_IN_USE_BIT)
    return Observation("raop", active, raw or "")


def from_info_plist(info: dict) -> Observation:
    """Decide activity from the ``/info`` binary-plist ``statusFlags`` field.

    Same bit encoding as the mDNS TXT fields, confirmed by capture. Only as
    fresh as the poll interval, so treat as a fallback cross-check.
    """
    raw = info.get("statusFlags")
    if raw is None:
        return Observation("info", None, "")
    flags = _parse_int(str(raw))
    if flags is None:
        return Observation("info", None, str(raw))
    active = bool(flags & AIRPLAY_SF_IN_USE_BIT)
    return Observation("info", active, str(raw))


def combine(observations: list[Observation]) -> bool | None:
    """Reduce several observations to a single activity verdict.

    Rule: an active reading from *any* source wins (mDNS can lead /info or vice
    versa). Only report inactive when at least one source has an opinion and none
    of them say active. Return None when nobody has any information.
    """
    opinions = [o.active for o in observations if o.active is not None]
    if not opinions:
        return None
    return any(opinions)

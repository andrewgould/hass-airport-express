"""AirPlay activity decision function.

This module maps the raw signals from an AirPort Express — the mDNS TXT records
of its ``_raop._tcp`` / ``_airplay._tcp`` services, and the ``/info`` binary
plist — onto a single boolean: **is a stream currently active?**

╔══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 0 — NOT YET VALIDATED AGAINST REAL HARDWARE                            ║
║                                                                              ║
║  The exact field/bit that reliably indicates "streaming active" on gen-2     ║
║  firmware has NOT been confirmed. The logic below encodes the *hypothesis*   ║
║  from the project brief and MUST be corrected once scripts/phase0_diagnostic ║
║  has captured real start/stop transitions. Until then this returns best-     ║
║  effort guesses and the sensor should not be trusted.                        ║
║                                                                              ║
║  When Phase 0 is done:                                                        ║
║    1. Replace the heuristics below with the confirmed field/bit.             ║
║    2. Drop captured fixtures into tests/fixtures/ and assert on them in      ║
║       tests/test_state.py.                                                   ║
║    3. Document the finding in the FINDINGS block just below.                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

FINDINGS (fill in during Phase 0)
---------------------------------
- Device under test: AirPort Express gen 2, model AirPort10,115,
  fv=p20.78100.3, hostname Theatre-AirPort-Express.local, mDNS name "Court yard"
- Field NAME confirmed: _airplay._tcp has NO ``sf=`` key on this firmware —
  use ``flags=`` instead. _raop._tcp does use ``sf=``. Both read 0x4 while idle.
- Which service updates first/most reliably (_raop vs _airplay): TBD (need
  streaming transition, not just idle snapshot)
- TXT bit meaning idle vs streaming:                              TBD — idle
  value is 0x4 for both flags/sf; need the streaming value to find the bit
- /info statusFlags field + encoding:                             also 0x4
  idle, same value as TXT flags/sf — encoding likely shared
- Do TXT and /info agree? any lag between them?                   TBD
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Hypothesised bit layout (UNCONFIRMED — see Phase 0 banner above) ---------
#
# On _airplay._tcp the ``sf=`` (status flags) TXT value is a hex/int bitfield.
# Community reports for various AirPlay receivers associate a low bit with
# "device in use / audio cable attached / stream active", but the exact bit on
# gen-2 Express firmware is unverified. We keep the mask as a named constant so
# Phase 0 only has to change one number.
AIRPLAY_SF_IN_USE_BIT = 0x800  # PLACEHOLDER — confirm empirically

# On _raop._tcp there is no universally-documented equivalent; the presence /
# absence of the advertisement, or a flags digit, may be the tell. Left as a
# hook for Phase 0.


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

    CONFIRMED (Phase 0, gen-2 Express, firmware p20.78100.3): this hardware's
    ``_airplay._tcp`` record has NO ``sf=`` key — the brief's assumption was for
    a different generation/firmware. The equivalent field here is ``flags=``.
    Both idle values observed so far: ``flags=0x4`` (_airplay) and ``sf=0x4``
    (_raop) — same value, different key name. Kept the ``sf`` lookup as a
    fallback in case other firmware versions do use it.
    """
    raw = _txt_to_str(txt.get("flags") or txt.get(b"flags") or txt.get("sf") or txt.get(b"sf"))
    flags = _parse_int(raw)
    if flags is None:
        return Observation("airplay", None, raw or "")
    active = bool(flags & AIRPLAY_SF_IN_USE_BIT)
    return Observation("airplay", active, raw or "")


def from_raop_txt(txt: dict[bytes | str, bytes | str | None]) -> Observation:
    """Decide activity from a ``_raop._tcp`` TXT record.

    PLACEHOLDER: no confirmed field yet. Returns None (no information) so it
    never overrides the _airplay signal until Phase 0 tells us what to read.
    """
    # Keep the raw record around so the diagnostic script / logs can show it.
    raw = ",".join(
        f"{_txt_to_str(k)}={_txt_to_str(v)}" for k, v in txt.items()
    )
    return Observation("raop", None, raw)


def from_info_plist(info: dict) -> Observation:
    """Decide activity from the ``/info`` binary-plist ``statusFlags`` field."""
    raw = info.get("statusFlags")
    if raw is None:
        return Observation("info", None, "")
    flags = _parse_int(str(raw))
    if flags is None:
        return Observation("info", None, str(raw))
    active = bool(flags & AIRPLAY_SF_IN_USE_BIT)  # PLACEHOLDER — may differ from mDNS
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

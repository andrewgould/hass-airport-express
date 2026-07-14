# Test fixtures

Captured 2026-07-14 during **Phase 0** from a real AirPort Express gen 2
(model AirPort10,115, fv=p20.78100.3), during one full idle -> streaming ->
idle cycle. See the FINDINGS block in `../../src/hass_airport_express/state.py`
for the full writeup.

- `airplay_idle.json` / `airplay_streaming.json` — `_airplay._tcp` TXT record
  (`flags=0x4` idle, `flags=0x804` streaming)
- `raop_idle.json` / `raop_streaming.json` — `_raop._tcp` TXT record
  (`sf=0x4` idle, `sf=0x804` streaming)
- `info_idle.json` / `info_streaming.json` — `/info` plist, trimmed to the
  fields the decision function reads (`statusFlags=4` idle, `=2052` streaming)

If you capture from another device/firmware and it disagrees with these
values, add new fixtures rather than replacing these — firmware variance is
exactly what the fallback field lookups in `state.py` (`flags=` / `sf=`) exist
to handle.

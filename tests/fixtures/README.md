# Test fixtures

Captured during **Phase 0** from real AirPort Express hardware. Drop the raw TXT
records and `/info` plist dumps here (idle vs streaming) so the decision-function
tests in `../test_state.py` can assert against real data instead of guesses.

Suggested files (create during Phase 0):

- `airplay_idle.json` — `_airplay._tcp` TXT record while idle
- `airplay_streaming.json` — `_airplay._tcp` TXT record while a stream is active
- `raop_idle.json` / `raop_streaming.json` — same for `_raop._tcp`
- `info_idle.plist` / `info_streaming.plist` — raw `/info` bodies

Keep them small and anonymised (strip any MAC/serial you'd rather not publish).

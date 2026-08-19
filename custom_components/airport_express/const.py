"""Constants for the AirPort Express AirPlay activity integration."""

from __future__ import annotations

DOMAIN = "airport_express"
PLATFORMS = ["binary_sensor"]

CONF_MDNS_NAME = "mdns_name"
CONF_OFF_DELAY = "off_delay_seconds"
CONF_CONFIRM_OBSERVATIONS = "confirm_observations"
CONF_INFO_POLL_SECONDS = "info_poll_seconds"

# Short enough that an automation reacts promptly, long enough to ride out the
# handshake blips seen in the Phase 0 captures. A longer "has the music really
# stopped" wait belongs in the automation, where it's visible and tunable --
# not buried in here. See README.
DEFAULT_OFF_DELAY = 10
DEFAULT_CONFIRM_OBSERVATIONS = 2
DEFAULT_INFO_POLL_SECONDS = 45

SIGNAL_UPDATE = "airport_express_update_{}"

from __future__ import annotations

# Button platform intentionally empty.
# Power control (Wake/Standby/Reboot) was removed because the GoldHEN
# HTTP API endpoints proved unreliable. The platform stub is kept so
# HACS does not complain about a missing module if the key is ever
# re-added to PLATFORMS in the future.
#
# BinLoader payload delivery is handled via the send_payload service
# registered in __init__.py.

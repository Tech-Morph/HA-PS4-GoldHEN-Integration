"""PS4 game database handler."""

import aioftp
import sqlite3
import os
import logging

from .const import DEFAULT_FTP_PORT, APP_DB_REMOTE, APP_DB_LOCAL

_LOGGER = logging.getLogger(**name**)

class PS4GameDB:

```
def __init__(self, hass, host):

    self.hass = hass
    self.host = host
    self.local_path = hass.config.path(APP_DB_LOCAL)
    self.game_map = {}

async def refresh(self):

    try:

        async with aioftp.Client.context(
            self.host,
            DEFAULT_FTP_PORT,
            "anonymous",
            "anonymous",
        ) as ftp:

            await ftp.download(APP_DB_REMOTE, self.local_path)

        await self.hass.async_add_executor_job(self._load_db)

        _LOGGER.info("PS4 app.db downloaded")

    except Exception as err:

        _LOGGER.warning("Failed downloading app.db: %s", err)

def _load_db(self):

    if not os.path.exists(self.local_path):
        return

    conn = sqlite3.connect(self.local_path)
    cursor = conn.cursor()

    try:

        cursor.execute("SELECT titleId, title FROM tbl_appbrowse")

        rows = cursor.fetchall()

        self.game_map = {row[0]: row[1] for row in rows}

    except Exception as err:

        _LOGGER.warning("DB parse failed: %s", err)

    finally:

        conn.close()

def resolve(self, title_id):

    return self.game_map.get(title_id)
```

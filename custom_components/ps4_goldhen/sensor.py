"""Sensor platform for PS4 GoldHEN."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import *

async def async_setup_entry(
hass: HomeAssistant,
entry: ConfigEntry,
async_add_entities: AddEntitiesCallback,
):

```
coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

async_add_entities(
    [
        PS4CurrentGameSensor(coordinator, entry),
        PS4CPUTempSensor(coordinator, entry),
    ]
)
```

class BasePS4Sensor(CoordinatorEntity, SensorEntity):

```
def __init__(self, coordinator, entry):

    super().__init__(coordinator)
    self.entry = entry

@property
def device_info(self):

    return {
        "identifiers": {(DOMAIN, self.entry.data[CONF_HOST])},
        "name": "PlayStation 4",
        "manufacturer": "Sony",
        "model": "PS4 GoldHEN",
    }
```

class PS4CurrentGameSensor(BasePS4Sensor):

```
_attr_name = "Current Game"
_attr_icon = "mdi:sony-playstation"

def __init__(self, coordinator, entry):

    super().__init__(coordinator, entry)

    self._attr_unique_id = f"{entry.data[CONF_HOST]}_current_game"

@property
def native_value(self):

    return self.coordinator.data.get(SENSOR_CURRENT_GAME)

@property
def extra_state_attributes(self):

    return {
        "title_id": self.coordinator.data.get(SENSOR_TITLE_ID),
        "game_name": self.coordinator.data.get(SENSOR_GAME_NAME),
        "cover": self.coordinator.data.get(SENSOR_GAME_COVER),
    }
```

class PS4CPUTempSensor(BasePS4Sensor):

```
_attr_name = "CPU Temperature"
_attr_native_unit_of_measurement = "°C"

def __init__(self, coordinator, entry):

    super().__init__(coordinator, entry)

    self._attr_unique_id = f"{entry.data[CONF_HOST]}_cpu_temp"

@property
def native_value(self):

    return self.coordinator.data.get(SENSOR_CPU_TEMP)
```

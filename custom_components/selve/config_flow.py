from __future__ import annotations

import asyncio
import logging
from typing import Optional, List

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# ----------------------------
# Helpers (laufen im Executor)
# ----------------------------

def _list_serial_ports() -> List[str]:
    """Synchroner Port-Scan (im Executor aufrufen!)."""
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception as e:
        # Fehlermeldung nur zurückgeben, Scan aber nicht hart scheitern lassen
        return []

def _test_open_serial(port: str, baudrate: int = 9600, timeout: float = 1.0) -> Optional[str]:
    """Versucht, den angegebenen seriellen Port testweise zu öffnen.
    Gibt None bei Erfolg zurück, sonst den Fehlertext.
    """
    try:
        from serial import Serial
        s = Serial(port=port, baudrate=baudrate, timeout=timeout)
        try:
            s.close()
        except Exception:
            pass
        return None
    except Exception as e:
        return str(e)


class SelveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow für Selve NG – nur Validierung & Speichern, kein Gateway-Aufbau hier."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Erster (und einziger) Schritt: Port auswählen/prüfen und speichern."""
        # Ports asynchron ermitteln (kein Blocking im Event-Loop)
        try:
            ports = await self.hass.async_add_executor_job(_list_serial_ports)
        except Exception as e:
            _LOGGER.exception("Selve: Fehler beim Auflisten der Ports: %s", e)
            ports = []

        # Schema: Port ist Pflicht (Rest übernimmt die Integration später)
        # Wenn Ports gefunden, nutzen wir ein Auswahlfeld; sonst Freitext
        if ports:
            schema = vol.Schema(
                {
                    vol.Required("port"): vol.In(ports),
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required("port"): cv.string,
                }
            )

        # Wenn noch keine Eingaben: Formular anzeigen
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema)

        # Preflight-Open im Executor (liefert None bei OK oder Fehlermeldung)
        user_port = user_input.get("port")
        if not user_port:
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors={"base": "invalid_port"},
            )

        _LOGGER.debug("Selve: Preflight-Test für Port %s", user_port)
        try:
            err = await self.hass.async_add_executor_job(_test_open_serial, user_port, 9600, 1.0)
        except Exception as e:
            _LOGGER.exception("Selve: Unerwarteter Fehler beim Port-Test: %s", e)
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors={"base": "cannot_connect"},
            )

        if err:
            # Typische Ursache: Port belegt oder USB/Parameterproblem
            _LOGGER.error("Selve: COM-Port-Fehler beim Preflight: %s", err)
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors={"base": "cannot_connect"},
            )

        # Alles gut → Eintrag erstellen (eigentliches Setup erfolgt in async_setup_entry)
        _LOGGER.info("Selve: Port validiert, erstelle Konfigurationseintrag.")
        return self.async_create_entry(title="Selve NG", data={"port": user_port})

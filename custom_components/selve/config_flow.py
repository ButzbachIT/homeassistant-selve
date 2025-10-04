from __future__ import annotations
import logging
import asyncio
from typing import Optional

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Monkey Patch: Fix für Upstream-Bug ('NoneType' object has no attribute 'close')
# ---------------------------------------------------------------------------
try:
    import selve as _selve
    _orig_setup = getattr(_selve.Gateway, "setup", None)

    if asyncio.iscoroutinefunction(_orig_setup):
        async def _safe_setup(self, *args, **kwargs):
            # defensiv: alten Serial-Port schließen, falls vorhanden
            ser = getattr(self, "_serial", None)
            if ser is not None:
                try:
                    ser.close()
                except Exception as e:
                    _LOGGER.warning("Selve: Fehler beim Schließen des vorherigen Serial-Ports: %s", e)

            try:
                return await _orig_setup(self, *args, **kwargs)
            except AttributeError as e:
                if "has no attribute 'close'" in str(e):
                    _LOGGER.error("Selve: Upstream-NoneType.close()-Crash vermieden → Verbindung fehlgeschlagen")
                    return False
                raise

        _selve.Gateway.setup = _safe_setup  # type: ignore[attr-defined]
        _LOGGER.debug("Selve: Monkey-Patch für Gateway.setup() angewendet (Python 3.13 Fix).")
    else:
        _LOGGER.debug("Selve: Gateway.setup() ist keine async-Funktion, Patch übersprungen.")
except Exception as e:
    _LOGGER.debug("Selve: Monkey-Patch konnte nicht angewendet werden: %s", e)

# ---------------------------------------------------------------------------
# Helper: Preflight-Test für serielle Verbindung (synchron in Executor)
# ---------------------------------------------------------------------------
def _test_open_serial(port: str, baudrate: int = 9600, timeout: float = 1.0) -> Optional[str]:
    """Versucht, den angegebenen seriellen Port testweise zu öffnen."""
    try:
        from serial import Serial
        s = Serial(port=port, baudrate=baudrate, timeout=timeout)
        try:
            s.close()
        except Exception:
            pass
        return None  # alles ok
    except Exception as e:
        return str(e)  # Fehlertext zurückgeben


# ---------------------------------------------------------------------------
# Config Flow für Home Assistant
# ---------------------------------------------------------------------------
class SelveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle configuration flow for Selve NG."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle initial step of the config flow."""
        _LOGGER.debug("Selve: Starte async_step_user() mit Eingabe: %s", user_input)

        gateway = self.hass.data.get(DOMAIN, {}).get("gateway") if self.hass.data.get(DOMAIN) else None
        if gateway is None:
            try:
                import selve
                gateway = selve.Gateway()
            except Exception as e:
                _LOGGER.exception("Selve: Konnte Gateway-Objekt nicht erzeugen: %s", e)
                return self.async_abort(reason="unknown_error")

        # 1️⃣ Ports abrufen (ohne Event-Loop zu blockieren)
        try:
            ports = await self.hass.async_add_executor_job(gateway.list_ports)
        except Exception as e:
            _LOGGER.warning("Selve: Fehler beim Auflisten der Ports: %s", e)
            ports = []

        # Wenn keine Ports gefunden, trotzdem manuelle Eingabe erlauben
        if not ports:
            _LOGGER.info("Selve: Keine Ports gefunden — manuelle Eingabe zulassen.")

        # 2️⃣ Wenn Nutzer Port eingibt → Preflight-Test
        user_port = None
        if user_input and "port" in user_input:
            user_port = user_input["port"]

        if user_port:
            _LOGGER.debug("Selve: Preflight-Test für Port %s", user_port)
            err = await self.hass.async_add_executor_job(_test_open_serial, user_port, 9600, 1.0)
            if err:
                _LOGGER.error("Selve: COM-Port-Fehler: %s", err)
                return self.async_abort(reason="cannot_connect")

        # 3️⃣ Gateway-Setup robust ausführen
        try:
            ok = await gateway.setup(discover=False, fromConfigFlow=True)
        except Exception as e:
            _LOGGER.exception("Selve: setup() hat einen Fehler ausgelöst: %s", e)
            return self.async_abort(reason="cannot_connect")

        if ok is False:
            _LOGGER.error("Selve: setup() schlug fehl → Verbindung konnte nicht hergestellt werden.")
            return self.async_abort(reason="cannot_connect")

        _LOGGER.info("Selve: setup() erfolgreich — Integration wird erstellt.")
        return self.async_create_entry(title="Selve NG", data=user_input)

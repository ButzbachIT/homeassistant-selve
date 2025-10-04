"""Config flow for selvetest integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from selve import Selve
from selve.util.errors import PortError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

port = "Unknown"


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for selve."""

    VERSION = 1

    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Give initial instructions for setup."""

        errors = {}
        data = {}

        if user_input is not None:
            if user_input["autodiscovery"] is True:
                try:
                    gateway = Selve(None, discover=False, logger=_LOGGER)
                    try:
                        ok = await gateway.setup(discover=False, fromConfigFlow=True)
                    except Exception as e:
                        _LOGGER.exception("Selve: setup() raised during config flow: %s", e)
                        return self.async_abort(reason="cannot_connect")
                    
                    if ok is False:
                        _LOGGER.error("Selve: setup() returned False (cannot connect)")
                        return self.async_abort(reason="cannot_connect")
                    data[CONF_PORT] = gateway._port
                    return self.async_create_entry(title="Selve Gateway", data=data)
                except PortError:
                    _LOGGER.exception("Invalid port")
                    errors["base"] = "invalid_port"

                except ConnectionFailedError:
                    _LOGGER.exception("Invalid port")
                    errors["base"] = "invalid_port"

                except AlreadyConfigured:
                    return self.async_abort(reason="already_configured")
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"

                except GatewayNotReadyError:
                    _LOGGER.exception("Gateway not ready")
                    errors["base"] = "gateway_not_ready"

                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"

            else:
                try:
                    gateway = Selve(None, discover=False, logger=_LOGGER)

                    if user_input[CONF_PORT] == "None":
                        _LOGGER.exception("Invalid port")
                        errors["base"] = "invalid_port"
                    else:
                        if await gateway.check_port(user_input[CONF_PORT]):
                            gateway = Selve(
                                user_input[CONF_PORT], discover=False, logger=_LOGGER
                            )
                            await gateway.setup(discover=False, fromConfigFlow=True)
                            data[CONF_PORT] = user_input[CONF_PORT]
                            return self.async_create_entry(
                                title="Selve Gateway", data=data
                            )
                        else:
                            _LOGGER.exception("Invalid port")
                            errors["base"] = "invalid_port"

                except PortError:
                    _LOGGER.exception("Invalid port")
                    errors["base"] = "invalid_port"

                except ConnectionFailedError:
                    _LOGGER.exception("Invalid port")
                    errors["base"] = "invalid_port"

                except AlreadyConfigured:
                    return self.async_abort(reason="already_configured")
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"

                except GatewayNotReadyError:
                    _LOGGER.exception("Gateway not ready")
                    errors["base"] = "gateway_not_ready"

                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"

        list = []
        list.append("None")
        gateway = Selve(None, discover=False, logger=_LOGGER)
        ports = gateway.list_ports()
        for p in ports:
            list.append(p.device)
        data_schema = {
            vol.Required("autodiscovery", default=True): bool,
            vol.Optional(CONF_PORT, default="None"): vol.In(list),
        }

        return self.async_show_form(
            step_id="user", errors=errors, data_schema=vol.Schema(data_schema)
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "switch_dir",
                        default=self.config_entry.options.get("switch_dir", False),
                    ): bool
                }
            ),
        )


class AlreadyConfigured(HomeAssistantError):
    """Error to indicate this device is already configured."""


class GatewayNotReadyError(HomeAssistantError):
    """Error to indicate we cannot connect."""


class ConnectionFailedError(HomeAssistantError):
    """Error to indicate there is invalid auth."""

diff --git a/custom_components/selve/config_flow.py b/custom_components/selve/config_flow.py
index 2f1aa12..ac77c65 100644
--- a/custom_components/selve/config_flow.py
+++ b/custom_components/selve/config_flow.py
@@ -1,10 +1,67 @@
 from __future__ import annotations
+import logging
+import asyncio
+from typing import Optional
 from homeassistant import config_entries
 from homeassistant.core import HomeAssistant
 from .const import DOMAIN
+_LOGGER = logging.getLogger(__name__)
+
+# --- begin: defensive monkey-patch for upstream "selve" lib (NoneType.close crash) ---
+try:
+    import selve as _selve
+    _orig_setup = getattr(_selve.Gateway, "setup", None)
+    if asyncio.iscoroutinefunction(_orig_setup):
+        async def _safe_setup(self, *args, **kwargs):
+            ser = getattr(self, "_serial", None)
+            if ser is not None:
+                try:
+                    ser.close()
+                except Exception as e:
+                    _LOGGER.warning("Selve: error while closing previous serial: %s", e)
+            try:
+                return await _orig_setup(self, *args, **kwargs)
+            except AttributeError as e:
+                if "has no attribute 'close'" in str(e):
+                    _LOGGER.error("Selve: avoided upstream NoneType.close() crash; treating as connection failure")
+                    return False
+                raise
+        _selve.Gateway.setup = _safe_setup  # type: ignore[attr-defined]
+        _LOGGER.debug("Selve: applied defensive monkey-patch for Gateway.setup()")
+except Exception as e:
+    _LOGGER.debug("Selve: could not apply monkey-patch: %s", e)
+# --- end: defensive monkey-patch ---
+
+# Helper: blockierendes Test-Öffnen im Executor ausführen
+def _test_open_serial(port: str, baudrate: int = 9600, timeout: float = 1.0) -> Optional[str]:
+    try:
+        from serial import Serial
+        s = Serial(port=port, baudrate=baudrate, timeout=timeout)
+        try:
+            s.close()
+        except Exception:
+            pass
+        return None  # OK
+    except Exception as e:
+        return str(e)  # Fehlertext zurück
@@ -37,14 +94,41 @@ class SelveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
-        # bisher: Ports scannen (blockiert Event-Loop)
-        # ports = gateway.list_ports()
+        # 1) Optional: Ports im Executor scannen (kein Blocking). Oder Scan ganz überspringen.
+        try:
+            ports = await self.hass.async_add_executor_job(gateway.list_ports)
+        except Exception as e:
+            _LOGGER.exception("Selve: listing serial ports failed: %s", e)
+            ports = []
 
         # UI/Fortschritt NICHT vom Scan abhängig machen: manuelle Eingabe erlauben
         # ...
 
-        # ok = await gateway.setup(discover=False, fromConfigFlow=True)
+        # 2) Wenn Nutzer bereits einen Port eingegeben hat, Preflight-Test ausführen
+        user_port = None
+        if user_input and "port" in user_input:
+            user_port = user_input["port"]
+
+        if user_port:
+            err = await self.hass.async_add_executor_job(_test_open_serial, user_port, 9600, 1.0)
+            if err:
+                _LOGGER.error("Error at com port: %s", err)
+                return self.async_abort(reason="cannot_connect")
+
+        # 3) Eigentliches Setup: robust mit Try/Except
+        try:
+            ok = await gateway.setup(discover=False, fromConfigFlow=True)
+        except Exception as e:
+            _LOGGER.exception("Selve: setup() raised during config flow: %s", e)
+            return self.async_abort(reason="cannot_connect")
+
+        if ok is False:
+            _LOGGER.error("Selve: setup() returned False (cannot connect)")
+            return self.async_abort(reason="cannot_connect")
 
         return self.async_create_entry(title="Selve NG", data=user_input)


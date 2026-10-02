"""Loopback FTP and complete-module setup tests; no PS4 access required."""
import asyncio
import contextlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/ps4_goldhen"


def load_integration():
    def module(name, **attrs):
        m = ModuleType(name)
        m.__dict__.update(attrs)
        return m

    class Coordinator:
        def __init__(self, hass, logger, *, update_method, **kwargs):
            self.update_method = update_method
            self.data = None
        async def async_config_entry_first_refresh(self):
            self.data = await self.update_method()
        def async_set_updated_data(self, data):
            self.data = data

    class Flow:
        def __init_subclass__(cls, **kwargs):
            pass

    api = module("homeassistant.components.websocket_api",
                 websocket_command=lambda schema: lambda fn: fn,
                 async_response=lambda fn: fn, async_register_command=lambda *a: None)
    vol = module("voluptuous", Schema=lambda value: value,
                 Required=lambda value, **kw: value, Optional=lambda value, **kw: value,
                 All=lambda *a: None, Coerce=lambda *a: None, Range=lambda **kw: None)
    fake = {
        "voluptuous": vol,
        "aiohttp": module("aiohttp", web=SimpleNamespace()),
        "homeassistant": module("homeassistant"),
        "homeassistant.components": module("homeassistant.components",
            websocket_api=api, panel_custom=SimpleNamespace()),
        "homeassistant.components.websocket_api": api,
        "homeassistant.components.frontend": module("homeassistant.components.frontend", StaticPathConfig=object),
        "homeassistant.components.http": module("homeassistant.components.http", HomeAssistantView=object),
        "homeassistant.config_entries": module("homeassistant.config_entries", ConfigEntry=object,
            ConfigFlow=Flow, OptionsFlow=Flow),
        "homeassistant.core": module("homeassistant.core", HomeAssistant=object,
            ServiceCall=object, callback=lambda fn: fn),
        "homeassistant.data_entry_flow": module("homeassistant.data_entry_flow", FlowResult=dict),
        "homeassistant.exceptions": module("homeassistant.exceptions", HomeAssistantError=RuntimeError),
        "homeassistant.helpers": module("homeassistant.helpers"),
        "homeassistant.helpers.update_coordinator": module("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=Coordinator),
    }
    name = "_ps4_issue1_test"
    old = {k: v for k, v in sys.modules.items() if k == name or k.startswith(name + ".")}
    with patch.dict(sys.modules, fake):
        try:
            spec = importlib.util.spec_from_file_location(name, COMPONENT / "__init__.py",
                submodule_search_locations=[str(COMPONENT)])
            integration = importlib.util.module_from_spec(spec)
            sys.modules[name] = integration
            spec.loader.exec_module(integration)
            flow_spec = importlib.util.spec_from_file_location(name + ".config_flow", COMPONENT / "config_flow.py")
            flow = importlib.util.module_from_spec(flow_spec)
            sys.modules[flow_spec.name] = flow
            flow_spec.loader.exec_module(flow)
            transport = sys.modules[name + ".ftp_telemetry"]
            return integration, flow, transport
        finally:
            for key in list(sys.modules):
                if key == name or key.startswith(name + "."):
                    del sys.modules[key]
            sys.modules.update(old)


class LocalFTP:
    def __init__(self, mode="ok", body=b'{"cpu_temp":63}', password=False, multiline=False):
        self.mode, self.body = mode, body
        self.password, self.multiline = password, multiline
        self.tasks, self.writers, self.servers = set(), [], []
        self.transfer = asyncio.Event()
        self.commands = []

    async def __aenter__(self):
        self.data_server = await asyncio.start_server(self.data_client, "127.0.0.1", 0)
        self.control_server = await asyncio.start_server(self.control_client, "127.0.0.1", 0)
        self.servers = [self.data_server, self.control_server]
        self.port = self.control_server.sockets[0].getsockname()[1]
        self.data_port = self.data_server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        for server in self.servers:
            server.close()
        for server in self.servers:
            await server.wait_closed()
        for writer in self.writers:
            writer.close()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        for writer in self.writers:
            with contextlib.suppress(OSError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 0.2)

    async def data_client(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.append(writer)
        try:
            await self.transfer.wait()
            if self.mode in ("missing", "stall"):
                await reader.read()
            else:
                writer.write(self.body)
                await writer.drain()
        finally:
            writer.close()
            self.tasks.discard(task)

    async def control_client(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.append(writer)
        try:
            if self.mode == "banner_stall":
                await reader.read()
                return
            writer.write(b"220-test server\r\nhello\r\n220 ready\r\n" if self.multiline else b"220 ready\r\n")
            await writer.drain()
            while raw := await reader.readline():
                command = raw.decode().strip()
                self.commands.append(command)
                if command.startswith("USER "):
                    response = b"331 password\r\n" if self.password else b"230 logged in\r\n"
                elif command.startswith("PASS "):
                    response = b"230 logged in\r\n"
                elif command == "TYPE I":
                    response = b"200 binary\r\n"
                elif command == "PASV":
                    response = f"227 (192,0,2,1,{self.data_port // 256},{self.data_port % 256})\r\n".encode()
                elif command.startswith("RETR "):
                    self.transfer.set()
                    if self.mode == "missing":
                        response = b"550 file unavailable\r\n"
                    elif self.mode in ("stall", "completion_stall"):
                        response = b"150 opening\r\n"
                    else:
                        response = b"150 opening\r\n226 complete\r\n"
                else:
                    response = b"500 unexpected\r\n"
                writer.write(response)
                await writer.drain()
        finally:
            writer.close()
            self.tasks.discard(task)


class SocketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.integration, self.flow, self.transport = load_integration()

    async def fetch(self, server):
        return await asyncio.wait_for(self.transport.async_fetch_telemetry(
            "127.0.0.1", server.port, "/data/GoldHEN/ps4_state.json",
            operation_timeout=0.08, total_timeout=0.4), 1)

    async def test_real_socket_missing_file_with_idle_data_connection(self):
        async with LocalFTP("missing") as server:
            result = await self.fetch(server)
            self.assertEqual(result.status, "ftp_550")
            self.assertTrue(result.ftp_reachable)
            self.assertIsNone(result.values)

    async def test_real_socket_stalled_data(self):
        async with LocalFTP("stall") as server:
            result = await self.fetch(server)
            self.assertEqual(result.status, "timeout")
            self.assertTrue(result.ftp_reachable)

    async def test_real_socket_stalled_completion(self):
        async with LocalFTP("completion_stall") as server:
            self.assertEqual((await self.fetch(server)).status, "timeout")

    async def test_real_socket_stalled_banner(self):
        async with LocalFTP("banner_stall") as server:
            result = await self.fetch(server)
            self.assertEqual(result.status, "timeout")
            self.assertFalse(result.ftp_reachable)

    async def test_real_socket_password_multiline_and_untrusted_pasv_host(self):
        async with LocalFTP(password=True, multiline=True) as server:
            result = await self.fetch(server)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.values["cpu_temp"], 63)
            self.assertIn("PASS anonymous@", server.commands)

    async def test_real_socket_invalid_json(self):
        for body in (b"", b"{", b"[]", b"{}", b"\xff"):
            with self.subTest(body=body):
                async with LocalFTP(body=body) as server:
                    result = await self.fetch(server)
                    self.assertEqual(result.status, "invalid_json")
                    self.assertTrue(result.ftp_reachable)

    async def test_deep_json_does_not_escape_first_refresh(self):
        async with LocalFTP() as server:
            with patch.object(self.transport.json, "loads", side_effect=RecursionError("nested JSON")):
                self.assertEqual((await self.fetch(server)).status, "invalid_json")

    async def test_real_socket_cancellation_propagates(self):
        async with LocalFTP("stall") as server:
            task = asyncio.create_task(self.transport.async_fetch_telemetry(
                "127.0.0.1", server.port, "/state.json"))
            await asyncio.wait_for(server.transfer.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_complete_module_offline_poll_returns_data(self):
        hass = SimpleNamespace(data={})
        root = self.integration._ensure_domain_root(hass)
        root["entry"] = {"klog_data": {"current_game": "CUSA00001", "cpu_temp": 63}}
        with patch.object(self.transport.asyncio, "open_connection", side_effect=OSError("offline")):
            result = await self.integration._poll_ftp_json("ps4.test", 2121, "entry", hass, object())
        self.assertFalse(result["ftp_reachable"])
        self.assertEqual(result["telemetry_status"], "connection_error")
        self.assertIsNone(result["cpu_temp"])
        self.assertEqual(result["current_game"], "CUSA00001")

    async def test_passive_connection_failure_preserves_authenticated_ftp(self):
        class Reader:
            def __init__(self):
                self.lines = iter([b"220 ready\r\n", b"230 ok\r\n", b"200 binary\r\n", b"227 (0,0,0,0,1,1)\r\n"])
            async def readline(self):
                return next(self.lines)
        writer = SimpleNamespace(write=lambda value: None, drain=AsyncMock(),
            close=lambda: None, wait_closed=AsyncMock(), get_extra_info=lambda name: ("127.0.0.1", 2121))
        with patch.object(self.transport.asyncio, "open_connection",
                side_effect=[(Reader(), writer), OSError("passive refused")]):
            result = await self.transport.async_fetch_telemetry("ps4.test", 2121, "/state.json")
        self.assertEqual(result.status, "connection_error")
        self.assertTrue(result.ftp_reachable)

    async def test_tcp_probe_close_is_bounded(self):
        async def never_close():
            await asyncio.Event().wait()
        writer = SimpleNamespace(close=lambda: None, wait_closed=never_close)
        with patch.object(self.flow.asyncio, "open_connection", AsyncMock(return_value=(object(), writer))):
            self.assertTrue(await asyncio.wait_for(self.flow._tcp_reachable("ps4.test", 2121), 0.5))

    async def test_tcp_probe_preserves_cancellation(self):
        ready = asyncio.Event()
        async def never_connect(*args):
            ready.set()
            await asyncio.Event().wait()
        with patch.object(self.flow.asyncio, "open_connection", never_connect):
            task = asyncio.create_task(self.flow._tcp_reachable("ps4.test", 2121))
            await ready.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_complete_setup_module_without_telemetry(self):
        for mode, body, status in (("missing", b"", "ftp_550"), ("stall", b"", "timeout"),
                                  ("ok", b"{", "invalid_json"), ("ok", b'{"cpu_temp":63}', "ok")):
            with self.subTest(mode=mode, status=status):
                async with LocalFTP(mode, body) as server:
                    hass = SimpleNamespace(data={},
                        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
                        services=SimpleNamespace(has_service=lambda *a: True))
                    global_state = self.integration._global(hass)
                    for key in global_state:
                        global_state[key] = True
                    tasks = []
                    def background(hass, coro, *, name):
                        tasks.append(name)
                        coro.close()
                        return SimpleNamespace(done=lambda: True)
                    entry = SimpleNamespace(entry_id="entry", data={"ps4_host": "127.0.0.1", "ftp_port": server.port},
                        async_create_background_task=background, async_on_unload=lambda callback: None,
                        add_update_listener=lambda fn: lambda: None)
                    async def bounded_fetch(*args):
                        return await self.transport.async_fetch_telemetry(*args, operation_timeout=0.08, total_timeout=0.4)
                    with patch.object(self.integration, "async_fetch_telemetry", bounded_fetch):
                        self.assertTrue(await asyncio.wait_for(self.integration.async_setup_entry(hass, entry), 1))
                    data = hass.data["ps4_goldhen"]["entry"]["coordinator"].data
                    self.assertEqual(data["telemetry_status"], status)
                    self.assertTrue(data["ftp_reachable"])
                    self.assertEqual(len(tasks), 2)
                    hass.config_entries.async_forward_entry_setups.assert_awaited_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)

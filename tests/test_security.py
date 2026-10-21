"""Admin-only panel/commands/views, send_payload limits, and a cover view that never opens FTP; no PS4 access required."""
import asyncio
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/ps4_goldhen"
REGISTERED_COMMANDS = []


class Response:
    def __init__(self, *, text=None, body=None, status=200, content_type=None, headers=None):
        self.text, self.body, self.status = text, body, status


class HTTPFound(Exception):
    def __init__(self, location):
        super().__init__(location)
        self.location = location


def load_integration():
    def module(name, **attrs):
        m = ModuleType(name)
        m.__dict__.update(attrs)
        return m

    def mark(attr):
        def decorate(fn):
            setattr(fn, attr, True)
            return fn
        return decorate

    class Flow:
        def __init_subclass__(cls, **kwargs):
            pass

    api = module("homeassistant.components.websocket_api",
                 websocket_command=lambda schema: mark("_ws_command"),
                 require_admin=mark("_admin_only"), async_response=lambda fn: fn,
                 async_register_command=lambda hass, fn: REGISTERED_COMMANDS.append(fn),
                 ActiveConnection=object)
    vol = module("voluptuous", Schema=lambda value: value,
                 Required=lambda value, **kw: value, Optional=lambda value, **kw: value,
                 All=lambda *a: None, Coerce=lambda *a: None, Range=lambda **kw: None)
    web = SimpleNamespace(Response=Response, HTTPFound=HTTPFound, Request=object,
                          json_response=lambda data: Response(status=200))
    fake = {
        "voluptuous": vol,
        "aiohttp": module("aiohttp", web=web),
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
        "homeassistant.exceptions": module("homeassistant.exceptions", HomeAssistantError=RuntimeError),
        "homeassistant.helpers": module("homeassistant.helpers"),
        "homeassistant.helpers.update_coordinator": module("homeassistant.helpers.update_coordinator",
            DataUpdateCoordinator=object),
    }
    name = "_ps4_security_test"
    old = {k: v for k, v in sys.modules.items() if k == name or k.startswith(name + ".")}
    with patch.dict(sys.modules, fake):
        try:
            spec = importlib.util.spec_from_file_location(name, COMPONENT / "__init__.py",
                submodule_search_locations=[str(COMPONENT)])
            integration = importlib.util.module_from_spec(spec)
            sys.modules[name] = integration
            spec.loader.exec_module(integration)
            ws_spec = importlib.util.spec_from_file_location(name + ".websocket", COMPONENT / "websocket.py")
            websocket = importlib.util.module_from_spec(ws_spec)
            sys.modules[ws_spec.name] = websocket
            ws_spec.loader.exec_module(websocket)
            return integration, websocket, sys.modules[name + ".payload_target"]
        finally:
            for key in list(sys.modules):
                if key == name or key.startswith(name + "."):
                    del sys.modules[key]
            sys.modules.update(old)


class Request(dict):
    def __init__(self, hass, *, admin, query=None, multipart=None):
        super().__init__(hass_user=SimpleNamespace(is_admin=admin))
        self.app = {"hass": hass}
        self.query = query or {}
        if multipart is not None:
            self.multipart = multipart


class Coordinator:
    def __init__(self):
        self.data, self.updates = {}, 0

    def async_set_updated_data(self, data):
        self.data, self.updates = data, self.updates + 1


def executor_hass(data=None):
    async def job(fn, *args):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)
    return SimpleNamespace(data=data if data is not None else {}, async_add_executor_job=job)


class AdminOnlyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        REGISTERED_COMMANDS.clear()
        self.integration, self.websocket, _ = load_integration()

    async def test_panel_requires_admin(self):
        hass = SimpleNamespace(data={})
        state = self.integration._global(hass)
        state["frontend_registered"] = True
        panel = SimpleNamespace(async_register_panel=AsyncMock())
        with patch.object(self.integration, "panel_custom", panel):
            await self.integration._register_frontend_and_panel_once(hass)
        self.assertIs(panel.async_register_panel.await_args.kwargs["require_admin"], True)

    def test_every_websocket_command_requires_admin(self):
        self.websocket.async_setup(SimpleNamespace())
        self.assertEqual(len(REGISTERED_COMMANDS), 7)
        commands = [*REGISTERED_COMMANDS, self.integration.ws_list_entries, self.integration.ws_list_payloads]
        for module in (self.integration, self.websocket):
            for value in vars(module).values():
                if getattr(value, "_ws_command", False):
                    self.assertIn(value, commands)
        for fn in commands:
            with self.subTest(command=fn.__name__):
                self.assertTrue(getattr(fn, "_admin_only", False))

    async def test_ftp_download_is_admin_only(self):
        view, hass = self.integration.PS4FTPDownloadView(), SimpleNamespace(data={})
        self.assertEqual((await view.get(Request(hass, admin=False, query={"entry_id": "e", "path": "/a"}))).status, 403)
        self.assertEqual((await view.get(Request(hass, admin=True))).status, 400)

    async def test_ftp_upload_is_admin_only(self):
        view, hass = self.integration.PS4FTPUploadView(), SimpleNamespace(data={})
        multipart = AsyncMock(return_value=SimpleNamespace(next=AsyncMock(return_value=None)))
        self.assertEqual((await view.post(Request(hass, admin=False, multipart=multipart))).status, 403)
        multipart.assert_not_awaited()
        self.assertEqual((await view.post(Request(hass, admin=True, multipart=multipart))).status, 400)


class SendPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.integration, _, self.target = load_integration()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.payloads = os.path.realpath(os.path.join(self.tmp.name, "payloads"))
        os.mkdir(self.payloads)
        Path(self.payloads, "info.elf").write_bytes(b"\x7fELF")
        Path(self.tmp.name, "secrets.yaml").write_text("secret")
        os.symlink(os.path.join(self.tmp.name, "secrets.yaml"), os.path.join(self.payloads, "link.bin"))

        entries = [SimpleNamespace(data={"ps4_host": "192.0.2.1", "binloader_port": 9090}),
                   SimpleNamespace(data={"ps4_host": "192.0.2.2", "binloader_port": 9091})]
        registered = {}
        hass = SimpleNamespace(data={},
            config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock(),
                                           async_entries=lambda domain: entries),
            services=SimpleNamespace(has_service=lambda *a: False,
                                     async_register=lambda domain, name, fn, schema: registered.setdefault(name, fn)))
        state = self.integration._global(hass)
        for key in state:
            state[key] = True
        def background(hass, coro, *, name):
            coro.close()
            return SimpleNamespace(done=lambda: True)
        entry = SimpleNamespace(entry_id="first", data=entries[0].data,
            async_create_background_task=background, async_on_unload=lambda callback: None,
            add_update_listener=lambda fn: lambda: None)
        telemetry = AsyncMock(return_value=SimpleNamespace(ftp_reachable=False, values=None, status="refused"))
        class Coord(Coordinator):
            def __init__(self, hass, logger, *, update_method, **kwargs):
                super().__init__()
                self.update_method = update_method
            async def async_config_entry_first_refresh(self):
                self.data = await self.update_method()
        with patch.object(self.integration, "async_fetch_telemetry", telemetry), \
             patch.object(self.integration, "DataUpdateCoordinator", Coord):
            self.assertTrue(await self.integration.async_setup_entry(hass, entry))
        self.handler = registered["send_payload"]
        self.sent = AsyncMock()
        for patcher in (patch.object(self.integration, "_send_bin_tcp", self.sent),
                        patch.object(self.integration, "PAYLOAD_DIR", self.payloads)):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def call(self, **data):
        await self.handler(SimpleNamespace(data={"timeout": 30, **data}))

    async def test_file_name_goes_to_first_console_on_its_port(self):
        await self.call(payload_file="info.elf", binloader_port=1234)
        self.sent.assert_awaited_once_with("192.0.2.1", 9090, os.path.join(self.payloads, "info.elf"), 30)

    async def test_ps4_host_picks_a_configured_console_and_its_port(self):
        await self.call(payload_file="info.elf", ps4_host="192.0.2.2", binloader_port=9999)
        self.sent.assert_awaited_once_with("192.0.2.2", 9091, os.path.join(self.payloads, "info.elf"), 30)

    async def test_unknown_host_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "not a PS4 set up"):
            await self.call(payload_file="info.elf", ps4_host="192.0.2.99")
        self.sent.assert_not_awaited()

    async def test_paths_outside_the_payload_folder_are_refused(self):
        for name in (os.path.join(self.tmp.name, "secrets.yaml"), "../secrets.yaml", "sub/info.elf",
                     "../payloads/info.elf", "..", ".", "", "link.bin"):
            with self.subTest(payload_file=name):
                with self.assertRaisesRegex(RuntimeError, "must be a file name in"):
                    await self.call(payload_file=name)
        self.sent.assert_not_awaited()

    def test_payload_target_without_consoles(self):
        with self.assertRaises(ValueError):
            self.target.payload_target([], None, host_key="h", port_key="p", default_port=9090)
        self.assertEqual(self.target.payload_target([{"h": " 192.0.2.3 "}], None, host_key="h", port_key="p",
                                                    default_port=9090), ("192.0.2.3", 9090))


class CoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.integration, _, _ = load_integration()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.covers = os.path.join(self.tmp.name, "covers")
        os.mkdir(self.covers)
        self.no_ftp = Mock(side_effect=AssertionError("FTP opened"))
        for patcher in (patch.object(self.integration, "COVER_CACHE_DIR", self.covers),
                        patch.object(self.integration, "_fetch_cover_ftp", self.no_ftp)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def entry(self, tid, game_map=None, host="ps4.test"):
        return {"host": host, "ftp_port": 2121, "game_map": game_map or {},
                "klog_data": {"title_id": tid}, "klog_state_machine": self.integration.KlogStateMachine()}

    async def get(self, hass, entry_id, tid):
        return await self.integration.PS4GameCoverView().get(SimpleNamespace(app={"hass": hass}), entry_id, tid)

    async def test_view_serves_cdn_redirect_or_cache_and_never_opens_ftp(self):
        hass = executor_hass({"ps4_goldhen": {"e": self.entry(None, {
            "CUSA00001": {"cdn_cover": "https://image.example/cover.png"}})}})
        with self.assertRaises(HTTPFound) as found:
            await self.get(hass, "e", "cusa00001")
        self.assertEqual(found.exception.location, "https://image.example/cover.png")
        Path(self.covers, "CUSA00002.png").write_bytes(b"png")
        Path(self.tmp.name, "SECRET.png").write_bytes(b"outside the cache")
        Path(self.covers, "ICON0.PNG.png").write_bytes(b"not a title")
        response = await self.get(hass, "e", "CUSA00002")
        self.assertEqual((response.status, response.body), (200, b"png"))
        self.assertEqual((await self.get(hass, "e", "CUSA00003")).status, 404)
        for tid in ("../secret", "CUSA0000", "CUSA000011", "icon0.png"):
            with self.subTest(title_id=tid):
                self.assertEqual((await self.get(hass, "e", tid)).status, 404)
        self.assertEqual((await self.get(hass, "missing", "CUSA00003")).status, 404)
        self.no_ftp.assert_not_called()

    async def test_cache_cover_fetches_once_and_skips_cdn_and_home_screen(self):
        fetch = Mock(return_value=b"png")
        hass = executor_hass({"ps4_goldhen": {
            "game": self.entry("CUSA00001"), "cdn": self.entry("CUSA00002", {"CUSA00002": {"cdn_cover": "https://x"}}),
            "home": self.entry(None), "system": self.entry("NPXS20001")}})
        coordinator = Coordinator()
        with patch.object(self.integration, "_fetch_cover_ftp", fetch):
            for entry_id in ("game", "game", "cdn", "home", "system"):
                await self.integration._cache_cover(hass, entry_id, coordinator)
        fetch.assert_called_once_with("ps4.test", 2121, "/user/appmeta/CUSA00001/icon0.png")
        self.assertEqual(Path(self.covers, "CUSA00001.png").read_bytes(), b"png")
        self.assertEqual(coordinator.updates, 1)

    async def test_failed_fetch_waits_before_the_next_try(self):
        fetch = Mock(side_effect=OSError("refused"))
        hass = executor_hass({"ps4_goldhen": {"e": self.entry("CUSA00001")}})
        now = [1000.0]
        with patch.object(self.integration, "_fetch_cover_ftp", fetch), \
             patch.object(self.integration, "time", SimpleNamespace(monotonic=lambda: now[0])):
            await self.integration._cache_cover(hass, "e", Coordinator())
            await self.integration._cache_cover(hass, "e", Coordinator())
            self.assertEqual(fetch.call_count, 1)
            now[0] += self.integration._COVER_RETRY_SECONDS
            await self.integration._cache_cover(hass, "e", Coordinator())
        self.assertEqual(fetch.call_count, 2)

    async def test_callers_waiting_on_a_failed_fetch_dont_retry_it(self):
        def slow_failure(host, port, path):
            time.sleep(0.05)
            raise OSError("refused")
        fetch = Mock(side_effect=slow_failure)
        hass = executor_hass({"ps4_goldhen": {"e": self.entry("CUSA00001")}})
        with patch.object(self.integration, "_fetch_cover_ftp", fetch):
            await asyncio.gather(*(self.integration._cache_cover(hass, "e", Coordinator()) for _ in range(3)))
        self.assertEqual(fetch.call_count, 1)

    async def test_one_cover_fetch_at_a_time_across_consoles(self):
        active, peak, guard = [0], [0], threading.Lock()
        def slow_fetch(host, port, path):
            with guard:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with guard:
                active[0] -= 1
            return b"png"
        hass = executor_hass({"ps4_goldhen": {"a": self.entry("CUSA00001", host="ps4-a"),
                                              "b": self.entry("CUSA00002", host="ps4-b")}})
        with patch.object(self.integration, "_fetch_cover_ftp", slow_fetch):
            await asyncio.gather(self.integration._cache_cover(hass, "a", Coordinator()),
                                 self.integration._cache_cover(hass, "b", Coordinator()))
        self.assertEqual(peak[0], 1)
        self.assertTrue(Path(self.covers, "CUSA00002.png").exists())

    async def test_known_game_start_schedules_the_cover_and_unknown_one_the_db_refresh(self):
        line = "[SL] AppFocusChanged [NPXS20001] -> [{}]"
        for tid, game_map, expected in (("CUSA00001", {"CUSA00001": {"name": "Game"}}, "_cache_cover"),
                                        ("CUSA00002", {}, "_force_db_refresh")):
            with self.subTest(title_id=tid):
                calls = {"_cache_cover": AsyncMock(), "_force_db_refresh": AsyncMock()}
                entry = {**self.entry(None, game_map), "coordinator": Coordinator()}
                hass = SimpleNamespace(data={"ps4_goldhen": {"e": entry}}, bus=SimpleNamespace(async_fire=Mock()))
                with patch.object(self.integration, "_cache_cover", calls["_cache_cover"]), \
                     patch.object(self.integration, "_force_db_refresh", calls["_force_db_refresh"]):
                    self.assertTrue(self.integration._parse_klog_line(hass, line.format(tid), entry, "e"))
                    await asyncio.sleep(0)
                for name, mock in calls.items():
                    self.assertEqual(mock.await_count, int(name == expected), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)

import ast
import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = 'ps4_goldhen'
EVENT = 'ps4_goldhen_klog_stream'

def load_function(path, name, extra):
    source = (ROOT / path).read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name == name)
    node.decorator_list = []
    ns = {'Any':Any,'HomeAssistant':object,'DataUpdateCoordinator':object,
          'websocket_api':SimpleNamespace(ActiveConnection=object),
          'callback':lambda f:f,'DOMAIN':DOMAIN,'EVENT_KLOG_STREAM':EVENT,
          '_LOGGER':logging.getLogger('klog-test'),'asyncio':asyncio}
    ns.update(extra)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated-function','exec'),ns)
    return ns[name]

class Bus:
    def __init__(self): self.listeners=[];self.events=[]
    def async_listen(self,kind,fn):
        item=(kind,fn);self.listeners.append(item)
        def unsub():
            if item in self.listeners:self.listeners.remove(item)
        return unsub
    def async_fire(self,kind,data):
        self.events.append((kind,data))
        event=SimpleNamespace(data=data,time_fired=datetime.now(timezone.utc))
        for k,f in list(self.listeners):
            if k==kind:f(event)

class Connection:
    def __init__(self):self.subscriptions={};self.results=[];self.errors=[];self.messages=[]
    def send_result(self,*args):self.results.append(args)
    def send_error(self,*args):self.errors.append(args)
    def send_message(self,msg):self.messages.append(msg)

class SubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bus=Bus();self.hass=SimpleNamespace(data={DOMAIN:{'one':{'klog_data':{'klog_connected':True}}}},bus=self.bus)
        self.fn=load_function('custom_components/ps4_goldhen/websocket.py','ws_klog_subscribe',{})
    async def test_no_ps4_tcp_connection(self):
        c=Connection()
        with patch.object(asyncio,'open_connection',side_effect=AssertionError('Unexpected TCP')):
            await self.fn(self.hass,c,{'id':1,'entry_id':'one'})
        self.assertTrue(c.results[0][1]['subscribed'])
    async def test_entry_filter_and_event_shape(self):
        c=Connection();await self.fn(self.hass,c,{'id':1,'entry_id':'one'})
        self.bus.async_fire(EVENT,{'entry_id':'two','message':'ignore'})
        self.bus.async_fire(EVENT,{'entry_id':'one','message':'raw line'})
        self.assertEqual(len(c.messages),1)
        self.assertEqual(c.messages[0]['event']['line'],'raw line')
        self.assertEqual(c.messages[0]['type'],'event')
    async def test_unsubscribe_stops_delivery(self):
        c=Connection();await self.fn(self.hass,c,{'id':1,'entry_id':'one'})
        c.subscriptions[1]()
        self.bus.async_fire(EVENT,{'entry_id':'one','message':'ignore'})
        self.assertFalse(c.messages)
    async def test_two_subscribers_share_bus(self):
        a,b=Connection(),Connection()
        await self.fn(self.hass,a,{'id':1,'entry_id':'one'})
        await self.fn(self.hass,b,{'id':2,'entry_id':'one'})
        self.bus.async_fire(EVENT,{'entry_id':'one','message':'line'})
        self.assertEqual(len(a.messages),1);self.assertEqual(len(b.messages),1)
    async def test_missing_entry(self):
        c=Connection();await self.fn(self.hass,c,{'id':1,'entry_id':'missing'})
        self.assertEqual(c.errors[0][1],'not_found');self.assertFalse(self.bus.listeners)
    async def test_missing_line_ignored(self):
        c=Connection();await self.fn(self.hass,c,{'id':1,'entry_id':'one'})
        self.bus.async_fire(EVENT,{'entry_id':'one','message':None})
        self.assertFalse(c.messages)

class ListenerTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_cleanup_and_raw_stream(self):
        import contextlib
        bus=Bus()
        sm=SimpleNamespace(klog_connected=False)
        data={'klog_state_machine':sm,'klog_data':{'klog_connected':False}}
        hass=SimpleNamespace(data={DOMAIN:{'one':data}},bus=bus)
        coordinator=SimpleNamespace(data={},async_set_updated_data=lambda d:None)
        ready=asyncio.Event()
        class Reader:
            first=True
            async def read(self,n):
                if self.first:
                    self.first=False
                    return b'noise line\nreal line\n'
                ready.set()
                await asyncio.Event().wait()
        class Writer:
            closed=False
            def close(self):self.closed=True
            async def wait_closed(self):pass
        writer=Writer()
        async def connect(*args,**kwargs):return Reader(),writer
        fn=load_function('custom_components/ps4_goldhen/__init__.py','_klog_listener_task',{
            'contextlib':contextlib,'_parse_klog_line':lambda *args:False})
        with patch.object(asyncio,'open_connection',connect):
            t=asyncio.create_task(fn(hass,'one','ps4',3232,coordinator))
            await asyncio.wait_for(ready.wait(),timeout=1)
            self.assertTrue(data['klog_data']['klog_connected'])
            t.cancel()
            with self.assertRaises(asyncio.CancelledError):await t
        self.assertTrue(writer.closed)
        self.assertEqual([d['message'] for k,d in bus.events],['noise line','real line'])
    def test_pending_line_buffer_is_bounded(self):
        src=(ROOT/'custom_components/ps4_goldhen/__init__.py').read_text()
        self.assertIn('lines[-1][-65536:]',src)

if __name__=='__main__':unittest.main(verbosity=2)

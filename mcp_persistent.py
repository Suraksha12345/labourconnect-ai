"""
Persistent MCP client - starts mcp_server.py ONCE as a background
subprocess when Flask boots, keeps the connection open for the life
of the app, and lets agents call tools synchronously without
spawning a new subprocess (and reloading the RAG model) per request.
"""
import asyncio
import json
import os
import threading
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_connection import MCP_PYTHON, MCP_SERVER_SCRIPT


class PersistentMCPClient:
    def __init__(self):
        self._loop = None
        self._thread = None
        self._session = None
        self._ready = threading.Event()
        self._start_lock = threading.Lock()

    def start(self):
        with self._start_lock:
            if self._thread is not None:
                return
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            if not self._ready.wait(timeout=90):
                raise RuntimeError("MCP server did not start in time")

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._connect())
        self._loop.run_forever()

    async def _connect(self):
        server_params = StdioServerParameters(
            command=MCP_PYTHON,
            args=[MCP_SERVER_SCRIPT],
            env=os.environ.copy(),
        )
        self._stdio_cm = stdio_client(server_params)
        read, write = await self._stdio_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        self._ready.set()

    def call_tool(self, name, arguments, timeout=60):
        if self._thread is None:
            self.start()
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments=arguments), self._loop
        )
        result = future.result(timeout=timeout)
        return json.loads(result.content[0].text) if result.content else None


_client = PersistentMCPClient()


def get_client():
    return _client
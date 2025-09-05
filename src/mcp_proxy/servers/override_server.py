import asyncio
import contextlib
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional
from mcp import ListToolsResult, types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send
from starlette.requests import Request
from starlette.responses import Response
import contextvars

from mcp_proxy.models.tool_override import ToolOverride
from mcp_proxy.tooling.load_tools import load_server_tool
from mcp_proxy.clients.sse_client import MCPClient
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar('current_session_id')


class AsyncOverrideServer:
    def __init__(self, name: str, base_sse: str):
        self.name = name
        self.base_sse = base_sse
        self.app = Server(name)
        
        self.upstream_tools: ListToolsResult | None = None
        self.servable_tools: Dict[str, types.Tool] = {}
        
        self.overrides: Dict[str, ToolOverride] = {}
        
        self.client_sessions: Dict[str, MCPClient] = {}
        
        self.session_manager = StreamableHTTPSessionManager(
            app=self.app,
            event_store=None,
            json_response=True,
            stateless=False,
        )
        
        self.initialized = False

    @classmethod
    async def create(cls, name: str, base_sse: str):
        self = cls(name, base_sse)
        await self.load_tools()
        return self

    async def handle_streamable_http(self, scope: Scope, receive: Receive, send: Send) -> None:
        session_id = None
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            session_id = headers.get(b"mcp-session-id", b"").decode("utf-8")
            if not session_id:
                session_id = str(uuid.uuid4())
        
        if session_id not in self.client_sessions:
            client = MCPClient()
            await client.connect_to_server(self.base_sse)
            self.client_sessions[session_id] = client
            logger.info(f"Created new client session: {session_id}")
        
        current_session_id.set(session_id)
        
        scope["mcp_session_id"] = session_id
        
        await self.session_manager.handle_request(scope, receive, send)

    async def load_tools(self):
        try:
            tools = await load_server_tool(self.base_sse)
            self.upstream_tools = tools
            for tool in tools.tools:
                self.servable_tools[tool.name] = tool

            logger.info(f"Loaded {len(tools.tools)} tools from upstream server")
            self.initialized = True
        except Exception as e:
            logger.error(f"Failed to load tools from upstream server: {e}")
            raise Exception(f"Failed to get server tools: {e}")
    
    def add_override(self, name: str, override: ToolOverride):
        self.overrides[name] = override
        logger.info(f"Added override for tool: {name}")

    def remove_override(self, name: str):
        if name in self.overrides:
            del self.overrides[name]
            logger.info(f"Removed override for tool: {name}")

    def disable_tool(self, name: str):
        if not self.servable_tools:
            raise Exception("Cannot disable tools. Tools not loaded")

        if name in self.servable_tools:
            del self.servable_tools[name]
            logger.info(f"Disabled tool: {name}")
    
    def enable_tool(self, name: str):
        if not self.servable_tools or not self.upstream_tools:
            raise Exception("Cannot enable tools. Tools not loaded")
        
        for tool in self.upstream_tools.tools:
            if tool.name == name:
                self.servable_tools[tool.name] = tool
                logger.info(f"Enabled tool: {name}")
                return
        
        raise Exception(f"Tool {name} not found in upstream tools")

    async def _get_client_for_session(self, session_id: str) -> Optional[MCPClient]:
        return self.client_sessions.get(session_id)

    async def _cleanup_session(self, session_id: str):
        if session_id in self.client_sessions:
            client = self.client_sessions[session_id]
            await client.close()
            del self.client_sessions[session_id]
            logger.info(f"Cleaned up client session: {session_id}")

    async def serve(self, port: int):
        if not self.initialized:
            raise Exception("Cannot serve. Server not initialized")

        @self.app.list_tools()
        async def list_tools() -> List[types.Tool]:
            return list(self.servable_tools.values())
        
        @self.app.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
            try:
                session_id = current_session_id.get()
            except LookupError:
                logger.error("No session ID available for tool call")
                return [types.TextContent(type="text", text="Error: No session available")]
            
            logger.info(f"Tool call '{name}' for session: {session_id}")
            
            client = await self._get_client_for_session(session_id)
            if not client:
                logger.error(f"No client found for session: {session_id}")
                return [types.TextContent(type="text", text="Error: Client session not found")]
            
            if name in self.overrides:
                logger.info(f"Using override for tool: {name}")
                override = self.overrides[name]
                try:
                    result = await override.call_with_original_access(name, arguments, client)
                    print(result)
                    return result
                except Exception as e:
                    logger.error(f"Override failed for tool {name}: {e}")
                    return [types.TextContent(type="text", text=f"Override error: {str(e)}")]
            
            if name not in self.servable_tools:
                logger.warning(f"Tool not found: {name}")
                return [types.TextContent(type="text", text=f"Tool '{name}' not available")]
            
            try:
                logger.info(f"Calling original tool: {name}")
                result = await client.call_tool(name, arguments)
                print(result)
                return result.content
            except Exception as e:
                logger.error(f"Tool call failed for {name}: {e}")
                return [types.TextContent(type="text", text=f"Tool call error: {str(e)}")]

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:
            async with self.session_manager.run():
                logger.info("MCP Proxy Server started!")
                try:
                    yield
                finally:
                    for session_id in list(self.client_sessions.keys()):
                        await self._cleanup_session(session_id)
                    logger.info("MCP Proxy Server shutting down...")

        starlette_app = Starlette(
            debug=True,
            routes=[
                Mount("/sse", self.handle_streamable_http),
            ],
            lifespan=lifespan,
        )

        starlette_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
            expose_headers=["Mcp-Session-Id"],
        )
        
        logger.info(f"Starting MCP Proxy Server on port {port}")
        
        config = uvicorn.Config(starlette_app, host="0.0.0.0", port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
import asyncio
from typing import Dict, Optional
from contextlib import AsyncExitStack
from mcp import ClientSession, Tool
from mcp.types import TextContent, CallToolResult, CallToolRequestParams
from mcp.client.sse import sse_client
from dotenv import load_dotenv

load_dotenv() 

class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.tools: Dict[str, Tool] = {}
    
    async def connect_to_server(self, sse_url: str):
        stdio_transport = await self.exit_stack.enter_async_context(sse_client(sse_url))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        await self.session.initialize()

        response = await self.session.list_tools()
        tools = response.tools
        for tool in tools:
            self.tools[tool.name] = tool
        print("\nConnected to server with tools:", [len(tools)])

    async def list_tools(self) -> list[Tool]:
        if not self.session:
            return []
        result = await self.session.list_tools()
        return result.tools
    
    async def call_tool(self, name: str, arguments: dict) -> CallToolResult:
        if not self.session:
            result = CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="Internal Error: Session not initialized"
                    )
                ],
                isError=True
            )
            return result
        result = await self.session.call_tool(name, arguments)
        return result
    
    async def close(self):
        await self.exit_stack.aclose()
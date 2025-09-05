"""
MCP Proxy Server Package

A powerful MCP (Model Context Protocol) proxy server that allows you to:
- Proxy tools from an upstream MCP server
- Override specific tools with custom functionality
- Maintain persistent client sessions for SSE connections
- Extend or modify tool behavior while preserving access to original tools
"""

from .servers.override_server import AsyncOverrideServer
from .models.tool_override import ToolOverride
from .clients.sse_client import MCPClient
from .tooling.load_tools import load_server_tool

__all__ = [
    "AsyncOverrideServer",
    "ToolOverride", 
    "MCPClient",
    "load_server_tool"
]

__version__ = "1.0.0"
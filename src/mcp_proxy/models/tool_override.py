
from typing import Awaitable, Callable, List, Dict, Any, Optional
from pydantic import BaseModel
from mcp import types
from mcp_proxy.clients.sse_client import MCPClient

class ToolOverride(BaseModel):
    base_tool: types.Tool
    override_fn: Callable[[str, Dict[str, Any], MCPClient], Awaitable[List[types.ContentBlock]]]
    
    async def call_with_original_access(
        self, 
        tool_name: str, 
        arguments: Dict[str, Any], 
        original_client: MCPClient
    ) -> List[types.ContentBlock]:
        result = await self.override_fn(tool_name, arguments, original_client)
        return result
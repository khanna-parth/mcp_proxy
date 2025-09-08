
from typing import Awaitable, Callable, List, Dict, Any, Optional, Protocol
from pydantic import BaseModel
from mcp import types
from mcp_proxy.clients.sse_client import MCPClient

class ToolResult(BaseModel):
    text: str
    error: bool

class OverrideFn(Protocol):
    def __call__(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        client: "MCPClient",
        **kwargs: Any
    ) -> Awaitable["ToolResult"]:
        ...


# override_fn -> (tool_name, tool_args, mcp_client, kwargs)
class ToolOverride(BaseModel):
    base_tool: types.Tool
    override_fn: OverrideFn
    # override_fn: Callable[[str, Dict[str, Any], MCPClient], Awaitable[ToolResult]]
    
    async def call_with_original_access(
        self, 
        tool_name: str, 
        arguments: Dict[str, Any],
        original_client: MCPClient,
        **kwargs
    ) -> List[types.ContentBlock]:
        result = await self.override_fn(tool_name, arguments, original_client, **kwargs)
        return [types.TextContent(
            type="text", 
            text=f"{'Error: ' if result.error else ''}{result.text}"
        )]
        # return result
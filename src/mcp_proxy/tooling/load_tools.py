from fastmcp import Client

async def load_server_tool(sse_url: str):
    try:
        async with Client(sse_url) as client:
            tools = await client.list_tools_mcp()
            return tools
    except Exception as e:
        raise e
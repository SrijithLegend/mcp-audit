from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def fetch_inventory(command: str, args: list[str]) -> dict:
    params = StdioServerParameters(command=command, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return {
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": t.input_schema,
                    }
                    for t in tools.tools
                ]
            }
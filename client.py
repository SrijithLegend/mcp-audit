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
                        "input_schema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None),
                    }
                    for t in tools.tools
                ]
            }


if __name__ == "__main__":  # self-check: scan a throwaway server, expect its one tool
    import asyncio
    import sys

    stub = (
        "from mcp.server.mcpserver import MCPServer\n"
        "m = MCPServer('stub')\n"
        "@m.tool()\n"
        "def add(a: int, b: int) -> int:\n"
        "    'Add two numbers'\n"
        "    return a + b\n"
        "m.run()\n"
    )
    inv = asyncio.run(fetch_inventory(sys.executable, ["-c", stub]))
    assert [t["name"] for t in inv["tools"]] == ["add"], inv
    assert inv["tools"][0]["description"] == "Add two numbers", inv
    assert inv["tools"][0]["input_schema"]["required"] == ["a", "b"], inv
    print("ok")

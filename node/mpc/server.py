import asyncio
import os
import signal
import traceback
import logging
import httpx
import mcp.types as types
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.requests import Request
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NapthaMPCServer:
    def __init__(self):
        self.app = Server("naptha-mpc")
        self.setup_tools()
        self.shutdown_event = asyncio.Event()
        
    async def fetch_website(self, url: str) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        headers = {
            "User-Agent": "MCP Test Server (github.com/modelcontextprotocol/python-sdk)"
        }
        async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            return [types.TextContent(type="text", text=response.text)]

    async def echo_message(self, message: str) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=message)]

    async def say_hello(self, name: str = "World") -> list[types.TextContent]:
        return [types.TextContent(type="text", text=f"Hello, {name}!")]
    
    def setup_tools(self):
        @self.app.call_tool()
        async def fetch_tool(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            if name == "fetch":
                if "url" not in arguments:
                    raise ValueError("Missing required argument 'url'")
                return await self.fetch_website(arguments["url"])
            elif name == "echo":
                if "message" not in arguments:
                    raise ValueError("Missing required argument 'message'")
                return await self.echo_message(arguments["message"])
            elif name == "hello":
                name_arg = arguments.get("name", "World")
                return await self.say_hello(name_arg)
            else:
                raise ValueError(f"Unknown tool: {name}")

        @self.app.list_tools()
        async def list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="fetch",
                    description="Fetches a website and returns its content",
                    inputSchema={
                        "type": "object",
                        "required": ["url"],
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "URL to fetch",
                            }
                        },
                    },
                ),
                types.Tool(
                    name="echo",
                    description="Returns the provided message",
                    inputSchema={
                        "type": "object",
                        "required": ["message"],
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Message to echo back",
                            }
                        },
                    },
                ),
                types.Tool(
                    name="hello",
                    description="Returns a greeting message",
                    inputSchema={
                        "type": "object",
                        "required": [],
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name to greet (defaults to 'World')",
                            }
                        },
                    },
                )
            ]
    
    def create_starlette_app(self, debug: bool = False) -> Starlette:
        """Create a Starlette application that can serve the provided mcp server with SSE."""
        sse = SseServerTransport("/messages/")

        async def handle_sse(request: Request) -> None:
            async with sse.connect_sse(
                    request.scope,
                    request.receive,
                    request._send,  # noqa: SLF001
            ) as (read_stream, write_stream):
                await self.app.run(
                    read_stream,
                    write_stream,
                    self.app.create_initialization_options(),
                )

        return Starlette(
            debug=debug,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )
    
    async def start_server(self, port: int, debug: bool = False):
        """Start the Starlette server with uvicorn"""
        from uvicorn import Config, Server
        
        app = self.create_starlette_app(debug=debug)
        config = Config(app=app, host="0.0.0.0", port=port)
        server = Server(config=config)
        
        # Store server instance for graceful shutdown
        self.server = server
        
        logger.info(f"Starting Naptha MPC Server on port {port}")
        await server.serve()
    
    async def graceful_shutdown(self, sig=None):
        """Gracefully shut down the server"""
        if sig:
            logger.info(f"Received shutdown signal: {sig}")
        
        logger.info("Shutting down server...")
        
        if not self.shutdown_event.is_set():
            self.shutdown_event.set()
            
            if hasattr(self, 'server') and self.server:
                self.server.should_exit = True
                await self.server.shutdown()
                logger.info("Server stopped")
            
            logger.info("Server shutdown complete")


async def run_server(port: int):
    """Main function to run the NapthaMPCServer"""
    server = NapthaMPCServer()
    
    def signal_handler(sig):
        """Handle shutdown signals"""
        asyncio.create_task(server.graceful_shutdown(sig))
    
    try:
        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig, 
                lambda s=sig: signal_handler(s)
            )

        # Start server
        await server.start_server(port=port)
        
        # Wait for shutdown event
        await server.shutdown_event.wait()
        
    except Exception as e:
        logger.error(f"Error running server: {e}")
        logger.error(traceback.format_exc())
        if not server.shutdown_event.is_set():
            await server.graceful_shutdown()
    finally:
        if not server.shutdown_event.is_set():
            await server.graceful_shutdown()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Naptha MPC Server")
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run the server on"
    )
    
    args = parser.parse_args()

    asyncio.run(run_server(port=args.port))
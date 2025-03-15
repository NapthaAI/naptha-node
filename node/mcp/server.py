import asyncio
import os
import signal
import traceback
import logging
import httpx
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
import mcp.types as types
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.requests import Request
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport

# Import our enhanced client
from naptha_mcp.client import NapthaMCPClient

file_path = Path(__file__).resolve().parent
project_root = file_path.parent.parent.parent

# Load environment variables
load_dotenv(find_dotenv(), override=True)

# Get MCP server script path from environment
MCP_SERVER_SCRIPT_PATH = f"{file_path}/naptha_mcp/weather.py"

if os.getenv("LAUNCH_DOCKER") == "false":
    os.environ["NODE_URL"] = "http://localhost:7001"
    os.environ["HUB_URL"] = "ws://localhost:3001/rpc"

    PRIVATE_KEY = os.getenv("PRIVATE_KEY")
    PRIVATE_KEY = f"{project_root}/{PRIVATE_KEY}"
    os.environ["PRIVATE_KEY"] = PRIVATE_KEY
else:
    os.environ["NODE_URL"] = "http://node-app:7001"
    os.environ["HUB_URL"] = "ws://surrealdb:8000/rpc"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables to hold tool configurations
SSE1_TOOLS = [
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

class SseServer(Server):
    """Extended Server class that allows us to store endpoint information"""
    def __init__(self, name, endpoint_path=None):
        super().__init__(name)
        self.endpoint_path = endpoint_path

class NapthaMCPServer:
    def __init__(self, generic_mcp_script_path=None):
        # Create server instances for the endpoints
        self.app1 = SseServer("naptha-mcp-sse1", "/sse")
        self.app2 = SseServer("naptha-mcp-sse2", "/sse2")
        self.app3 = SseServer("naptha-mcp-sse3", "/sse3")
        
        # Create an instance of the NapthaMCPClient
        self.mcp_client = NapthaMCPClient()
        
        # Store the generic MCP script path for later use
        self.generic_mcp_script_path = generic_mcp_script_path
        
        # Set up the tools for each server
        self.setup_app1()
        self.setup_app2()
        self.setup_app3()
        
        self.shutdown_event = asyncio.Event()
        self.shutdown_timeout = 10
        
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
    
    def setup_app1(self):
        """Set up tools for /sse endpoint"""
        @self.app1.call_tool()
        async def call_tool1(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            logger.info(f"App1 tool call: {name}")
            
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

        @self.app1.list_tools()
        async def list_tools1() -> list[types.Tool]:
            logger.info("App1 listing tools")
            return SSE1_TOOLS
    
    async def initialize_client(self):
        """Initialize and authenticate the client if needed"""
        try:
            # Ensure the client is initialized in async context
            await self.mcp_client.__aenter__()
            
            # Sign in if needed
            if not hasattr(self.mcp_client, "_authenticated") or not self.mcp_client._authenticated:
                await self.mcp_client.signin()
                # Mark as authenticated to avoid repeated sign-ins
                self.mcp_client._authenticated = True
                
            return True
        except Exception as e:
            logger.error(f"Failed to initialize client: {str(e)}")
            return False
    
    def setup_app2(self):
        """Set up tools for /sse2 endpoint"""
        
        @self.app2.call_tool()
        async def call_tool2(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            logger.info(f"App2 tool call: {name}")
            
            # Initialize client
            if not await self.initialize_client():
                raise ValueError("Failed to initialize client")
            
            try:
                # Use the client's run_mcp_tool method to handle the tool call
                func_args = {
                    "tool": name,
                    "arguments": arguments
                }
                
                result = await self.mcp_client.run_mcp_tool(
                    tool_module_name="echo_tool",
                    func_name="call_tool",
                    func_args=func_args
                )
                
                if not result or not result.results:
                    raise ValueError(f"No result returned from tool: {name}")
                
                # The result will be in the format returned by the tool module
                tool_result = result.results[0]
                
                # If it's already a TextContent object, return it
                if isinstance(tool_result, types.TextContent):
                    return [tool_result]
                    
                # If it's a dict with the right fields, convert it
                if isinstance(tool_result, dict) and "type" in tool_result and "text" in tool_result:
                    return [types.TextContent(**tool_result)]
                    
                # Otherwise, create a text content from the result
                return [types.TextContent(type="text", text=str(tool_result))]
                
            except Exception as e:
                logger.error(f"Error running tool {name}: {str(e)}")
                raise ValueError(f"Error running tool {name}: {str(e)}")

        @self.app2.list_tools()
        async def list_tools2() -> list[types.Tool]:
            logger.info("App2 listing tools")
            
            # If client is not available, return empty list
            if not self.mcp_client:
                logger.warning("Client not available, no tools will be available")
                return []
            
            try:
                # Initialize client
                if not await self.initialize_client():
                    logger.warning("Client initialization failed, no tools will be available")
                    return []
                
                # Use the client to list tools
                result = await self.mcp_client.run_mcp_tool(
                    tool_module_name="echo_tool",
                    func_name="list_tools",
                    func_args={}
                )
                
                if result and result.results and result.results[0]:
                    # The result might be a JSON string, try to parse it
                    tool_list = result.results[0]
                    
                    logger.info(f"Raw tool list: {tool_list}")
                    
                    # If it's a string, try to parse it as JSON
                    if isinstance(tool_list, str):
                        try:
                            tool_list = json.loads(tool_list)
                            logger.info(f"Parsed tool list: {tool_list}")
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse tool list as JSON: {e}")
                            return []
                    
                    # Now tool_list should be a Python list of dictionaries
                    if isinstance(tool_list, list):
                        tools = []
                        for tool in tool_list:
                            try:
                                tools.append(types.Tool(
                                    name=tool["name"],
                                    description=tool["description"],
                                    inputSchema=tool.get("input_schema", {})
                                ))
                            except (KeyError, TypeError) as e:
                                logger.error(f"Error processing tool item: {e}")
                        return tools
                    else:
                        logger.warning(f"Unexpected tool list format: {type(tool_list)}")
                        return []
                else:
                    logger.warning("No tools returned from client")
                    return []
                        
            except Exception as e:
                logger.error(f"Error listing tools with client: {str(e)}")
                # Return empty list instead of fallback
                return []
    
    def setup_app3(self):
        """Set up tools for /sse3 endpoint with generic MCP server support"""
        
        @self.app3.call_tool()
        async def call_tool3(name: str, arguments: dict) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            logger.info(f"App3 tool call: {name}")
            
            if not self.generic_mcp_script_path:
                raise ValueError("Generic MCP script path not provided. Please restart the server with a valid script path.")
            
            try:
                # Create a new client instance for each call to avoid cancel scope issues
                # This is less efficient but more reliable for the current anyio implementation
                temp_client = NapthaMCPClient()
                
                try:
                    # Connect to the MCP server
                    await temp_client.connect_mcp_server(self.generic_mcp_script_path)
                    
                    # Call the tool
                    result = await temp_client.call_mcp_tool(name, arguments)
                    
                    # Return the result
                    return [types.TextContent(type="text", text=result)]
                finally:
                    # Always clean up the temporary client
                    if hasattr(temp_client, "is_mcp_connected") and temp_client.is_mcp_connected:
                        await temp_client.disconnect_mcp_server()
                    await temp_client.__aexit__(None, None, None)
                    
            except Exception as e:
                logger.error(f"Error calling tool {name} on generic MCP server: {str(e)}")
                error_message = f"Error calling tool {name}: {str(e)}"
                return [types.TextContent(type="text", text=error_message)]

        @self.app3.list_tools()
        async def list_tools3() -> list[types.Tool]:
            logger.info("App3 listing tools")
            
            if not self.generic_mcp_script_path:
                logger.warning("Generic MCP script path not provided, no tools will be available")
                return []
            
            try:
                # Create a new client instance for tool listing to avoid cancel scope issues
                temp_client = NapthaMCPClient()
                
                try:
                    # Connect to the MCP server
                    tools = await temp_client.connect_mcp_server(self.generic_mcp_script_path)
                    return tools
                finally:
                    # Always clean up the temporary client
                    if hasattr(temp_client, "is_mcp_connected") and temp_client.is_mcp_connected:
                        await temp_client.disconnect_mcp_server()
                    await temp_client.__aexit__(None, None, None)
                    
            except Exception as e:
                logger.error(f"Error listing tools from generic MCP server: {str(e)}")
                return []
    
    def create_starlette_app(self, debug: bool = False) -> Starlette:
        """Create a Starlette application that can serve the provided mcp server with SSE."""
        sse = SseServerTransport("/messages/")

        async def handle_sse(request: Request) -> None:
            logger.info(f"New connection from /sse")
            
            async with sse.connect_sse(
                    request.scope,
                    request.receive,
                    request._send,  # noqa: SLF001
            ) as (read_stream, write_stream):
                await self.app1.run(
                    read_stream,
                    write_stream,
                    self.app1.create_initialization_options(),
                )

        async def handle_sse2(request: Request) -> None:
            logger.info(f"New connection from /sse2")
            
            async with sse.connect_sse(
                    request.scope,
                    request.receive,
                    request._send,  # noqa: SLF001
            ) as (read_stream, write_stream):
                await self.app2.run(
                    read_stream, 
                    write_stream, 
                    self.app2.create_initialization_options(),
                )
        
        async def handle_sse3(request: Request) -> None:
            logger.info(f"New connection from /sse3")
            
            if not self.generic_mcp_script_path:
                from starlette.responses import JSONResponse
                return JSONResponse({"error": "Generic MCP script path not provided"}, status_code=500)
            
            async with sse.connect_sse(
                    request.scope,
                    request.receive,
                    request._send,  # noqa: SLF001
            ) as (read_stream, write_stream):
                await self.app3.run(
                    read_stream, 
                    write_stream, 
                    self.app3.create_initialization_options(),
                )

        async def handle_health(request: Request):
            from starlette.responses import JSONResponse
            status_info = {
                "status": "ok",
                "endpoints": {
                    "sse": True,
                    "sse2": True,
                    "sse3": self.generic_mcp_script_path is not None
                }
            }
            
            # Add MCP server info if connected
            if hasattr(self.mcp_client, "is_mcp_connected") and self.mcp_client.is_mcp_connected:
                status_info["mcp_server"] = self.mcp_client.get_mcp_server_info()
                
            return JSONResponse(status_info)

        routes = [
            Route("/sse", endpoint=handle_sse),
            Route("/sse2", endpoint=handle_sse2),
            Route("/health", endpoint=handle_health),
            Mount("/messages/", app=sse.handle_post_message),
        ]
        
        # Add sse3 endpoint only if generic MCP script path is provided
        if self.generic_mcp_script_path:
            routes.append(Route("/sse3", endpoint=handle_sse3))

        return Starlette(
            debug=debug,
            routes=routes,
        )
    
    async def start_server(self, port: int, debug: bool = False):
        """Start the Starlette server with uvicorn"""
        from uvicorn import Config, Server
        
        app = self.create_starlette_app(debug=debug)
        config = Config(app=app, host="0.0.0.0", port=port)
        server = Server(config=config)
        
        # Store server instance for graceful shutdown
        self.server = server
        
        logger.info(f"Starting Naptha MCP Server on port {port}")
        
        # Log the available endpoints
        endpoints = ["/sse", "/sse2", "/health"]
        if self.generic_mcp_script_path:
            endpoints.append("/sse3")
        logger.info(f"Available endpoints: {', '.join(endpoints)}")
        
        await server.serve()
    
    async def _force_shutdown(self):
        """Force shutdown the server after timeout"""
        logger.warning(f"Forcing shutdown after {self.shutdown_timeout} seconds")
        os._exit(0)  # Force immediate exit
        
    async def graceful_shutdown(self, sig=None):
        """Gracefully shut down the server with timeout"""
        if sig:
            logger.info(f"Received shutdown signal: {sig}")
        
        logger.info("Shutting down server...")
        
        # Clean up MCP client
        if hasattr(self.mcp_client, "is_mcp_connected") and self.mcp_client.is_mcp_connected:
            try:
                await self.mcp_client.disconnect_mcp_server()
            except Exception as e:
                logger.error(f"Error disconnecting from MCP server: {str(e)}")
        
        # Clean up Naptha client
        try:
            await self.mcp_client.__aexit__(None, None, None)
        except Exception as e:
            logger.error(f"Error cleaning up Naptha client: {str(e)}")
        
        if not self.shutdown_event.is_set():
            self.shutdown_event.set()
            
            # Start a task that will force exit after timeout
            force_shutdown_task = asyncio.create_task(
                asyncio.sleep(self.shutdown_timeout, self._force_shutdown())
            )
            
            try:
                if hasattr(self, 'server') and self.server:
                    logger.info(f"Attempting graceful shutdown (timeout: {self.shutdown_timeout}s)...")
                    self.server.should_exit = True
                    await self.server.shutdown()
                    logger.info("Server stopped gracefully")
                
                # If we get here, cancel the force shutdown task
                force_shutdown_task.cancel()
                logger.info("Server shutdown complete")
                
            except asyncio.CancelledError:
                # This might happen during forced shutdown
                logger.warning("Shutdown was cancelled")
                raise
            
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")
                logger.error(traceback.format_exc())
                # Don't cancel force_shutdown_task here, let it exit the process


async def run_server(port: int, generic_mcp_script_path: str = None):
    """Main function to run the NapthaMCPServer"""
    server = NapthaMCPServer(generic_mcp_script_path)
    
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
    import sys
    
    parser = argparse.ArgumentParser(description="Run Naptha MCP Server")
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run the server on"
    )
    parser.add_argument(
        "--generic-mcp-script",
        type=str,
        default=MCP_SERVER_SCRIPT_PATH,
        help="Path to a generic MCP server script (.py or .js) to use with the /sse3 endpoint"
    )
    
    args = parser.parse_args()
    
    # Get script path from command line or environment
    script_path = args.generic_mcp_script
    
    # Report the source of the script path
    if script_path:
        if args.generic_mcp_script == MCP_SERVER_SCRIPT_PATH and MCP_SERVER_SCRIPT_PATH:
            print(f"Using MCP server script from environment: {script_path}")
        else:
            print(f"Using MCP server script from command line: {script_path}")
            
        # Validate the script path
        if not os.path.exists(script_path):
            print(f"Error: Generic MCP script not found: {script_path}")
            sys.exit(1)
    else:
        print("No generic MCP script provided. The /sse3 endpoint will not be available.")
        print("Set MCP_SERVER_SCRIPT_PATH environment variable or use --generic-mcp-script option.")
    
    asyncio.run(run_server(port=args.port, generic_mcp_script_path=script_path))
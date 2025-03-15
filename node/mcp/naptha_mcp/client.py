#!/usr/bin/env python3
import asyncio
import os
import logging
import json
from typing import Dict, Any, List, Optional
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import mcp.types as types

from naptha_sdk.client.naptha import Naptha
from naptha_sdk.schemas import ToolDeployment, NodeConfigUser, ToolRunInput
from naptha_sdk.user import sign_consumer_id
from naptha_sdk.utils import get_logger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = get_logger(__name__)

# Load environment variables
load_dotenv(override=True)

class NapthaMCPClient:
    """A client for interacting with MCP servers on a Naptha node.
    
    This is a thin wrapper around the UserClient from naptha_sdk with added
    convenience methods for working with MCP endpoints.
    
    Now enhanced with support for direct MCP server execution via stdio.
    """
    
    def __init__(self):
        """Initialize the client using environment variables"""
        self.naptha = Naptha()
        
        # Generic MCP server variables
        self.mcp_session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.available_tools: List[types.Tool] = []
        self.is_mcp_connected = False
        self.mcp_server_path = None
        
    async def __aenter__(self):
        """Setup client for use in async context manager"""
        await self.naptha.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up resources when exiting async context manager"""
        # Clean up MCP resources if connected
        if self.is_mcp_connected:
            await self.disconnect_mcp_server()
            
        # Clean up Naptha resources
        await self.naptha.__aexit__(exc_type, exc_val, exc_tb)
        
    async def signin(self, username=None, password=None):
        """Sign in using provided credentials or from environment variables"""
        username = username or os.getenv("HUB_USERNAME")
        password = password or os.getenv("HUB_PASSWORD")
        
        if not username or not password:
            logger.error("Missing username or password. Please provide credentials or set HUB_USERNAME and HUB_PASSWORD environment variables.")
            return False
        
        try:
            logger.info(f"Signing in user: {username}")
            success, _, _ = await self.naptha.hub.signin(username, password)
            if not success:
                logger.error("Authentication failed. Please check your username and password.")
                return False
            logger.info("Authentication successful!")
            return True
        except Exception as e:
            logger.error(f"Error during sign-in: {e}")
            return False
    
    async def ensure_user_registered(self):
        """Ensure the user is registered with the node"""
        try:
            user = await self.naptha.node.check_user(user_input={"public_key": self.naptha.hub.public_key})
            
            if user['is_registered']:
                logger.info(f"User is registered with node: {user['id']}")
                return user
            else:
                logger.info("User not registered. Registering now...")
                user = await self.naptha.node.register_user(user_input=user)
                logger.info(f"User registration successful: {user['id']}")
                return user
        except Exception as e:
            logger.error(f"Error checking/registering user: {str(e)}")
            return None
    
    async def run_mcp_tool(self, tool_module_name, func_name, func_args=None):
        """Run a tool on a specific MCP endpoint
        
        Args:
            tool_module_name: Name of the tool module to use
            func_name: Name of the function to run (list_tools or call_tool)
            func_args: Arguments to pass to the function
            
        Returns:
            The tool run result
        """
        # First ensure user is registered
        user = await self.ensure_user_registered()
        if not user:
            logger.error("Failed to ensure user is registered")
            return None
        
        if func_args is None:
            func_args = {}
                    
        # Create tool deployment
        tool_deployment = ToolDeployment(
            name=tool_module_name,
            module={"name": tool_module_name, "module_type": "tool"},
            node=NodeConfigUser(ip="localhost")
        )
        
        # Create tool run input
        tool_run_input = ToolRunInput(
            consumer_id=user['id'],
            inputs={
                "func_name": func_name,
                "func_args": func_args
            },
            deployment=tool_deployment,
            signature=sign_consumer_id(user['id'], os.getenv("PRIVATE_KEY"))
        )
        logger.info(f"Running tool: {tool_run_input}")
        
        # Run the tool using the UserClient
        try:
            result = await self.naptha.node.run_tool_and_poll(tool_run_input)
            logger.info(f"Tool result: {result}")
            return result
        except Exception as e:
            logger.error(f"Error running tool: {str(e)}")
            return None
    
    async def connect_mcp_server(self, server_script_path: str):
        """Connect to a generic MCP server
        
        Args:
            server_script_path: Path to the server script (.py or .js)
            
        Returns:
            List of available tools
        """
        if self.is_mcp_connected:
            # Try to reuse existing connection
            try:
                # Check if connection is still valid by listing tools
                response = await self.mcp_session.list_tools()
                self.available_tools = response.tools
                return self.available_tools
            except Exception:
                # If any error occurs, close the existing connection and create a new one
                await self.disconnect_mcp_server()
                
        self.mcp_server_path = server_script_path
            
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")
            
        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None
        )
        
        try:
            # Create a new exit stack for this connection
            self.exit_stack = AsyncExitStack()
            
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            self.stdio, self.write = stdio_transport
            self.mcp_session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
            
            await self.mcp_session.initialize()
            
            # List available tools
            response = await self.mcp_session.list_tools()
            self.available_tools = response.tools
            logger.info(f"Connected to MCP server with tools: {[tool.name for tool in self.available_tools]}")
            self.is_mcp_connected = True
            
            return self.available_tools
            
        except Exception as e:
            logger.error(f"Error connecting to MCP server: {str(e)}")
            await self.cleanup_mcp_resources()
            raise

    async def disconnect_mcp_server(self):
        """Disconnect from the MCP server and clean up resources"""
        await self.cleanup_mcp_resources()
        
    async def cleanup_mcp_resources(self):
        """Clean up MCP resources"""
        if self.is_mcp_connected:
            try:
                await self.exit_stack.aclose()
            except Exception as e:
                logger.error(f"Error during MCP cleanup: {str(e)}")
            finally:
                self.is_mcp_connected = False
                self.mcp_session = None
                self.available_tools = []
                logger.info("Disconnected from MCP server")

    async def call_mcp_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """Call a tool from the connected MCP server with improved error handling
        
        Args:
            name: Name of the tool to call
            arguments: Arguments to pass to the tool
            
        Returns:
            Tool execution result as string
        """
        if not self.is_mcp_connected:
            raise ValueError("Not connected to any MCP server. Please connect first.")
            
        if not self.mcp_session:
            raise ValueError("MCP session not initialized.")
            
        try:
            result = await self.mcp_session.call_tool(name, arguments)
            
            # Extract text content
            text_content = []
            for item in result.content:
                if hasattr(item, 'text'):
                    text_content.append(item.text)
                    
            return "\n".join(text_content) if text_content else "No text content in response"
            
        except Exception as e:
            logger.error(f"Error calling MCP tool {name}: {str(e)}")
            # Try to reconnect and retry once
            try:
                logger.info(f"Attempting to reconnect and retry tool call: {name}")
                await self.connect_mcp_server(self.mcp_server_path)
                result = await self.mcp_session.call_tool(name, arguments)
                
                # Extract text content
                text_content = []
                for item in result.content:
                    if hasattr(item, 'text'):
                        text_content.append(item.text)
                        
                return "\n".join(text_content) if text_content else "No text content in response"
            except Exception as retry_error:
                logger.error(f"Retry failed for tool {name}: {str(retry_error)}")
                raise ValueError(f"Error calling tool {name}: {str(e)}. Retry also failed.")

# Test code to demonstrate the client usage
async def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_mcp_server_script>")
        return
        
    server_script_path = sys.argv[1]
    
    client = NapthaMCPClient()
    try:
        # Connect to MCP server
        await client.connect_mcp_server(server_script_path)
        
        # Print available tools
        print("\nAvailable tools:")
        for tool in client.available_tools:
            print(f"- {tool.name}: {tool.description}")
        
        # Example: call a tool if weather.py is used
        if "get_forecast" in [tool.name for tool in client.available_tools]:
            print("\nTesting get_forecast tool...")
            result = await client.call_mcp_tool("get_forecast", {
                "latitude": 37.7749, 
                "longitude": -122.4194
            })
            print(f"Result: {result[:200]}...")
        
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        # Clean up resources
        await client.disconnect_mcp_server()

if __name__ == "__main__":
    asyncio.run(main())
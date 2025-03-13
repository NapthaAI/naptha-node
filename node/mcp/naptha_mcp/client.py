#!/usr/bin/env python3
import asyncio
import argparse
import os
import logging
import json
from dotenv import load_dotenv

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
    """
    
    def __init__(self):
        """Initialize the client using environment variables"""
        self.naptha = Naptha()
        
    async def __aenter__(self):
        """Setup client for use in async context manager"""
        await self.naptha.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up resources when exiting async context manager"""
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
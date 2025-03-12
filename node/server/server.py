import asyncio
from dotenv import load_dotenv
import os
import signal
from pathlib import Path
from typing import Optional
import traceback

from node.storage.hub.hub import HubDBSurreal
from node.server.http_server import HTTPServer
from node.server.ws_server import WebSocketServer
from node.server.grpc_server import GrpcServer
from node.utils import get_logger, get_node_config
from node.secret import Secret

logger = get_logger(__name__)
load_dotenv()
REGISTER_NODE_WITH_HUB = os.getenv("REGISTER_NODE_WITH_HUB")

FILE_PATH = Path(__file__).resolve()
PARENT_DIR = FILE_PATH.parent


class NodeServer:
    def __init__(self, communication_protocol: str, port: int):
        self.node_config = get_node_config()
        self.node_id = self.node_config.id.split(":")[1]
        # Store initial config values
        self.ip = self.node_config.ip
        self.server: Optional[HTTPServer | WebSocketServer | GrpcServer] = None
        self.communication_protocol = communication_protocol
        self.port = port
        self.hub = HubDBSurreal()
        self.shutdown_event = asyncio.Event()

    async def register_node(self):
        """Register the node with the hub - only HTTP server does this"""
        if self.communication_protocol == "http":
            try:
                async with self.hub as hub:
                    success, user, user_id = await hub.signin(
                        os.getenv("HUB_USERNAME"), os.getenv("HUB_PASSWORD")
                    )
                    if not success:
                        logger.error('Failed to sign in to hub.')
                        raise Exception("Failed to sign in to hub")
                    
                    # First try to delete any existing node registration
                    node_id = self.node_config.id
                    try:
                        await hub.delete_node(node_id=node_id)
                        logger.info(f"Cleaned up existing node registration: {node_id}")
                    except Exception as e:
                        logger.error(f"No existing node to clean up: {e}")
                    
                    # Create http server records first
                    server_records = []
                    ip_ = self.node_config.ip
                    if "http://" in ip_:    
                        ip_ = ip_.split("//")[1]
                    server_records.append({
                        "communication_protocol": self.node_config.user_communication_protocol,
                        "node_id": self.node_id,
                        "port": self.node_config.user_communication_port
                    })

                    # Create other server records
                    for i in range(self.node_config.num_node_communication_servers):
                        server_records.append({
                            "communication_protocol": self.node_config.node_communication_protocol,
                            "node_id": self.node_id,
                            "port": self.node_config.servers[i].port
                        })

                    logger.debug(f"Server records: {server_records}")

                    # Now register the node
                    self.node_config = await hub.create_node(node_config=self.node_config, servers=server_records)
                    if isinstance(self.node_config, dict):
                        self.node_id = self.node_config["id"].split(":")[1]
                        self.ip = self.node_config["ip"]
                    logger.info(f"Registered node: {self.node_config['id'] if isinstance(self.node_config, dict) else self.node_config.id}")
            except Exception as e:
                logger.error(f"Error during node registration: {e}")
                logger.error(f"Traceback: {''.join(traceback.format_exc())}")
                # Ensure we try to clean up even if registration fails
                await self.unregister_node()
                raise

    async def start_server(self):
        """Start the server based on type and port"""
        # Handle http:// prefix in ip
        if "http://" in self.ip:
            ip = self.ip.split("//")[1]
        else:
            ip = self.ip

        if self.communication_protocol == "http":
            logger.info(f"Starting HTTP server on port {self.port}...")
            self.server = HTTPServer(ip, self.port)
            # Store reference to NodeServer in app state
            self.server.app.state.node_server = self
            
            # Add shutdown event handler
            @self.server.app.on_event("shutdown")
            async def shutdown_event():
                logger.info("FastAPI shutdown event triggered")
                try:
                    await self.graceful_shutdown()
                except Exception as e:
                    logger.error(f"Error during shutdown: {e}")

        elif self.communication_protocol in ["ws", "wss"]:
            logger.info(f"Starting WebSocket server on port {self.port}...")
            self.server = WebSocketServer(
                ip, 
                self.port,
                node_id=self.node_id
            )
        elif self.communication_protocol == "grpc":
            logger.info(f"Starting gRPC server on port {self.port}...")
            self.server = GrpcServer(
                ip,
                self.port,
                node_id=self.node_id
            )
        else:
            raise ValueError(f"Invalid server type: {self.communication_protocol}")

        await self.server.launch_server()

    async def unregister_node(self):
        """Unregister the node from the hub - only HTTP server does this"""
        if self.communication_protocol == "http":
            try:
                logger.info("Unregistering node from hub")

                if not isinstance(self.node_config, dict):
                    self.node_config = self.node_config.model_dump()

                node_id = self.node_config["id"]
                logger.info(f"Attempting to unregister node: {node_id}")

                async with HubDBSurreal() as hub:
                    try:
                        # Add timeout to signin
                        success, user, user_id = await asyncio.wait_for(
                            hub.signin(os.getenv("HUB_USERNAME"), os.getenv("HUB_PASSWORD")),
                            timeout=10.0
                        )
                        if not success:
                            raise Exception("Failed to sign in to hub during unregistration")

                        # Add timeout to delete_node
                        success = await asyncio.wait_for(
                            hub.delete_node(node_id=node_id, servers=self.node_config["servers"]),
                            timeout=10.0
                        )

                        if success:
                            logger.info(f"Successfully unregistered node: {node_id}")
                        else:
                            logger.error(f"Failed to unregister node: {node_id}")
                            raise Exception("Failed to unregister node")
                    except asyncio.TimeoutError:
                        logger.error("HubDBSurreal operation timed out")
                        raise
            except Exception as e:
                logger.error(f"Error during node unregistration: {e}")
                logger.error(f"Traceback: {''.join(traceback.format_exc())}")
                raise

    async def graceful_shutdown(self, sig=None):
        """Handle graceful shutdown of the server"""
        if sig:
            logger.info(f'Received exit signal {sig.name}...')
        
        logger.info(f"Initiating graceful shutdown for {self.communication_protocol} server on port {self.port}...")
        self.shutdown_event.set()
        
        try:
            if self.communication_protocol == "http" and REGISTER_NODE_WITH_HUB == "true":
                logger.info("HTTP server shutting down, will unregister node")
                # Add timeout to unregister operation
                try:
                    await asyncio.wait_for(self.unregister_node(), timeout=20.0)
                    logger.info("Node unregistration completed successfully")
                except asyncio.TimeoutError:
                    logger.error("Node unregistration timed out")
                except Exception as e:
                    logger.error(f"Failed to unregister node during shutdown: {e}")
            else:
                logger.info("HTTP server shutting down, node unregistration not required")
            
            # Handle server-specific shutdown
            if isinstance(self.server, HTTPServer):
                logger.info("Stopping HTTP server...")
                try:
                    await asyncio.wait_for(self.server.stop(), timeout=10.0)
                    logger.info("HTTP server stopped successfully")
                except asyncio.TimeoutError:
                    logger.error("HTTP server stop timed out")
                except Exception as e:
                    logger.error(f"Error stopping HTTP server: {e}")
            
        except Exception as e:
            logger.error(f"Error during {self.communication_protocol} server shutdown: {e}")
        finally:
            # Give time for cleanup operations to complete
            logger.debug("Cleanup delay before exit...")
            await asyncio.sleep(1)
            logger.info(f"Forcing exit of {self.communication_protocol} server...")
            os._exit(0)

async def run_server(communication_protocol: str, port: int):
    """Main function to run a single server"""
    node_server = NodeServer(communication_protocol, port)
    
    def signal_handler(sig):
        """Handle shutdown signals"""
        asyncio.create_task(node_server.graceful_shutdown(sig))
    
    try:
        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig, 
                lambda s=sig: signal_handler(s)
            )

        if REGISTER_NODE_WITH_HUB == "true" and node_server.communication_protocol == "http":
            if node_server.node_config.ip == "localhost":
                logger.error("Unable to register a localhost server with the hub")
                raise Exception("Cannot register node on hub with NODE_IP localhost. Either change REGISTER_NODE_WITH_HUB to false, or set NODE_IP to your public IP address or domain name in config.py.")
            # Register node (only for HTTP server)
            await node_server.register_node()
            logger.info(f"Node registered with hub")
        else:
            logger.info("Skipping registration of node with hub")
        # Start server
        await node_server.start_server()
        
        # Wait for shutdown event
        await node_server.shutdown_event.wait()
        
    except Exception as e:
        logger.error(f"Error running server: {e}")
        logger.error(traceback.format_exc())
        if not node_server.shutdown_event.is_set():
            await node_server.graceful_shutdown()
    finally:
        if not node_server.shutdown_event.is_set():
            await node_server.graceful_shutdown()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run node server")
    parser.add_argument(
        "--communication-protocol",
        type=str,
        choices=["http", "ws", "wss", "grpc"],
        required=True,
        help="Type of server to run"
    )
    parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="Port to run the server on"
    )
    
    args = parser.parse_args()

    server_private_key_path = os.path.join(os.path.dirname(__file__), '../../private_key.pem')
    server_public_key_path = os.path.join(os.path.dirname(__file__), '../../public_key.pem')
    env_file_path = os.path.join(os.path.dirname(__file__), '../../.env')

    secret = Secret(server_private_key_path, server_public_key_path, env_file_path)
    secret.check_and_generate_keys()

    asyncio.run(run_server(
        communication_protocol=args.communication_protocol,
        port=args.port
    ))
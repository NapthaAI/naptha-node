from dotenv import load_dotenv
import os
import json
import asyncio
import uvicorn
import websockets
from datetime import datetime
import traceback
import logging
from typing import Dict, Any, Union
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from node.schemas import (
    AgentRunInput, AgentDeployment,
    MemoryRunInput, MemoryDeployment,
    ToolRunInput, ToolDeployment,
    EnvironmentRunInput, EnvironmentDeployment,
    KBRunInput, KBDeployment, 
    OrchestratorRunInput, OrchestratorDeployment,
    ModuleExecutionType,
)
from node.storage.db.db import LocalDBPostgres
from node.user import register_user, check_user
from node.worker.docker_worker import execute_docker_agent
from node.worker.package_worker import (
    run_agent,
    run_tool,
    run_kb,
    run_memory,
    run_orchestrator,
    run_environment,

)
from node.module_manager import setup_module_deployment

logger = logging.getLogger(__name__)
load_dotenv()

file_path = Path(__file__).resolve()
root_dir = file_path.parent.parent.parent
MODULES_SOURCE_DIR = root_dir / os.getenv("MODULES_SOURCE_DIR")

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, websocket: WebSocket, client_id: str, task: str):
        await websocket.accept()
        if client_id not in self.active_connections:
            self.active_connections[client_id] = {}
        self.active_connections[client_id][task] = websocket
        logger.info(f"WebSocket connection established for {client_id}_{task}")

    def disconnect(self, client_id: str, task: str):
        if (
            client_id in self.active_connections
            and task in self.active_connections[client_id]
        ):
            del self.active_connections[client_id][task]
            if not self.active_connections[client_id]:
                del self.active_connections[client_id]
            logger.info(f"WebSocket connection closed for {client_id}_{task}")

    async def send_message(self, message: str, client_id: str, task: str):
        if (
            client_id in self.active_connections
            and task in self.active_connections[client_id]
        ):
            try:
                await self.active_connections[client_id][task].send_text(message)
                logger.info(f"Sent message to {client_id}_{task}")
            except Exception as e:
                logger.error(f"Error sending message to {client_id}_{task}: {str(e)}")
                self.disconnect(client_id, task)


class TransientDatabaseError(Exception):
    pass


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class WebSocketServer:
    def __init__(self, host: str, port: int, node_id: str):
        self.host = host
        self.port = port
        self.node_id = node_id
        self.app = FastAPI()
        self.temp_files = {}
        self.manager = ConnectionManager()
        self.server = None
        self._started = False

        # Add shutdown event handler
        @self.app.on_event("shutdown")
        async def shutdown_event():
            logger.info("Received shutdown signal from FastAPI")
            try:
                await self.graceful_shutdown()
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        # Add health check endpoint
        @self.app.get("/health")
        async def health_check():
            """Simple health check endpoint"""
            return {"status": "ok", "communication_protocol": "websocket"}

        self.app.add_api_websocket_route(
            "/ws/user/check/{client_id}", self.check_user_endpoint
        )
        self.app.add_api_websocket_route(
            "/ws/user/register/{client_id}", self.register_user_endpoint
        )
        self.app.add_api_websocket_route(
            "/ws/{module_type}/run/{client_id}", self.run_module_endpoint
        )

    async def establish_connection(self):
        while True:
            try:
                websocket = await websockets.connect(self.host)
                logger.info(f"Connected to relay server at {self.host}")
                return websocket
            except Exception as e:
                logger.error(f"Failed to connect to relay server: {e}")
                await asyncio.sleep(5)  # Wait before retrying

    async def send_response(self, response):
        try:
            await self.relay_websocket.send(json.dumps(response, cls=DateTimeEncoder))
            logger.info(f"Sent response: {response}")
        except Exception as e:
            logger.error(f"Error sending response: {str(e)}")
            # If the connection is closed, try to reconnect
            if isinstance(e, websockets.exceptions.ConnectionClosed):
                logger.info("Attempting to reconnect to relay server...")
                self.relay_websocket = await self.establish_connection()
                # Try sending the response again after reconnecting
                try:
                    await self.relay_websocket.send(
                        json.dumps(response, cls=DateTimeEncoder)
                    )
                    logger.info(f"Sent response after reconnection: {response}")
                except Exception as e2:
                    logger.error(
                        f"Failed to send response after reconnection: {str(e2)}"
                    )

    async def run_agent_endpoint(self, websocket: WebSocket, client_id: str):
        await self.manager.connect(websocket, client_id, "run_agent")
        try:
            while True:
                try:
                    data = await websocket.receive_json()  # Try receiving data
                    logger.info(f"Endpoint: run_agent :: Received data: {data}")

                    # Simulating a response process
                    result = await self.run_agent(data, client_id)
                    logger.info(f"Endpoint: run_agent :: Sending result: {result}")
                    await self.manager.send_message(result, client_id, "run_agent")

                except WebSocketDisconnect:
                    logger.warning(f"Client {client_id} disconnected.")
                    self.manager.disconnect(client_id, "run_agent")
                    break  # Exit the loop if client disconnects

                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                    await self.manager.send_message(
                        json.dumps({"status": "error", "message": "Invalid JSON"}),
                        client_id,
                        "run_agent",
                    )

                except Exception as e:
                    logger.error(f"Error processing request: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    await self.manager.send_message(
                        json.dumps({"status": "error", "message": str(e)}),
                        client_id,
                        "run_agent",
                    )

        except WebSocketDisconnect:
            logger.warning(f"Client {client_id} disconnected (outer).")
            self.manager.disconnect(client_id, "run_agent")
    
    async def create_module(self, module_deployment: Union[AgentDeployment, MemoryDeployment, ToolDeployment, EnvironmentDeployment, KBDeployment]) -> Dict[str, Any]:
        """
        Unified method to create and install any type of module and its sub-modules
        """
        try:
            # Map deployment types to module types
            module_type_map = {
                AgentDeployment: "agent",
                ToolDeployment: "tool",
                KBDeployment: "kb",
                MemoryDeployment: "memory",
                OrchestratorDeployment: "orchestrator",
                EnvironmentDeployment: "environment",
            }

            # Determine module type based on deployment class
            module_type = None
            for deployment_class, type_name in module_type_map.items():
                if isinstance(module_deployment, deployment_class):
                    module_type = type_name
                    break

            if not module_type:
                raise HTTPException(status_code=400, detail="Invalid module deployment type")

            logger.info(f"Creating {module_type}: {module_deployment}")

            main_module_name = module_deployment.module['name'] if isinstance(module_deployment.module, dict) else module_deployment.module.name
            main_module_path = Path(f"{MODULES_SOURCE_DIR}/{main_module_name}/{main_module_name}")

            module_deployment = await setup_module_deployment(
                module_type, 
                main_module_path / "configs/deployment.json", 
                module_deployment.name, 
                module_deployment
            )

            return module_deployment

        except Exception as e:
            logger.error(f"Failed to create module: {str(e)}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=str(e))

    async def run_module_endpoint(self, websocket: WebSocket, module_type: str, client_id: str):
        await self.manager.connect(websocket, client_id, f"run_{module_type}")
        try:
            while True:
                try:
                    data = await websocket.receive_json()
                    logger.info(f"Endpoint: run_{module_type} :: Received data: {data}")

                    result = await self.run_module(module_type, data, client_id)
                    logger.info(f"Endpoint: run_{module_type} :: Sending result: {result}")
                    await self.manager.send_message(result, client_id, f"run_{module_type}")

                except WebSocketDisconnect:
                    logger.warning(f"Client {client_id} disconnected.")
                    self.manager.disconnect(client_id, f"run_{module_type}")
                    break

                except json.JSONDecodeError:
                    logger.error("Invalid JSON received")
                    await self.manager.send_message(
                        json.dumps({"status": "error", "message": "Invalid JSON"}),
                        client_id,
                        f"run_{module_type}",
                    )

                except Exception as e:
                    logger.error(f"Error processing request: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    await self.manager.send_message(
                        json.dumps({"status": "error", "message": str(e)}),
                        client_id,
                        f"run_{module_type}",
                    )

        except WebSocketDisconnect:
            logger.warning(f"Client {client_id} disconnected (outer).")
            self.manager.disconnect(client_id, f"run_{module_type}")

    async def run_module(self, module_type: str, data: dict, client_id: str) -> str:
        try:
            # Map module types to their corresponding input and run classes
            module_configs = {
                "agent": {
                    "input_class": AgentRunInput,
                    "db_create": lambda db, input: db.create_agent_run(input),
                    "db_list": lambda db, id: db.list_agent_runs(id),
                    "worker": run_agent,
                    "docker_support": True
                },
                "tool": {
                    "input_class": ToolRunInput,
                    "db_create": lambda db, input: db.create_tool_run(input),
                    "db_list": lambda db, id: db.list_tool_runs(id),
                    "worker": run_tool,
                    "docker_support": False
                },
                "kb": {
                    "input_class": KBRunInput,
                    "db_create": lambda db, input: db.create_kb_run(input),
                    "db_list": lambda db, id: db.list_kb_runs(id),
                    "worker": run_kb,
                    "docker_support": False
                },
                "memory": {
                    "input_class": MemoryRunInput,
                    "db_create": lambda db, input: db.create_memory_run(input),
                    "db_list": lambda db, id: db.list_memory_runs(id),
                    "worker": run_memory,
                    "docker_support": False
                },
                "orchestrator": {
                    "input_class": OrchestratorRunInput,
                    "db_create": lambda db, input: db.create_orchestrator_run(input),
                    "db_list": lambda db, id: db.list_orchestrator_runs(id),
                    "worker": run_orchestrator,
                    "docker_support": False
                },
                "environment": {
                    "input_class": EnvironmentRunInput,
                    "db_create": lambda db, input: db.create_environment_run(input),
                    "db_list": lambda db, id: db.list_environment_runs(id),
                    "worker": run_environment,
                    "docker_support": False
                },

            }

            if module_type not in module_configs:
                raise ValueError(f"Invalid module type: {module_type}")

            config = module_configs[module_type]
            run_input = config["input_class"](**data)
            logger.info(f"Received task: {run_input}")

            # if not run_input.deployment.initialized:
            #     deployment = await self.create_module(run_input.deployment)
            #     run_input.deployment = deployment

            async with LocalDBPostgres() as db:
                module_run = await config["db_create"](db, run_input)
                if not module_run:
                    raise ValueError(f"Failed to create {module_type} run")
                module_run_data = module_run.model_dump()

            # Execute the task
            if isinstance(module_run.deployment.module, dict):
                execution_type = module_run.deployment.module["execution_type"]
            else:
                execution_type = module_run.deployment.module.execution_type

            if execution_type == ModuleExecutionType.package or execution_type == 'package':
                task = config["worker"].delay(module_run_data)
            elif execution_type == ModuleExecutionType.docker or execution_type == 'docker':
                task = execute_docker_agent.delay(module_run_data)
            else:
                raise HTTPException(status_code=400, detail=f"Invalid {module_type} run type")

            # Wait for the task to complete
            while not task.ready():
                await asyncio.sleep(1)

            # Retrieve the updated run from the database
            async with LocalDBPostgres() as db:
                updated_run = await config["db_list"](db, module_run_data['id'])
                if isinstance(updated_run, list):
                    updated_run = updated_run[0]

            if isinstance(updated_run, dict):
                updated_run.pop("_sa_instance_state", None)
            else:
                updated_run = updated_run.__dict__
                updated_run.pop("_sa_instance_state", None)

            # Convert timestamps to strings if they exist
            for time_field in ['created_time', 'start_processing_time', 'completed_time']:
                if time_field in updated_run and isinstance(updated_run[time_field], datetime):
                    updated_run[time_field] = updated_run[time_field].isoformat()

            return json.dumps(
                {"status": "success", "data": updated_run}, cls=DateTimeEncoder
            )
        except Exception as e:
            logger.error(f"Failed to run {module_type} module: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return json.dumps({"status": "error", "message": str(e)})
        
    async def check_user_endpoint(self, websocket: WebSocket, client_id: str):
        await self.manager.connect(websocket, client_id, "check_user")
        try:
            while True:
                data = await websocket.receive_text()
                result = await self.check_user(data)
                await self.manager.send_message(result, client_id, "check_user")
        except WebSocketDisconnect:
            self.manager.disconnect(client_id, "check_user")

    async def check_user(self, data: str) -> str:
        data = json.loads(data)
        _, response = await check_user(data)
        if '_sa_instance_state' in response:
            response.pop('_sa_instance_state')
        return json.dumps(response)

    async def register_user_endpoint(self, websocket: WebSocket, client_id: str):
        await self.manager.connect(websocket, client_id, "register_user")
        try:
            while True:
                data = await websocket.receive_text()
                result = await self.register_user(data)
                await self.manager.send_message(result, client_id, "register_user")
        except WebSocketDisconnect:
            self.manager.disconnect(client_id, "register_user")

    async def register_user(self, data: str) -> str:
        data = json.loads(data)
        _, response = await register_user(data)
        if '_sa_instance_state' in response:
            response.pop('_sa_instance_state')
        return json.dumps(response)

    async def graceful_shutdown(self):
        """Fast and efficient WebSocket server shutdown"""
        try:
            logger.info("WebSocket server shutting down...")
            
            # 1. Close all active connections concurrently with timeout
            close_tasks = []
            for client_id in list(self.manager.active_connections.keys()):
                for task in list(self.manager.active_connections[client_id].keys()):
                    websocket = self.manager.active_connections[client_id][task]
                    close_tasks.append(
                        asyncio.create_task(websocket.close())
                    )
                    self.manager.disconnect(client_id, task)
                    
            if close_tasks:
                try:
                    # 2. Wait max 2 seconds for connections to close
                    await asyncio.wait_for(
                        asyncio.gather(*close_tasks, return_exceptions=True),
                        timeout=2.0
                    )
                except asyncio.TimeoutError:
                    logger.warning("Some connections failed to close gracefully")

            # 3. Stop server quickly
            if self.server and self._started:
                try:
                    await asyncio.wait_for(self.server.shutdown(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("Server shutdown timed out")
                finally:
                    self._started = False

            # 4. Clean up temp files without waiting
            if self.temp_files:
                for filepath in list(self.temp_files.values()):
                    try:
                        if os.path.exists(filepath):
                            os.remove(filepath)
                    except Exception as e:
                        logger.error(f"Failed to remove temp file {filepath}: {e}")
                self.temp_files.clear()

        except Exception as e:
            logger.error(f"Error during WebSocket shutdown: {e}")
        finally:
            logger.info("WebSocket server shutdown complete")

    async def launch_server(self):
        """Start the WebSocket server"""
        config = uvicorn.Config(
            self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="debug",
            timeout_keep_alive=300,
            limit_concurrency=2000,
            backlog=4096,
            timeout_graceful_shutdown=5,
            reload=False,
            ws_ping_interval=20,
            ws_ping_timeout=30     
        )
        self.server = uvicorn.Server(config)
        self._started = True
        try:
            await self.server.serve()
        finally:
            self._started = False

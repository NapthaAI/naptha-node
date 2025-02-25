import asyncio
import httpx
import logging
import traceback
from datetime import datetime
from typing import Union, Any, Dict, List, Optional
import uvicorn
import os
import base64
from dotenv import load_dotenv, dotenv_values
from fastapi import FastAPI, APIRouter, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pathlib import Path

from node.module_manager import (
    setup_module_deployment,
)
from node.schemas import (
    AgentRun,
    AgentRunInput,
    MemoryDeployment,
    MemoryRun,
    MemoryRunInput,
    ToolRun,
    ToolRunInput,
    OrchestratorRun,
    OrchestratorRunInput,
    EnvironmentRun,
    EnvironmentRunInput,
    DockerParams,
    ChatCompletionRequest,
    AgentDeployment, 
    OrchestratorDeployment, 
    EnvironmentDeployment,
    KBDeployment,
    KBRunInput,
    KBRun,
    ModuleExecutionType,
    ToolDeployment,
    SecretInput
)
from node.storage.db.db import LocalDBPostgres
from node.storage.hub.hub import HubDBSurreal
from node.user import check_user, register_user, get_user_public_key, verify_signature
from node.worker.docker_worker import execute_docker_agent
from node.worker.package_worker import run_agent, run_tool, run_environment, run_orchestrator, run_kb, run_memory
from node.client import Node as NodeClient
from node.storage.server import router as storage_router
from node.inference.server import router as inference_router
from node.secret import Secret

logger = logging.getLogger(__name__)
load_dotenv()

file_path = Path(__file__).resolve()
root_dir = file_path.parent.parent.parent
MODULES_SOURCE_DIR = root_dir / os.getenv("MODULES_SOURCE_DIR")
LITELLM_HTTP_TIMEOUT = 60*5
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY")
LITELLM_URL = "http://litellm:4000" if os.getenv("LAUNCH_DOCKER") == "true" else "http://localhost:4000"

if not LITELLM_MASTER_KEY:
    raise Exception("Missing LITELLM_MASTER_KEY for authentication")


class TransientDatabaseError(Exception):
    pass

class HTTPServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

        self.app = FastAPI()
        router = APIRouter()
        self.server = None
        self.should_exit = False
        self.secret = Secret()

        @self.app.on_event("shutdown")
        async def shutdown_event():
            logger.info("Received shutdown signal from FastAPI")
            self.should_exit = True
            # Add a short delay to allow the signal to propagate
            await asyncio.sleep(1)
        
        @self.app.get("/health")
        async def health_check():
            return {"status": "ok", "communication_protocol": "http"}
        
        # Handle validation errors when request data doesn't match the expected Pydantic models
        # Logs the validation error details and request body, then returns a 422 response with the error info
        @self.app.exception_handler(RequestValidationError)
        async def validation_exception_handler(request: Request, exc: RequestValidationError):
            logger.error(f"Request validation error: {exc.errors()}")
            logger.error(f"Request body: {await request.json()}")
            return JSONResponse(
                status_code=422,
                content={
                    "detail": exc.errors(),
                    "body": await request.json()
                }
            )
        
        @router.get("/.well-known/jwks.json")
        async def get_public_key():
            try:
                jwk = self.secret.get_public_key()

                return {"keys" : [jwk]}
            except Exception as e:
                return {"error": f"Error retrieving public key: {str(e)}"}

        @router.post("/agent/create")
        async def agent_create_endpoint(agent_input: AgentDeployment) -> AgentDeployment:
            """
            Create an agent
            :param agent_input: AgentDeployment
            :return: AgentDeployment
            """
            return await self.agent_create(agent_input)

        @router.post("/agent/run")
        async def agent_run_endpoint(agent_run_input: AgentRunInput, secrets: List[SecretInput] = []) -> AgentRun:
            """
            Run an agent
            :param agent_run_input: Agent run specifications
            :param secrets: Optional list of secrets to pass to the agent
            :return: Status
            """
            return await self.agent_run(agent_run_input, secrets)

        @router.post("/agent/check") 
        async def agent_check_endpoint(agent_run: AgentRun) -> AgentRun:
            """
            Check an agent
            :param agent_run: AgentRun details
            :return: Status
            """
            return await self.agent_check(agent_run)

        @router.post("/tool/create")
        async def tool_create_endpoint(tool_input: ToolDeployment) -> ToolDeployment:
            """
            Create a tool
            :param tool_input: ToolDeployment 
            :return: ToolDeployment
            """
            return await self.tool_create(tool_input)

        @router.post("/tool/run")
        async def tool_run_endpoint(tool_run_input: ToolRunInput, secrets: List[SecretInput] = []) -> ToolRun:
            """
            Run a tool
            :param tool_run_input: Tool run specifications
            :param secrets: Optional list of secrets to pass to the tool
            :return: Status
            """
            return await self.tool_run(tool_run_input, secrets)

        @router.post("/tool/check")
        async def tool_check_endpoint(tool_run: ToolRun) -> ToolRun:
            """
            Check a tool
            :param tool_run: ToolRun details
            :return: Status
            """
            return await self.tool_check(tool_run)

        @router.post("/orchestrator/create")
        async def orchestrator_create_endpoint(orchestrator_input: OrchestratorDeployment) -> OrchestratorDeployment:
            """
            Create an agent orchestrator
            :param orchestrator_input: OrchestratorDeployment
            :return: OrchestratorDeployment
            """
            return await self.orchestrator_create(orchestrator_input)
        
        @router.post("/orchestrator/run")
        async def orchestrator_run_endpoint(orchestrator_run_input: OrchestratorRunInput, secrets: List[SecretInput] = []) -> OrchestratorRun:
            """
            Run an agent orchestrator
            :param orchestrator_run_input: Orchestrator run specifications
            :param secrets: Optional list of secrets to pass to the orchestrator
            :return: Status
            """
            return await self.orchestrator_run(orchestrator_run_input, secrets)

        @router.post("/orchestrator/check")
        async def orchestrator_check_endpoint(orchestrator_run: OrchestratorRun) -> OrchestratorRun:
            """
            Check an orchestrator
            :param orchestrator_run: OrchestratorRun details
            :return: Status
            """
            return await self.orchestrator_check(orchestrator_run)
        
        @router.post("/environment/create")
        async def environment_create_endpoint(environment_input: EnvironmentDeployment) -> EnvironmentDeployment:
            """
            Create an environment
            :param environment_input: EnvironmentDeployment
            :return: EnvironmentDeployment
            """
            return await self.environment_create(environment_input)

        @router.post("/environment/run")
        async def environment_run_endpoint(environment_run_input: EnvironmentRunInput, secrets: List[SecretInput] = []) -> EnvironmentRun:
            """
            Run an environment
            :param environment_run_input: Environment run specifications 
            :param secrets: Optional list of secrets to pass to the environment
            :return: Status
            """
            return await self.environment_run(environment_run_input, secrets)

        @router.post("/environment/check")
        async def environment_check_endpoint(environment_run: EnvironmentRun) -> EnvironmentRun:
            """
            Check an environment
            :param environment_run: EnvironmentRun details
            :return: Status
            """
            return await self.environment_check(environment_run)

        @router.post("/kb/create")
        async def kb_create_endpoint(kb_input: KBDeployment) -> KBDeployment:
            """
            Create a knowledge base
            :param kb_input: KBDeployment
            :return: KBDeployment
            """
            return await self.kb_create(kb_input)
        
        @router.post("/kb/run")
        async def kb_run_endpoint(kb_run_input: KBRunInput, secrets: List[SecretInput] = []) -> KBRun:
            """
            Run a knowledge base
            :param kb_run_input: KBRunInput
            :param secrets: Optional list of secrets to pass to the knowledge base
            :return: KBRun
            """
            return await self.kb_run(kb_run_input, secrets)

        @router.post("/kb/check")
        async def kb_check_endpoint(kb_run: KBRun) -> KBRun:
            """
            Check a knowledge base
            :param kb_run: KBRun details
            :return: Status
            """
            return await self.kb_check(kb_run)

        @router.post("/memory/create")
        async def memory_create_endpoint(memory_input: MemoryDeployment) -> MemoryDeployment:
            """
            Create a memory module
            :param memory_input: MemoryDeployment
            :return: MemoryDeployment
            """
            return await self.memory_create(memory_input)

        @router.post("/memory/run")
        async def memory_run_endpoint(memory_run_input: MemoryRunInput, secrets: List[SecretInput] = [] ) -> MemoryRun:
            """
            Run a memory module
            :param memory_run_input: Memory run specifications
            :param secrets: Optional list of secrets to pass to the memory
            :return: Status
            """
            return await self.memory_run(memory_run_input, secrets)

        @router.post("/memory/check")
        async def memory_check_endpoint(memory_run: MemoryRun) -> MemoryRun:
            """
            Check a memory module
            :param memory_run: MemoryRun details
            :return: Status
            """
            return await self.memory_check(memory_run)

        # User endpoints
        @router.post("/user/check")
        async def user_check_endpoint(user_input: dict):
            """Check if a user exists."""
            _, response = await check_user(user_input)
            if '_sa_instance_state' in response:
                response.pop('_sa_instance_state')
            return response

        @router.post("/user/register")
        async def user_register_endpoint(user_input: dict):
            """Register a new user."""
            _, response = await register_user(user_input)
            if '_sa_instance_state' in response:
                response.pop('_sa_instance_state')
            return response
        
        @router.post("/user/secret/create")
        async def user_secret_create_endpoint(
            existing_secrets: List[SecretInput] = [], 
            secrets: List[SecretInput] = [], 
            signature: str = Query(...), 
            is_update: Optional[bool] = Query(False)
        ):
            user_id = secrets[0].user_id.replace("<record>", "") if secrets else ""
            
            if not user_id:
                raise HTTPException(status_code=400, detail=f"Data cannot be empty")
            
            if not verify_signature(user_id, signature, user_id.split(":")[1]):
                raise HTTPException(status_code=401, detail="Unauthorized: Invalid signature")
            
            try:
                aes_secret = base64.b64decode(os.getenv("AES_SECRET"))
                for data in secrets:
                    rsa_decrypted_secret_value = self.secret.decrypt_rsa(data.secret_value)
                    encrypted_secret_value = self.secret.encrypt_with_aes(rsa_decrypted_secret_value, aes_secret)
                    data.secret_value = encrypted_secret_value
                
                async with HubDBSurreal() as hub:
                    result = await hub.create_secret(secrets, is_update, existing_secrets)
                
                return result
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error processing secrets: {str(e)}")

        async def get_server_connection(self, server_id: str):
            """
                Gets server connection details from hub and returns appropriate Node object
            """
            try:
                async with HubDBSurreal() as hub:
                    logger.info(f"Getting server connection for {server_id}")
                    server = await hub.get_server(server_id=server_id)
                    logger.info(f"Server: {server}")
                    return server['connection_string']
            except Exception as e:
                logger.error(f"Error getting server connection: {e}")
                raise

        # Include the router
        self.app.include_router(router)
        self.app.include_router(storage_router)
        self.app.include_router(inference_router)

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    async def register_user_on_worker_nodes(self, module_run: Union[AgentRun, OrchestratorRun]):
        """
        Registers user on worker nodes.
        """
        logger.info(f"Validating user {module_run.consumer_id} access on worker nodes")

        node_clients = []
        if hasattr(module_run, "agent_deployments"):
            for deployment in module_run.agent_deployments:
                if deployment.agent_node:
                    node_clients.append(NodeClient(deployment.agent_node))
        elif hasattr(module_run, "tool_deployments"):
            for deployment in module_run.tool_deployments:
                if deployment.tool_node:
                    node_clients.append(NodeClient(deployment.tool_node))
        elif hasattr(module_run, "environment_deployments"):
            for deployment in module_run.environment_deployments:
                if deployment.environment_node:
                    node_clients.append(NodeClient(deployment.environment_node))
        elif hasattr(module_run, "kb_deployments"):
            for deployment in module_run.kb_deployments:
                if deployment.kb_node:
                    node_clients.append(NodeClient(deployment.kb_node))
        elif hasattr(module_run, "memory_deployments"):
            for deployment in module_run.memory_deployments:
                if deployment.memory_node:
                    node_clients.append(NodeClient(deployment.memory_node))

        for node_client in node_clients:
            async with node_client as node_client:
                consumer = await node_client.check_user(user_input=self.consumer)
                
                if consumer["is_registered"]:
                    logger.info(f"User validated on node: {node_client.node_schema}")
                    return
                
                logger.info(f"Registering new user on node: {node_client.node_schema}")
                consumer = await node_client.register_user(user_input=consumer)
                logger.info(f"User registration complete on node: {node_client.node_schema}")

    async def create_module(self, module_deployment: Union[AgentDeployment, MemoryDeployment, OrchestratorDeployment, EnvironmentDeployment, KBDeployment, MemoryDeployment, ToolDeployment]) -> Dict[str, Any]:
        """
        Unified method to create and install any type of module and its sub-modules
        """
        try:
            logger.info(f"Creating {module_deployment.module['module_type']}: {module_deployment}")

            main_module_name = module_deployment.module['name']
            main_module_path = Path(f"{MODULES_SOURCE_DIR}/{main_module_name}/{main_module_name}")

            module_deployment = await setup_module_deployment(module_deployment.module["module_type"], main_module_path / "configs/deployment.json", module_deployment.name, module_deployment)

            return module_deployment


        except Exception as e:
            logger.error(f"Failed to create module: {str(e)}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=str(e))

    async def run_module(
        self, 
        module_run_input: Union[AgentRunInput, MemoryRunInput, OrchestratorRunInput, EnvironmentRunInput, ToolRunInput],
        secrets: List[SecretInput] = []
    ) -> Union[AgentRun, MemoryRun, OrchestratorRun, EnvironmentRun, ToolRun]:
        """
        Generic method to run either an agent, memory, orchestrator, environment, tool, kb, or memory
        :param run_input: Run specifications (AgentRunInput, MemoryRunInput, OrchestratorRunInput, EnvironmentRunInput, ToolRunInput or KBRunInput)
        :return: Status
        """
        try:

            if not module_run_input.deployment.initialized == True:
                module_deployment = await self.create_module(module_run_input.deployment)
                module_run_input.deployment = module_deployment

            # Determine module type and configuration
            if isinstance(module_run_input, AgentRunInput):
                create_func = lambda db: db.create_agent_run
            elif isinstance(module_run_input, ToolRunInput):
                create_func = lambda db: db.create_tool_run
            elif isinstance(module_run_input, OrchestratorRunInput):
                create_func = lambda db: db.create_orchestrator_run
            elif isinstance(module_run_input, EnvironmentRunInput):
                create_func = lambda db: db.create_environment_run
            elif isinstance(module_run_input, KBRunInput):
                create_func = lambda db: db.create_kb_run
            elif isinstance(module_run_input, MemoryRunInput):
                create_func = lambda db: db.create_memory_run
            else:
                raise HTTPException(status_code=400, detail="Invalid run input type")
                
            module_type = module_run_input.deployment.module.module_type

            logger.info(f"Received request to run {module_type}: {module_run_input}")

            user_public_key = await get_user_public_key(module_run_input.consumer_id)

            if not verify_signature(module_run_input.consumer_id, module_run_input.signature, user_public_key):
                raise HTTPException(status_code=401, detail="Unauthorized: Invalid signature")
            
            user_env_data = {}
            secret = Secret()
                    
            for record in secrets:
                decrypted_value = secret.decrypt_with_aes(record.secret_value, base64.b64decode(os.getenv("AES_SECRET")))
                user_env_data[record.key_name] = decrypted_value

            # Create module run record in DB
            async with LocalDBPostgres() as db:
                module_run = await create_func(db)(module_run_input)
                if not module_run:
                    raise HTTPException(status_code=500, detail=f"Failed to create {module_type} run")
                module_run_data = module_run.model_dump()

                logger.info(f"{module_type.capitalize()} run data: {module_run_data}")

            await self.register_user_on_worker_nodes(module_run)

            # Execute the task based on module type
            if module_run_input.deployment.module.execution_type == ModuleExecutionType.package:
                if module_type == "agent":
                    _ = run_agent.delay(module_run_data, user_env_data)
                elif module_type == "tool":
                    _ = run_tool.delay(module_run_data, user_env_data)
                elif module_type == "orchestrator":
                    _ = run_orchestrator.delay(module_run_data, user_env_data)
                elif module_type == "environment":
                    _ = run_environment.delay(module_run_data, user_env_data)
                elif module_type == "kb":
                    _ = run_kb.delay(module_run_data, user_env_data)
                elif module_type == "memory":
                    _ = run_memory.delay(module_run_data, user_env_data)                   
            elif module_run_input.deployment.module.execution_type == ModuleExecutionType.docker and module_type == "agent":
                # validate docker params
                try:
                    _ = DockerParams(**module_run_data["inputs"])
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Invalid docker params: {str(e)}")
                _ = execute_docker_agent.delay(module_run_data)
            else:
                raise HTTPException(status_code=400, detail=f"Invalid {module_type} run type")

            return module_run_data
        
        except HTTPException as e:
            logger.error(f"Error: {str(e.detail)}")
            raise e

        except Exception as e:
            logger.error(f"Failed to run module: {str(e)}")
            error_details = traceback.format_exc()
            logger.error(f"Full traceback: {error_details}")
            raise HTTPException(
                status_code=500, detail=f"Failed to run module: {module_run_input}"
            )

    async def agent_create(self, agent_deployment: AgentDeployment) -> AgentDeployment:
        agent_deployment.module['module_type'] = "agent"
        return await self.create_module(agent_deployment)

    async def tool_create(self, tool_deployment: ToolDeployment) -> ToolDeployment:
        tool_deployment.module['module_type'] = "tool"
        return await self.create_module(tool_deployment)

    async def orchestrator_create(self, orchestrator_deployment: OrchestratorDeployment) -> OrchestratorDeployment:
        orchestrator_deployment.module['module_type'] = "orchestrator"
        return await self.create_module(orchestrator_deployment)
    
    async def environment_create(self, environment_deployment: EnvironmentDeployment) -> EnvironmentDeployment:
        environment_deployment.module['module_type'] = "environment"
        return await self.create_module(environment_deployment)

    async def kb_create(self, kb_deployment: KBDeployment) -> KBDeployment:
        kb_deployment.module['module_type'] = "kb"
        return await self.create_module(kb_deployment)

    async def memory_create(self, memory_deployment: MemoryDeployment) -> MemoryDeployment:
        memory_deployment.module['module_type'] = "memory"
        return await self.create_module(memory_deployment)

    async def agent_run(self, agent_run_input: AgentRunInput, secrets: List[SecretInput] = []) -> AgentRun:
        return await self.run_module(agent_run_input, secrets)

    async def tool_run(self, tool_run_input: ToolRunInput, secrets: List[SecretInput] = []) -> ToolRun:
        return await self.run_module(tool_run_input, secrets)

    async def orchestrator_run(self, orchestrator_run_input: OrchestratorRunInput, secrets: List[SecretInput] = []) -> OrchestratorRun:
        return await self.run_module(orchestrator_run_input, secrets)

    async def environment_run(self, environment_run_input: EnvironmentRunInput, secrets: List[SecretInput] = []) -> EnvironmentRun:
        return await self.run_module(environment_run_input, secrets)

    async def kb_run(self, kb_run_input: KBRunInput, secrets: List[SecretInput] = []) -> KBRun:
        return await self.run_module(kb_run_input, secrets)

    async def memory_run(self, memory_run_input: MemoryRunInput, secrets: List[SecretInput] = []) -> MemoryRun:
        return await self.run_module(memory_run_input, secrets)

    async def check_module(
        self, 
        module_run: Union[AgentRun, MemoryRun, ToolRun, OrchestratorRun, EnvironmentRun]
    ) -> Union[AgentRun, MemoryRun, ToolRun, OrchestratorRun, EnvironmentRun]:
        """
        Check a module run (agent, memory, tool, orchestrator, or environment)
        :param module_run: Run details (AgentRun, MemoryRun, ToolRun, OrchestratorRun, or EnvironmentRun)
        :return: Status
        """
        try:
            # Determine module type and configuration
            if isinstance(module_run, AgentRun):
                list_func = lambda db: db.list_agent_runs(module_run.id)
            elif isinstance(module_run, ToolRun):
                list_func = lambda db: db.list_tool_runs(module_run.id)
            elif isinstance(module_run, OrchestratorRun):
                list_func = lambda db: db.list_orchestrator_runs(module_run.id)
            elif isinstance(module_run, EnvironmentRun):
                list_func = lambda db: db.list_environment_runs(module_run.id)
            elif isinstance(module_run, KBRun):
                list_func = lambda db: db.list_kb_runs(module_run.id)
            elif isinstance(module_run, MemoryRun):
                list_func = lambda db: db.list_memory_runs(module_run.id)
            else:
                raise HTTPException(status_code=400, detail="Invalid module run type")

            module_type = module_run.deployment.module['module_type']

            logger.info(f"Checking {module_type} run")
            if module_run.id is None:
                raise HTTPException(status_code=400, detail=f"{module_type.capitalize()} run ID is required")

            async with LocalDBPostgres() as db:
                run_data = await list_func(db)
                if isinstance(run_data, list):
                    run_data = run_data[0]
                run_data.pop("_sa_instance_state", None)

                if 'results' in run_data and run_data['results']:
                    run_data['results'] = [r for r in run_data['results'] if r is not None]
    
                # Convert datetime fields to ISO format
                for time_field in ['created_time', 'start_processing_time', 'completed_time']:
                    if time_field in run_data and isinstance(run_data[time_field], datetime):
                        run_data[time_field] = run_data[time_field].isoformat()
                
                # Convert back to appropriate type
                module_run = type(module_run)(**run_data)

            if not module_run:
                raise HTTPException(status_code=404, detail=f"{module_type.capitalize()} run not found")

            logger.info(f"Found {module_type} status: {module_run.status}")

            if module_run.status == "completed":
                logger.info(f"{module_type.capitalize()} run completed. Returning output: {module_run.results}")
                response = module_run.results
            elif module_run.status == "error":
                logger.info(f"{module_type.capitalize()} run failed. Returning error: {module_run.error_message}")
                response = module_run.error_message
            else:
                response = None

            logger.info(f"Response: {response}")
            return module_run

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to check {module_type} run: {str(e)}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Internal server error occurred while checking {module_type} run"
            )

    async def agent_check(self, agent_run: AgentRun) -> AgentRun:
        return await self.check_module(agent_run)

    async def tool_check(self, tool_run: ToolRun) -> ToolRun:
        return await self.check_module(tool_run)

    async def orchestrator_check(self, orchestrator_run: OrchestratorRun) -> OrchestratorRun:
        return await self.check_module(orchestrator_run)

    async def environment_check(self, environment_run: EnvironmentRun) -> EnvironmentRun:
        return await self.check_module(environment_run)

    async def kb_check(self, kb_run: KBRun) -> KBRun:
        return await self.check_module(kb_run)

    async def memory_check(self, memory_run: MemoryRun) -> MemoryRun:
        return await self.check_module(memory_run)

    async def stop(self):
        """Handle graceful server shutdown"""
        if self.server and self._started:
            logger.info("Stopping HTTP server...")
            self.server.should_exit = True
            await self.server.shutdown()
            logger.info("HTTP server stopped")

    async def launch_server(self):
        logger.info(f"Launching HTTP server on 0.0.0.0:{self.port}...")
        config = uvicorn.Config(
            self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="debug",
            timeout_keep_alive=300,
            limit_concurrency=200,
            backlog=4096,
            reload=False,  # Important: set to False for proper shutdown
            timeout_graceful_shutdown=30,  # Add explicit graceful shutdown timeout
        )
        self.server = uvicorn.Server(config)
        self._started = True
        try:
            await self.server.serve()
        finally:
            self._started = False
import asyncio
from dotenv import load_dotenv
import grpc
import signal
import logging
import traceback
from datetime import datetime
from pathlib import Path
from google.protobuf.empty_pb2 import Empty
from google.protobuf.json_format import MessageToDict
from grpc import ServicerContext
import os
from typing import Dict, Any, Union
from google.protobuf import struct_pb2
from node.storage.db.db import LocalDBPostgres
from node.user import register_user, check_user
from node.worker.docker_worker import execute_docker_agent
from node.worker.package_worker import (
    run_agent,
    run_memory,
    run_tool,
    run_environment,
    run_kb
)
from node.server import grpc_server_pb2, grpc_server_pb2_grpc
from node.schemas import (
    AgentDeployment,
    MemoryDeployment,
    ToolDeployment,
    EnvironmentDeployment,
    KBDeployment,
    AgentRunInput,
    MemoryRunInput,
    ToolRunInput,
    EnvironmentRunInput,
    KBRunInput,
    ModuleExecutionType
)
from node.module_manager import setup_module_deployment

load_dotenv()

file_path = Path(__file__).resolve()
root_dir = file_path.parent.parent.parent
MODULES_SOURCE_DIR = root_dir / os.getenv("MODULES_SOURCE_DIR")

logger = logging.getLogger(__name__)

class GrpcServerServicer(grpc_server_pb2_grpc.GrpcServerServicer):
    async def CheckUser(self, request, context):
        logger.info(f"Checking user: {request.public_key}")
        input_data = {"public_key": request.public_key}
        _, user_data = await check_user(input_data)
        logger.debug(f"User check result: {user_data}")
        return grpc_server_pb2.CheckUserResponse(**user_data)

    async def RegisterUser(self, request, context):
        logger.info(f"Registering user: {request.public_key}")
        input_data = {"public_key": request.public_key}
        success, user_data = await register_user(input_data)
        if success:
            logger.debug(f"User registration result: {user_data}")
            return grpc_server_pb2.RegisterUserResponse(**user_data)
        else:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details('User registration failed')
            return grpc_server_pb2.RegisterUserResponse()

    async def create_module(self, module_deployment: Union[AgentDeployment, MemoryDeployment, ToolDeployment, EnvironmentDeployment, KBDeployment]) -> Dict[str, Any]:
        """
        Unified method to create and install any type of module and its sub-modules
        """
        try:
            # Map deployment types to module types
            module_type_map = {
                AgentDeployment: "agent",
                MemoryDeployment: "memory",
                ToolDeployment: "tool",
                EnvironmentDeployment: "environment",
                KBDeployment: "kb"
            }

            # Determine module type based on deployment class
            module_type = None
            for deployment_class, type_name in module_type_map.items():
                if isinstance(module_deployment, deployment_class):
                    module_type = type_name
                    break

            if not module_type:
                raise Exception("Invalid module deployment type")

            logger.info(f"Creating {module_type}")

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
            raise Exception(f"Failed to create module: {str(e)}")

    async def RunModule(self, request, context):
        try:
            module_type = request.module_type
            module_configs = {
                "agent": {
                    "input_class": AgentRunInput,
                    "db_create": lambda db, input: db.create_agent_run(input),
                    "db_list": lambda db, id: db.list_agent_runs(id),
                    "worker": run_agent,
                    "docker_support": True,
                    "deployment_class": grpc_server_pb2.AgentDeployment
                },
                "memory": {
                    "input_class": MemoryRunInput,
                    "db_create": lambda db, input: db.create_memory_run(input),
                    "db_list": lambda db, id: db.list_memory_runs(id),
                    "worker": run_memory,
                    "docker_support": False,
                    "deployment_class": grpc_server_pb2.BaseDeployment
                },
                "tool": {
                    "input_class": ToolRunInput,
                    "db_create": lambda db, input: db.create_tool_run(input),
                    "db_list": lambda db, id: db.list_tool_runs(id),
                    "worker": run_tool,
                    "docker_support": False,
                    "deployment_class": grpc_server_pb2.ToolDeployment
                },
                "environment": {
                    "input_class": EnvironmentRunInput,
                    "db_create": lambda db, input: db.create_environment_run(input),
                    "db_list": lambda db, id: db.list_environment_runs(id),
                    "worker": run_environment,
                    "docker_support": False,
                    "deployment_class": grpc_server_pb2.BaseDeployment
                },
                "kb": {
                    "input_class": KBRunInput,
                    "db_create": lambda db, input: db.create_kb_run(input),
                    "db_list": lambda db, id: db.list_kb_runs(id),
                    "worker": run_kb,
                    "docker_support": False,
                    "deployment_class": grpc_server_pb2.BaseDeployment
                }
            }

            if module_type not in module_configs:
                raise ValueError(f"Invalid module type: {module_type}")

            config = module_configs[module_type]
            request_dict = MessageToDict(request, preserving_proto_field_name=True)

            deployment_field = f"{module_type}_deployment"
            if deployment_field in request_dict:
                deployment = request_dict[deployment_field]
                if 'node_input' in deployment:
                    deployment['node'] = deployment.pop('node_input')
                elif 'node_config' in deployment:
                    deployment['node'] = deployment.pop('node_config')
                request_dict['deployment'] = deployment

            run_input = config["input_class"](**request_dict)
            run_input.inputs = request_dict.get('inputs', {})

            logger.info(f"Run input: {run_input}")

            # if not run_input.deployment.initialized:
            #     deployment = await self.create_module(run_input.deployment)
            #     run_input.deployment = deployment

            async with LocalDBPostgres() as db:
                module_run = await config["db_create"](db, run_input)
                module_run_data = module_run.model_dump()

            yield grpc_server_pb2.ModuleRun(
                module_type=module_type,
                status="started",
                error=False,
                id=module_run_data['id'],
                consumer_id=module_run_data['consumer_id']
            )

            if isinstance(run_input.deployment.module, dict):
                execution_type = run_input.deployment.module["execution_type"]
            else:
                execution_type = run_input.deployment.module.execution_type

            if execution_type == ModuleExecutionType.package or execution_type == "package":
                task = config["worker"].delay(module_run_data)
            elif execution_type == ModuleExecutionType.docker or execution_type == "docker":
                if config["docker_support"]:
                    task = execute_docker_agent.delay(module_run_data)
                else:
                    raise Exception(f"Docker execution not supported for {module_type}")
            else:
                raise Exception(f"Invalid {module_type} run type")

            while not task.ready():
                yield grpc_server_pb2.ModuleRun(
                    module_type=module_type,
                    status="running",
                    error=False,
                    id=module_run_data['id'],
                    consumer_id=module_run_data['consumer_id'],
                    results=[]
                )
                await asyncio.sleep(5)

            async with LocalDBPostgres() as db:
                updated_run = await config["db_list"](db, module_run_data['id'])
                if isinstance(updated_run, list):
                    updated_run = updated_run[0]

            if isinstance(updated_run, dict):
                updated_run.pop("_sa_instance_state", None)
            else:
                updated_run = updated_run.__dict__
                updated_run.pop("_sa_instance_state", None)

            for time_field in ['created_time', 'start_processing_time', 'completed_time']:
                if time_field in updated_run and isinstance(updated_run[time_field], datetime):
                    updated_run[time_field] = updated_run[time_field].isoformat()

            inputs = struct_pb2.Struct()
            inputs.update(updated_run.get('inputs', {}))

            deployment_data = updated_run.get("deployment", {})
            DeploymentClass = config["deployment_class"]

            if 'node' in deployment_data:
                node_data = deployment_data['node']
                if 'id' in node_data:
                    node = grpc_server_pb2.NodeConfig(**node_data)
                else:
                    node = grpc_server_pb2.NodeConfigInput(**node_data)
                
                module_data = deployment_data.get("module", {})
                if not isinstance(module_data, dict):
                    module_data = module_data.__dict__
                module = grpc_server_pb2.Module(**module_data)
                
                config_data = deployment_data.get("config", {})
                if isinstance(config_data, dict):
                    config_struct = struct_pb2.Struct()
                    config_struct.update(config_data)
                else:
                    config_struct = config_data

                deployment = DeploymentClass(
                    name=deployment_data.get("name", ""),
                    module=module,
                    config=config_struct,
                    initialized=deployment_data.get("initialized", False)
                )
                
                if isinstance(node, grpc_server_pb2.NodeConfig):
                    deployment.node_config.CopyFrom(node)
                else:
                    deployment.node_input.CopyFrom(node)

            final_response = grpc_server_pb2.ModuleRun()

            # Set basic fields
            final_response.module_type = str(module_type)
            final_response.consumer_id = str(updated_run.get("consumer_id", ""))
            final_response.inputs.CopyFrom(inputs)
            final_response.status = str(updated_run.get("status", "completed"))
            final_response.error = bool(updated_run.get("error", False))
            final_response.id = str(updated_run.get("id", ""))

            # Extend list fields
            if updated_run.get("results"):
                final_response.results.extend([str(r) for r in updated_run.get("results", [])])

            # Set optional string fields
            if updated_run.get("error_message"):
                final_response.error_message = str(updated_run.get("error_message"))
            if updated_run.get("created_time"):
                final_response.created_time = str(updated_run.get("created_time"))
            if updated_run.get("start_processing_time"):
                final_response.start_processing_time = str(updated_run.get("start_processing_time"))
            if updated_run.get("completed_time"):
                final_response.completed_time = str(updated_run.get("completed_time"))
            if updated_run.get("duration") is not None:
                final_response.duration = float(updated_run.get("duration", 0.0))

            # Set deployment
            if module_type == "agent":
                final_response.agent_deployment.CopyFrom(deployment)
            elif module_type == "tool":
                final_response.tool_deployment.CopyFrom(deployment)
            elif module_type == "memory":
                final_response.memory_deployment.CopyFrom(deployment)
            elif module_type == "kb":
                final_response.kb_deployment.CopyFrom(deployment)
            elif module_type == "environment":
                final_response.environment_deployment.CopyFrom(deployment)

            yield final_response

        except Exception as e:
            logger.error(f"Error running {module_type} module: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            yield grpc_server_pb2.ModuleRun(
                module_type=module_type,
                status="error",
                error=True,
                error_message=str(e),
                consumer_id=request_dict.get('consumer_id', ''),
                id="",
                results=[]
            )

    async def CheckModuleRun(self, request, context):
        try:
            module_type = request.module_type
            run_id = request.run_id
            logger.info(f"Checking {module_type} run: {run_id}")

            # Map module types to DB list functions
            module_db_functions = {
                "agent": lambda db: db.list_agent_runs(run_id),
                "memory": lambda db: db.list_memory_runs(run_id),
                "tool": lambda db: db.list_tool_runs(run_id),
                "environment": lambda db: db.list_environment_runs(run_id),
                "kb": lambda db: db.list_kb_runs(run_id)
            }

            if module_type not in module_db_functions:
                raise ValueError(f"Invalid module type: {module_type}")

            async with LocalDBPostgres() as db:
                module_run = await module_db_functions[module_type](db)
                if isinstance(module_run, list):
                    module_run = module_run[0]
                module_run.pop("_sa_instance_state", None)

            if not module_run:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f'{module_type} run not found')
                return grpc_server_pb2.ModuleRun()

            return grpc_server_pb2.ModuleRun(
                module_type=module_type,
                **module_run
            )

        except Exception as e:
            logger.error(f"Error checking {module_type} run: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return grpc_server_pb2.ModuleRun()

    async def is_alive(self, request: Empty, context: ServicerContext) -> grpc_server_pb2.GeneralResponse:
        return grpc_server_pb2.GeneralResponse(ok=True)

    async def stop(self, request: Empty, context: ServicerContext) -> grpc_server_pb2.GeneralResponse:
        self.stop_event.set()
        return grpc_server_pb2.GeneralResponse(ok=True)

class GrpcServer:
    def __init__(
        self,
        host: str,
        port: int,
        node_id: str,
    ):
        self.host = host
        self.port = port
        self.node_id = node_id
        self.shutdown_event = asyncio.Event()

        options = [
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
            ("grpc.keepalive_time_ms", 30 * 60 * 1000),       # 30 minutes
            ("grpc.keepalive_timeout_ms", 30 * 60 * 1000),     # 30 minutes
            ("grpc.http2.max_pings_without_data", 0),
            ("grpc.http2.min_time_between_pings_ms", 30 * 60 * 1000),  # 30 minutes
            ("grpc.max_connection_idle_ms", 60 * 60 * 1000),   # 1 hour
            ("grpc.max_connection_age_ms", 2 * 60 * 60 * 1000),  # 2 hours
        ]

        self.server = grpc.aio.server(options=options)
        grpc_server_pb2_grpc.add_GrpcServerServicer_to_server(
            GrpcServerServicer(), self.server
        )
        self.listen_addr = f"0.0.0.0:{self.port}"
        self.server.add_insecure_port(self.listen_addr)

    async def graceful_shutdown(self, timeout: float = 3.0):
        logger.info("Starting graceful shutdown...")

        await self.server.stop(timeout)
        self.shutdown_event.set()
        logger.info("Graceful shutdown complete.")

    async def launch_server(self):
        logger.info(f"Starting server on {self.listen_addr}")
        await self.server.start()

        # Set up signal handlers for graceful shutdown
        for sig in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_running_loop().add_signal_handler(
                sig, lambda: asyncio.create_task(self.graceful_shutdown())
            )

        try:
            await self.shutdown_event.wait()
        finally:
            await self.server.wait_for_termination()



if __name__ == "__main__":
    # Create and configure logging first
    logging.basicConfig(level=logging.INFO)
    
    # Create a new event loop explicitly
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        server = GrpcServer(
            host="0.0.0.0",
            port=7002,
            node_type="worker",
            node_id="1234567890"
        )
        loop.run_until_complete(server.launch_server())
    finally:
        loop.close()
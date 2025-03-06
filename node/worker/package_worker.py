import asyncio
from contextlib import contextmanager
import functools
import inspect
from importlib import util
import json
import logging
import os
import pytz
from pathlib import Path
import sys
import traceback
from datetime import datetime
from dotenv import load_dotenv, dotenv_values
from typing import Union
import sys

from node.module_manager import install_module_with_lock, load_and_validate_input_schema
from node.schemas import AgentRun, MemoryRun, ToolRun, EnvironmentRun, OrchestratorRun, KBRun
from node.worker.main import app
from node.worker.utils import prepare_input_dir, update_db_with_status_sync, upload_to_ipfs

logger = logging.getLogger(__name__)

load_dotenv()

file_path = Path(__file__).resolve()
root_dir = file_path.parent.parent.parent

_BASE_OUTPUT_DIR = os.getenv("BASE_OUTPUT_DIR")
BASE_OUTPUT_DIR = root_dir / _BASE_OUTPUT_DIR

_MODULES_SOURCE_DIR = os.getenv("MODULES_SOURCE_DIR")
MODULES_SOURCE_DIR = root_dir / _MODULES_SOURCE_DIR

if MODULES_SOURCE_DIR not in sys.path:
    sys.path.append(MODULES_SOURCE_DIR)

@app.task(bind=True, acks_late=True)
def run_agent(self, agent_run, user_env_data = {}):
    try:
        agent_run = AgentRun(**agent_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(agent_run, user_env_data))
    finally:
        # Force cleanup of channels
        app.backend.cleanup()

@app.task(bind=True, acks_late=True)
def run_memory(self, memory_run, user_env_data = {}):
    try:
        memory_run = MemoryRun(**memory_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(memory_run, user_env_data))
    finally:
        # Force cleanup of channels
        app.backend.cleanup()

@app.task(bind=True, acks_late=True)
def run_tool(self, tool_run, user_env_data = {}):
    try:
        tool_run = ToolRun(**tool_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(tool_run, user_env_data))
    finally:
        # Force cleanup of channels
        app.backend.cleanup()

@app.task(bind=True, acks_late=True)
def run_orchestrator(self, orchestrator_run, user_env_data = {}):
    try:
        orchestrator_run = OrchestratorRun(**orchestrator_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(orchestrator_run, user_env_data))
    finally:
        # Force cleanup of channels
        app.backend.cleanup()

@app.task(bind=True, acks_late=True)
def run_environment(self, environment_run, user_env_data = {}):
    try:
        environment_run = EnvironmentRun(**environment_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(environment_run, user_env_data))
    finally:
        # Force cleanup of channels
        app.backend.cleanup()

@app.task(bind=True, acks_late=True)
def run_kb(self, kb_run, user_env_data = {}):
    try:
        kb_run = KBRun(**kb_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(kb_run, user_env_data))
    finally:
        # Force cleanup of channels
        app.backend.cleanup()

async def _run_module_async(module_run: Union[AgentRun, MemoryRun, ToolRun, OrchestratorRun, EnvironmentRun, KBRun], user_env_data = {}) -> None:
    """Handles execution of agent, memory, orchestrator, and environment runs.
    
    Args:
        module_run: Either an AgentRun, MemoryRun, OrchestratorRun, or EnvironmentRun object
    """
    try:
        module_run_engine = ModuleRunEngine(module_run)

        module_version = f"v{module_run_engine.module['module_version']}"
        module_name = module_run_engine.module["name"]
        module = module_run.deployment.module

        logger.info(f"Received {module_run_engine.module_type} run: {module_run} - Checking if {module_run_engine.module_type} {module_name} version {module_version} is installed")

        try:
            await install_module_with_lock(module)
        except Exception as e:
            error_msg = (f"Failed to install or verify {module_run_engine.module_type} {module_name}: {str(e)}")
            logger.error(error_msg)
            logger.error(f"Traceback: {traceback.format_exc()}")
            if "Dependency conflict detected" in str(e):
                logger.error("This error is likely due to a mismatch in naptha-sdk versions. Please check and align the versions in both the agent and the main project.")
            await handle_failure(error_msg=error_msg, module_run=module_run)
            return

        await module_run_engine.init_run()
        await module_run_engine.start_run(user_env_data)

        if module_run_engine.module_run.status == "completed":
            await module_run_engine.complete()
        elif module_run_engine.module_run.status == "error":
            await module_run_engine.fail()

    except Exception as e:
        error_msg = f"Error in _run_module_async: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        await handle_failure(error_msg=error_msg, module_run=module_run)
        return

async def handle_failure(
    error_msg: str, 
    module_run: Union[AgentRun, OrchestratorRun, EnvironmentRun]
) -> None:
    """Handle failure for any type of module run.
    
    Args:
        error_msg: Error message to store
        module_run: Module run object (AgentRun, OrchestratorRun, or EnvironmentRun)
    """
    module_run.status = "error"
    module_run.error = True 
    module_run.error_message = error_msg
    module_run.completed_time = datetime.now(pytz.utc).isoformat()

    # Calculate duration if possible
    if hasattr(module_run, "start_processing_time") and module_run.start_processing_time:
        module_run.duration = (
            datetime.fromisoformat(module_run.completed_time)
            - datetime.fromisoformat(module_run.start_processing_time)
        ).total_seconds()
    else:
        module_run.duration = 0

    try:
        await update_db_with_status_sync(module_run=module_run)
    except Exception as db_error:
        logger.error(f"Failed to update database after error: {str(db_error)}")

async def maybe_async_call(func, *args, **kwargs):
    if inspect.iscoroutinefunction(func):
        # If it's an async function, await it directly
        return await func(*args, **kwargs)
    else:
        # If it's a sync function, run it in an executor to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, functools.partial(func, *args, **kwargs)
        )

class ModuleLoader:
    def __init__(self, module_name: str, venv_path: str, module_dir: Path):
        self.module_name = module_name
        self.venv_path = venv_path
        self.module_dir = module_dir
        self.original_sys_path = None
        self.original_cwd = None

    @contextmanager
    def package_context(self, env_vars):
        """Temporarily modify sys.path and working directory for package imports"""
        dot_env_vars = dotenv_values(os.path.join(os.path.dirname(__file__), '../../.env'))
        old_env = os.environ.copy()

        try:
            self.original_sys_path = sys.path.copy()
            self.original_cwd = os.getcwd()
            
            # Change working directory to module directory
            os.chdir(str(self.module_dir))
            
            # Add both site-packages and module root directory to path
            # UV uses a slightly different structure for virtual environments
            venv_site_packages = os.path.join(
                self.venv_path, 
                'lib', 
                f'python{sys.version_info.major}.{sys.version_info.minor}',
                'site-packages'
            )
            
            # Ensure module directory is first in path
            if str(self.module_dir) in sys.path:
                sys.path.remove(str(self.module_dir))
            if str(venv_site_packages) in sys.path:
                sys.path.remove(str(venv_site_packages))
                
            sys.path.insert(0, str(self.module_dir))
            sys.path.insert(1, str(venv_site_packages))

            # Remove env data from .env and add user env data
            for key in dot_env_vars:
                if key in os.environ:
                    os.environ[key] = ""

            if env_vars:
                os.environ.update(env_vars)
            
            logger.debug(f"Modified sys.path: {sys.path[:2]}")
            logger.debug(f"Current working directory: {os.getcwd()}")
            logger.debug(f"Injected user env data")
            
            yield
            
        finally:
            if self.original_sys_path:
                sys.path = self.original_sys_path
            if self.original_cwd:
                os.chdir(self.original_cwd)

            os.environ.clear()
            os.environ.update(old_env)

    async def load_and_run(self, module_path: Path, entrypoint: str, module_run, user_env_data = {}):
        with self.package_context(user_env_data):
            try:
                # Remove any existing module references
                for key in list(sys.modules.keys()):
                    if key.startswith(self.module_name):
                        del sys.modules[key]

                # Import the run module directly first
                spec = util.spec_from_file_location(
                    f"{self.module_name}.run", 
                    str(module_path)
                )
                if not spec or not spec.loader:
                    raise ImportError(f"Could not load module spec from {module_path}")
                
                module = util.module_from_spec(spec)
                sys.modules[f"{self.module_name}.run"] = module
                spec.loader.exec_module(module)

                # Get and execute the entrypoint function
                run_func = getattr(module, entrypoint)
                
                # Convert module_run to dict if it's a pydantic model
                if hasattr(module_run, 'model_dump'):
                    module_run_dict = module_run.model_dump()
                else:
                    module_run_dict = module_run
                
                if inspect.iscoroutinefunction(run_func):
                    result = await run_func(module_run=module_run_dict)
                else:
                    result = await maybe_async_call(run_func, module_run=module_run_dict)
                
                return result

            except Exception as e:
                logger.error(f"Module import paths: {sys.path[:2]}")
                logger.error(f"Current working directory: {os.getcwd()}")
                logger.error(f"Module directory contents: {list(Path(os.getcwd()).glob('*'))}")
                raise RuntimeError(f"Module execution failed: {str(e)}") from e

class ModuleRunEngine:
    def __init__(self, module_run: Union[AgentRun, MemoryRun, ToolRun, EnvironmentRun, KBRun]):
        self.module_run = module_run
        self.deployment = module_run.deployment
        self.module = self.deployment.module
        self.module_type = module_run.deployment.module['module_type']

        self.module_name = self.module["name"]
        self.module_version = f"v{self.module['module_version']}"
        self.parameters = module_run.inputs

        self.consumer = {
            "public_key": module_run.consumer_id.split(":")[1],
            "id": module_run.consumer_id,
        }

    async def init_run(self):
        logger.info(f"Initializing {self.module_type} run")
        self.module_run.status = "processing"
        self.module_run.start_processing_time = datetime.now(pytz.timezone("UTC")).isoformat()

        await update_db_with_status_sync(module_run=self.module_run)

        if "input_dir" in self.parameters or "input_ipfs_hash" in self.parameters:
            self.parameters = prepare_input_dir(
                parameters=self.parameters,
                input_dir=self.parameters.get("input_dir", None),
                input_ipfs_hash=self.parameters.get("input_ipfs_hash", None),
            )

        # Load the module
        self.module_run = await load_and_validate_input_schema(self.module_run)

    async def start_run(self, env_data = {}):
        """Executes the module run"""
        logger.info(f"Starting {self.module_type} run")
        self.module_run.status = "running"
        await update_db_with_status_sync(module_run=self.module_run)

        try:
            # Setup paths
            modules_source_dir = Path(MODULES_SOURCE_DIR) / self.module_name
            module_dir = modules_source_dir  
            venv_dir = module_dir / ".venv"
            module_path = module_dir / self.module_name / "run.py"
            
            # Log package structure
            logger.info(f"Checking module structure...")
            logger.debug(f"__init__.py exists: {(module_dir / self.module_name / '__init__.py').exists()}")
            logger.debug(f"schemas.py exists: {(module_dir / self.module_name / 'schemas.py').exists()}")
            logger.debug(f"Module directory contents: {list((module_dir / self.module_name).glob('*'))}")

            # Get entrypoint name
            entrypoint = self.module['module_entrypoint'].split('.')[0] if 'module_entrypoint' in self.module else 'run'
            
            # Initialize loader with module directory
            loader = ModuleLoader(self.module_name, str(venv_dir), module_dir)
            
            # Run module
            response = await loader.load_and_run(
                module_path=module_path,
                entrypoint=entrypoint,
                module_run=self.module_run,
                user_env_data=env_data
            )
            
            # Handle response
            if isinstance(response, str):
                self.module_run.results = [response]
            else:
                self.module_run.results = [json.dumps(response)]
                
            if self.module_type == "agent":
                await self.handle_output(self.module_run, response)
                
            self.module_run.status = "completed"

        except Exception as e:
            logger.error(f"Error running {self.module_type}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    async def handle_output(self, module_run, results):
        """Handles the output of the module run (only for agent and tool runs)"""
        if module_run.deployment.data_generation_config:
            save_location = module_run.deployment.data_generation_config.save_outputs_location
            if save_location:
                module_run.deployment.data_generation_config.save_outputs_location = save_location

            if module_run.deployment.data_generation_config.save_outputs:
                if save_location == "node":
                    if ':' in module_run.id:
                        output_path = f"{BASE_OUTPUT_DIR}/{module_run.id.split(':')[1]}"
                    else:
                        output_path = f"{BASE_OUTPUT_DIR}/{module_run.id}"
                    module_run.deployment.data_generation_config.save_outputs_path = output_path
                    if not os.path.exists(output_path):
                        os.makedirs(output_path)
                elif save_location == "ipfs":
                    save_path = getattr(module_run.deployment.data_generation_config, "save_outputs_path")
                    out_msg = upload_to_ipfs(save_path)
                    out_msg = f"IPFS Hash: {out_msg}"
                    logger.info(f"Output uploaded to IPFS: {out_msg}")
                    self.module_run.results = [out_msg]

    async def complete(self):
        """Marks the module run as completed"""
        self.module_run.status = "completed"
        self.module_run.error = False
        self.module_run.error_message = ""
        self.module_run.completed_time = datetime.now(pytz.utc).isoformat()
        self.module_run.duration = (
            datetime.fromisoformat(self.module_run.completed_time)
            - datetime.fromisoformat(self.module_run.start_processing_time)
        ).total_seconds()
        await update_db_with_status_sync(module_run=self.module_run)
        logger.info(f"{self.module_type.title()} run completed")

    async def fail(self):
        """Marks the module run as failed"""
        logger.error(f"Error running {self.module_type}")
        error_details = traceback.format_exc()
        logger.error(f"Traceback: {error_details}")
        self.module_run.status = "error"
        self.module_run.error = True
        self.module_run.error_message = error_details
        self.module_run.completed_time = datetime.now(pytz.utc).isoformat()
        self.module_run.duration = (
            datetime.fromisoformat(self.module_run.completed_time)
            - datetime.fromisoformat(self.module_run.start_processing_time)
        ).total_seconds()
        await update_db_with_status_sync(module_run=self.module_run)

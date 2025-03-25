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
import subprocess
import tempfile

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
def run_agent(self, agent_run, user_env_data={}):
    try:
        agent_run = AgentRun(**agent_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(agent_run, user_env_data))
    finally:
        app.backend.cleanup()

@app.task(bind=True, acks_late=True)
def run_memory(self, memory_run, user_env_data={}):
    try:
        memory_run = MemoryRun(**memory_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(memory_run, user_env_data))
    finally:
        app.backend.cleanup()

@app.task(bind=True, acks_late=True)
def run_tool(self, tool_run, user_env_data={}):
    try:
        tool_run = ToolRun(**tool_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(tool_run, user_env_data))
    finally:
        app.backend.cleanup()

@app.task(bind=True, acks_late=True)
def run_orchestrator(self, orchestrator_run, user_env_data={}):
    try:
        orchestrator_run = OrchestratorRun(**orchestrator_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(orchestrator_run, user_env_data))
    finally:
        app.backend.cleanup()

@app.task(bind=True, acks_late=True)
def run_environment(self, environment_run, user_env_data={}):
    try:
        environment_run = EnvironmentRun(**environment_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(environment_run, user_env_data))
    finally:
        app.backend.cleanup()

@app.task(bind=True, acks_late=True)
def run_kb(self, kb_run, user_env_data={}):
    try:
        kb_run = KBRun(**kb_run)
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run_module_async(kb_run, user_env_data))
    finally:
        app.backend.cleanup()

async def _run_module_async(module_run: Union[AgentRun, MemoryRun, ToolRun, OrchestratorRun, EnvironmentRun, KBRun], user_env_data={}) -> None:
    try:
        module_run_engine = ModuleRunEngine(module_run)
        module_version = f"v{module_run_engine.module['module_version']}"
        module_name = module_run_engine.module["name"]
        module = module_run.deployment.module

        logger.info(f"Received {module_run_engine.module_type} run: {module_run} - Checking if {module_run_engine.module_type} {module_name} version {module_version} is installed")
        # try:
        #     await install_module_with_lock(module)
        # except Exception as e:
        #     error_msg = f"Failed to install or verify {module_run_engine.module_type} {module_name}: {str(e)}"
        #     logger.error(error_msg)
        #     logger.error(f"Traceback: {traceback.format_exc()}")
        #     if "Dependency conflict detected" in str(e):
        #         logger.error("This error is likely due to a mismatch in naptha-sdk versions. Please check and align the versions in both the agent and the main project.")
        #     await handle_failure(error_msg=error_msg, module_run=module_run)
        #     return

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

async def handle_failure(error_msg: str, module_run: Union[AgentRun, OrchestratorRun, EnvironmentRun]) -> None:
    module_run.status = "error"
    module_run.error = True
    module_run.error_message = error_msg
    module_run.completed_time = datetime.now(pytz.utc).isoformat()
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
        return await func(*args, **kwargs)
    else:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))

class ModuleLoader:
    def __init__(self, module_name: str, venv_path: str, module_dir: Path):
        self.module_name = module_name
        self.venv_path = venv_path
        self.module_dir = module_dir
        self.original_sys_path = None
        self.original_cwd = None

    @contextmanager
    def package_context(self, env_vars):
        dot_env_vars = dotenv_values(os.path.join(os.path.dirname(__file__), '../../.env'))
        old_env = os.environ.copy()
        try:
            self.original_sys_path = sys.path.copy()
            self.original_cwd = os.getcwd()
            os.chdir(str(self.module_dir))
            venv_site_packages = os.path.join(
                self.venv_path,
                'lib',
                f'python{sys.version_info.major}.{sys.version_info.minor}',
                'site-packages'
            )
            if str(self.module_dir) in sys.path:
                sys.path.remove(str(self.module_dir))
            if str(venv_site_packages) in sys.path:
                sys.path.remove(str(venv_site_packages))
            sys.path.insert(0, str(self.module_dir))
            sys.path.insert(1, str(venv_site_packages))
            for key in dot_env_vars:
                if key in os.environ:
                    os.environ[key] = ""
            if env_vars:
                os.environ.update(env_vars)
            logger.debug(f"Modified sys.path: {sys.path[:2]}")
            logger.debug(f"Current working directory: {os.getcwd()}")
            logger.debug("Injected user env data")
            yield
        finally:
            if self.original_sys_path:
                sys.path = self.original_sys_path
            if self.original_cwd:
                os.chdir(self.original_cwd)
            os.environ.clear()
            os.environ.update(old_env)

    def _load_and_run_subprocess(self, module_path: Path, entrypoint: str, module_run, user_env_data={}):
        # Convert module_run to a JSON-serializable dict if it's a pydantic BaseModel
        if hasattr(module_run, "model_dump"):
            module_run_data = module_run.model_dump()
        elif hasattr(module_run, "dict"):
            module_run_data = module_run.dict()
        else:
            module_run_data = module_run

        with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as tmp:
            json.dump(module_run_data, tmp)
            tmp.flush()
            tmp_name = tmp.name

        # Create environment for subprocess and update it with user_env_data
        env = os.environ.copy()
        env.update(user_env_data)
        venv_site_packages = os.path.join(
            self.venv_path,
            'lib',
            f'python{sys.version_info.major}.{sys.version_info.minor}',
            'site-packages'
        )
        env['PYTHONPATH'] = f"{self.module_dir}{os.pathsep}{venv_site_packages}{os.pathsep}{env.get('PYTHONPATH', '')}"

        # Use a multi-line inline code string to ensure proper formatting and error handling.
        inline_code = (
            "import sys, json, inspect, asyncio, logging\n"
            "logging.disable(logging.CRITICAL)\n"
            "try:\n"
            "    from {module_name}.run import {entrypoint}\n"
            "except Exception as e:\n"
            "    sys.exit(json.dumps({{'error': 'Import failed: ' + str(e)}}))\n"
            "try:\n"
            "    data = json.load(open(sys.argv[1]))\n"
            "except Exception as e:\n"
            "    sys.exit(json.dumps({{'error': 'JSON load failed: ' + str(e)}}))\n"
            "try:\n"
            "    result = {entrypoint}(data)\n"
            "    if inspect.iscoroutine(result):\n"
            "        result = asyncio.run(result)\n"
            "except Exception as e:\n"
            "    result = {{'error': str(e)}}\n"
            "sys.stdout.write(json.dumps(result))\n"
            "sys.stdout.flush()\n"
        ).format(module_name=self.module_name, entrypoint=entrypoint)

        venv_python = os.path.join(self.venv_path, 'bin', 'python')
        python_executable = venv_python if os.path.exists(venv_python) else sys.executable

        cmd = [python_executable, "-c", inline_code, tmp_name]
        try:
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Subprocess module execution failed: {e.stderr}")

    async def load_and_run(self, module_path: Path, entrypoint: str, module_run, user_env_data={}):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._load_and_run_subprocess,
            module_path,
            entrypoint,
            module_run,
            user_env_data
        )

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
        self.module_run = await load_and_validate_input_schema(self.module_run)

    async def start_run(self, env_data={}):
        logger.info(f"Starting {self.module_type} run")
        logger.info(f"Env data: {env_data}")
        self.module_run.status = "running"
        await update_db_with_status_sync(module_run=self.module_run)
        try:
            modules_source_dir = Path(MODULES_SOURCE_DIR) / self.module_name
            module_dir = modules_source_dir  
            venv_dir = module_dir / ".venv"
            module_path = module_dir / self.module_name / "run.py"
            logger.info("Checking module structure...")
            logger.debug(f"__init__.py exists: {(module_dir / self.module_name / '__init__.py').exists()}")
            logger.debug(f"schemas.py exists: {(module_dir / self.module_name / 'schemas.py').exists()}")
            logger.debug(f"Module directory contents: {list((module_dir / self.module_name).glob('*'))}")
            entrypoint = self.module['module_entrypoint'].split('.')[0] if 'module_entrypoint' in self.module else 'run'
            loader = ModuleLoader(self.module_name, str(venv_dir), module_dir)
            response = await loader.load_and_run(
                module_path=module_path,
                entrypoint=entrypoint,
                module_run=self.module_run,
                user_env_data=env_data
            )
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

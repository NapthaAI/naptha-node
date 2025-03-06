from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dotenv import load_dotenv
import fcntl
import shutil
from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError
import importlib
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import time
import traceback
from pip._internal.cli.main import main as pip_main
from pydantic import BaseModel
import sys
from typing import Union, Dict
import uuid
import yaml
from node.schemas import (
    AgentDeployment, 
    AgentRun, 
    EnvironmentDeployment,
    EnvironmentRun,
    OrchestratorRun, 
    LLMConfig, 
    DataGenerationConfig,
    KBRun,
    KBDeployment,
    MemoryRun,
    MemoryDeployment,
    ToolRun,
    ToolDeployment,
    Module,
    OrchestratorDeployment,
    OrchestratorRun
)
from node.worker.utils import download_from_ipfs, unzip_file
from node.utils import get_node_config
from node.storage.hub.hub import list_modules, list_nodes

logger = logging.getLogger(__name__)
load_dotenv()

file_path = Path(__file__).resolve()
root_dir = file_path.parent.parent
BASE_OUTPUT_DIR = root_dir / os.getenv("BASE_OUTPUT_DIR")
MODULES_SOURCE_DIR = root_dir / os.getenv("MODULES_SOURCE_DIR")
NODE_IP = os.getenv("NODE_IP")

INSTALLED_MODULES = {}

class LockAcquisitionError(Exception):
    pass

@contextmanager
def file_lock(lock_file, timeout=30):
    lock_fd = None
    try:
        # Ensure the directory exists
        lock_dir = os.path.dirname(lock_file)
        os.makedirs(lock_dir, exist_ok=True)

        start_time = time.time()
        while True:
            try:
                lock_fd = open(lock_file, "w")
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except IOError:
                if time.time() - start_time > timeout:
                    raise LockAcquisitionError(f"Failed to acquire lock after {timeout} seconds")
                time.sleep(1)

        yield lock_fd

    finally:
        if lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

def is_module_installed(module_name: str, required_version: str) -> bool:
    try:
        modules_source_dir = Path(MODULES_SOURCE_DIR) / module_name

        # First check if the directory exists
        if not modules_source_dir.exists():
            logger.warning(f"Module directory for {module_name} does not exist")
            return False

        # Check if pyproject.toml exists (indicates a valid poetry project)
        if not (modules_source_dir / "pyproject.toml").exists():
            logger.warning(f"No pyproject.toml found for {module_name}")
            return False

        # Check if .venv exists (indicates installed dependencies)
        if not (modules_source_dir / ".venv").exists():
            logger.warning(f"No virtual environment found for {module_name}")
            return False

        try:    
            repo = Repo(modules_source_dir)
            if repo.head.is_detached:
                current_tag = next((tag.name for tag in repo.tags if tag.commit == repo.head.commit), None)
            else:
                current_tag = next((tag.name for tag in repo.tags if tag.commit == repo.head.commit), None)

            if current_tag:
                logger.info(f"Module {module_name} is at tag: {current_tag}")
                current_version = (current_tag[1:] if current_tag.startswith("v") else current_tag)
                required_version = (
                    required_version[1:]
                    if required_version.startswith("v")
                    else required_version
                )
                return current_version == required_version
            else:
                logger.warning(f"No tag found for current commit in {module_name}")
                return False
                
        except (InvalidGitRepositoryError, GitCommandError) as e:
            logger.error(f"Git error for {module_name}: {str(e)}")
            return False

    except Exception as e:
        logger.warning(f"Error checking module {module_name}: {str(e)}")
        return False

async def install_module_with_lock(module: Union[Dict, Module]):
    if isinstance(module, dict):
        module_name = module["name"]
        url = module["module_url"]
        run_version = module["module_version"]
    else:
        module_name = module.name
        url = module.module_url
        run_version = module.module_version

    if module_name in INSTALLED_MODULES:
        installed_version = INSTALLED_MODULES[module_name]
        if installed_version == run_version:
            logger.info("Running uv update")
            modules_source_dir = Path(MODULES_SOURCE_DIR) / module_name
            venv_dir = modules_source_dir / ".venv"
            pip_path = venv_dir / "bin" / "pip"
            
            # Use pip from the virtual environment to update the package
            update_cmd = [str(pip_path), "install", "--upgrade", "-e", "."]
            proc = subprocess.run(update_cmd, capture_output=True, text=True, cwd=modules_source_dir)
            logger.debug(f"Update output: {proc.stdout}")
            logger.debug(f"Module {module_name} version {run_version} is already installed")
            return True

    lock_file = Path(MODULES_SOURCE_DIR) / f"{module_name}.lock"
    logger.info(f"Lock file: {lock_file}")
    try:
        with file_lock(lock_file):
            logger.info(f"Acquired lock for {module_name}")

            if not is_module_installed(module_name, run_version):
                logger.info(f"Module {module_name} version {run_version} is not installed. Attempting to install...")
                if not url:
                    raise ValueError(f"Module URL is required for installation of {module_name}")
                install_module(module_name, run_version, url)

            # Verify module installation
            if not verify_module_installation(module_name):
                raise RuntimeError(f"Module {module_name} failed verification after installation")

            logger.info(f"Module {module_name} version {run_version} is installed and verified")
            INSTALLED_MODULES[module_name] = run_version
    except LockAcquisitionError as e:
        error_msg = f"Failed to acquire lock for module {module_name}: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise RuntimeError(error_msg) from e
    except Exception as e:
        error_msg = f"Failed to install or verify module {module_name}: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise RuntimeError(error_msg) from e

def verify_module_installation(module_name: str) -> bool:
    try:
        modules_source_dir = Path(MODULES_SOURCE_DIR) / module_name
        venv_dir = modules_source_dir / ".venv"
        
        # Get python path from the module's venv
        if os.name == 'nt':  # Windows
            python_path = venv_dir / "Scripts" / "python"
        else:  # Unix
            python_path = venv_dir / "bin" / "python"
        
        # Try to import the module using the venv's Python
        result = subprocess.run(
            [str(python_path), "-c", f"import {module_name}.run"],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            error_msg = f"Error importing module {module_name}: {result.stderr}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
            
        return True
        
    except Exception as e:
        error_msg = f"Error verifying module {module_name}: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise RuntimeError(error_msg) from e
    

async def download_persona(persona_module: str):
    if not persona_module:
        logger.info("No personas to install")
        return

    personas_base_dir = Path(MODULES_SOURCE_DIR) / "personas"
    personas_base_dir.mkdir(exist_ok=True)

    persona_url = persona_module.module_url

    logger.info(f"Downloading persona {persona_url}")
    if persona_url in ["", None, " "]:
        logger.warning(f"Skipping empty persona URL")
        return None
    # identify if the persona is a git repo or an ipfs hash
    if "ipfs://" in persona_url:
        return await download_persona_from_ipfs(persona_url, personas_base_dir)
    else:
        return await download_persona_from_git(persona_url, personas_base_dir)
        
async def download_persona_from_ipfs(persona_url: str, personas_base_dir: Path):
    try:
        if "::" not in persona_url:
            raise ValueError(f"Invalid persona URL: {persona_url}. Expected format: ipfs://ipfs_hash::persona_folder_name")
        
        persona_folder_name = persona_url.split("::")[1]
        persona_ipfs_hash = persona_url.split("::")[0].split("ipfs://")[1]
        persona_dir = personas_base_dir / persona_folder_name

        # if the persona directory exists, continue without downloading
        if persona_dir.exists():
            logger.info(f"Persona {persona_folder_name} already exists")
            # remove the directory
            shutil.rmtree(persona_dir)
            logger.debug(f"Removed existing persona directory: {persona_dir}")

        persona_temp_zip_path = download_from_ipfs(persona_ipfs_hash, personas_base_dir)
        unzip_file(persona_temp_zip_path, persona_dir)
        os.remove(persona_temp_zip_path)
        logger.info(f"Successfully installed persona: {persona_folder_name}")
        return persona_dir
    except Exception as e:
        error_msg = f"Error installing persona from {persona_url}: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise RuntimeError(error_msg) from e

async def download_persona_from_git(repo_url: str, personas_base_dir: Path):
    try:
        repo_name = repo_url.split('/')[-1]
        persona_dir = personas_base_dir / repo_name

        if persona_dir.exists():
            # remove the directory
            shutil.rmtree(persona_dir)
            logger.debug(f"Removed existing persona directory: {persona_dir}")
            # clone the repository again
            Repo.clone_from(repo_url, persona_dir)
            logger.info(f"Successfully cloned persona: {repo_name}")
        else:
            logger.info(f"Cloning new persona repository: {repo_name}")
            Repo.clone_from(repo_url, persona_dir)
            logger.info(f"Successfully cloned persona: {repo_name}")
        return persona_dir
    except Exception as e:
        error_msg = f"Error installing persona from {repo_url}: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise RuntimeError(error_msg) from e


def install_module_from_ipfs(module_name: str, module_version: str, module_source_url: str):
    logger.info(f"Installing/updating module {module_name} version {module_version}")
    modules_source_dir = Path(MODULES_SOURCE_DIR) / module_name
    logger.debug(f"Module path exists: {modules_source_dir.exists()}")
    try:
        module_ipfs_hash = module_source_url.split("ipfs://")[1]
        module_temp_zip_path = download_from_ipfs(module_ipfs_hash, MODULES_SOURCE_DIR)
        unzip_file(module_temp_zip_path, modules_source_dir)
        os.remove(module_temp_zip_path)

        # remove the .venv directory
        venv_dir = modules_source_dir / ".venv"
        if venv_dir.exists():
            shutil.rmtree(venv_dir)
            logger.debug(f"Removed existing venv directory: {venv_dir}")

    except Exception as e:
        error_msg = f"Error installing {module_name}: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise RuntimeError(error_msg) from e


def install_module_from_git(module_name: str, module_version: str, module_source_url: str):
    logger.info(f"Installing/updating module {module_name} version {module_version}")
    modules_source_dir = Path(MODULES_SOURCE_DIR) / module_name
    logger.debug(f"Module path exists: {modules_source_dir.exists()}")
    try:
        if modules_source_dir.exists():
            logger.debug(f"Updating existing repository for {module_name}")
            repo = Repo(modules_source_dir)
            repo.remotes.origin.fetch()
            repo.git.checkout(module_version)
            logger.debug(f"Successfully updated {module_name} to version {module_version}")
        else:
            # Clone new repository
            logger.debug(f"Cloning new repository for {module_name}")
            Repo.clone_from(module_source_url, modules_source_dir)
            repo = Repo(modules_source_dir)
            repo.git.checkout(module_version)
            logger.debug(f"Successfully cloned {module_name} version {module_version}")

    except Exception as e:
        error_msg = f"Error installing {module_name}: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Traceback: {traceback.format_exc()}")
        if "Dependency conflict detected" in str(e):
            error_msg += "\nThis is likely due to a mismatch in naptha-sdk versions between the module and the main project."
        raise RuntimeError(error_msg) from e
    
def run_uv_command(command, module_name=None):
    try:
        if module_name:
            modules_source_dir = Path(MODULES_SOURCE_DIR) / module_name
            result = subprocess.run(
                ["uv"] + command,
                check=True,
                capture_output=True,
                text=True,
                cwd=modules_source_dir
            )
        else:
            result = subprocess.run(
                ["uv"] + command,
                check=True,
                capture_output=True,
                text=True
            )
        return result.stdout
    except subprocess.CalledProcessError as e:
        error_msg = (
            f"UV command failed: {e.cmd}\n"
            f"Stdout: {e.stdout}\n"
            f"Stderr: {e.stderr}"
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e

def install_module(module_name: str, module_version: str, module_source_url: str):
    logger.info(f"Installing/updating module {module_name} version {module_version}")
    modules_source_dir = Path(MODULES_SOURCE_DIR) / module_name
    logger.debug(f"Module path exists: {modules_source_dir.exists()}")

    try:
        if "ipfs://" in module_source_url:
            install_module_from_ipfs(module_name, module_version, module_source_url)
        else:
            install_module_from_git(module_name, module_version, module_source_url)

        # Create virtual environment using UV directly in the module folder
        subprocess.run(["uv", "venv", ".venv"], check=True, cwd=modules_source_dir)
        
        # Install pip in the virtual environment
        venv_dir = modules_source_dir / ".venv"
        python_path = venv_dir / "bin" / "python"
        
        # Install pip in the virtual environment
        venv_dir = modules_source_dir / ".venv"
        python_path = venv_dir / "bin" / "python"
        subprocess.run([
            str(python_path), "-c",
            "import sys; from urllib.request import urlopen; exec(urlopen('https://bootstrap.pypa.io/get-pip.py').read())"
        ], check=True)

        # Install the module in development mode
        pip_path = venv_dir / "bin" / "pip"
        install_cmd = [str(pip_path), "install", "."]

        # Capture stdout/stderr
        proc = subprocess.run(install_cmd, capture_output=True, text=True, cwd=modules_source_dir)
        logger.debug(f"Pip install stdout: {proc.stdout}")
        logger.debug(f"Pip install stderr: {proc.stderr}")

        if proc.returncode != 0:
            raise RuntimeError(f"Pip install failed: {proc.stderr}")

        if not verify_module_installation(module_name):
            raise RuntimeError(f"Module {module_name} failed verification after installation")

        return {"name": module_name, "module_version": module_version, "status": "success"}

    except Exception as e:
        error_msg = f"Error installing {module_name}: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


def load_persona(persona_dir: str, persona_module: Module):
    """Load persona from a JSON or YAML file in a git repository."""
    try:
        logger.info(f"Loading persona {persona_module.name} from {persona_dir}")
        persona_dir = Path(persona_dir)
        persona_file = persona_dir / persona_module.module_entrypoint

        with open(persona_file, 'r') as file:
            if persona_file.suffix.lower() in ['.yaml', '.yml']:
                persona_data = yaml.safe_load(file)
            else:
                persona_data = json.load(file)
            return persona_data
        
    except Exception as e:
        logger.error(f"Error loading persona from {persona_dir}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

async def load_data_generation_config(deployment, default_deployment):
    logger.info(f"Loading data generation config for {deployment.name}")
    if not deployment.data_generation_config:
        deployment.data_generation_config = DataGenerationConfig()
    incoming_config = deployment.data_generation_config.model_dump()
    merged_config = merge_config(incoming_config, default_deployment["data_generation_config"])
    if "save_outputs_path" in merged_config:
        merged_config["save_outputs_path"] = f"{BASE_OUTPUT_DIR}/{str(uuid.uuid4())}/{merged_config['save_outputs_path']}"
    deployment.data_generation_config = merged_config
    return deployment

def merge_config(input_config, default_config):
    """
    Deep merge configurations, with input taking precedence over defaults
    
    Args:
        input_config: User provided configuration
        default_config: Default configuration from file
    """
    if not input_config:
        return default_config
        
    if isinstance(input_config, dict) and isinstance(default_config, dict):
        result = default_config.copy()
        for key, input_value in input_config.items():
            if input_value is not None:
                if isinstance(input_value, (dict, list)):
                    result[key] = merge_config(input_value, result.get(key, {}))
                else:
                    result[key] = input_value
        return result
    return input_config if input_config is not None else default_config

async def load_and_validate_input_schema(module_run: Union[AgentRun, OrchestratorRun, EnvironmentRun, KBRun, MemoryRun, ToolRun]) -> Union[AgentRun, OrchestratorRun, EnvironmentRun, KBRun, MemoryRun, ToolRun]:
    module_name = module_run.deployment.module['name']
    module_name = module_name.replace("-", "_")
    
    # Get python path from module's venv
    modules_source_dir = Path(MODULES_SOURCE_DIR) / module_name
    venv_dir = modules_source_dir / ".venv"
    python_path = venv_dir / "bin" / "python"

    # Run validation in module's venv
    validation_code = f"""
import json
from {module_name}.schemas import InputSchema
inputs = json.loads('{json.dumps(module_run.inputs)}')
validated = InputSchema(**inputs).model_dump()
print(json.dumps(validated))
"""
    
    try:
        result = subprocess.run(
            [str(python_path), "-c", validation_code],
            capture_output=True,
            text=True,
            check=True
        )
        validated_inputs = json.loads(result.stdout.strip())
        module_run.inputs = validated_inputs
        return module_run
    except subprocess.CalledProcessError as e:
        logger.error(f"Error validating inputs: {e.stderr}")
        raise RuntimeError(f"Failed to validate inputs: {e.stderr}")

def load_and_validate_config_schema(deployment: Union[AgentDeployment, ToolDeployment, EnvironmentDeployment, KBDeployment, MemoryDeployment]):
    if "config_schema" in deployment.config and deployment.config["config_schema"] is not None:
        config_schema = deployment.config["config_schema"]
        module_name = deployment.module["name"].replace("-", "_")
        schemas_module = importlib.import_module(f"{module_name}.schemas")
        ConfigSchema = getattr(schemas_module, config_schema)
        deployment.config = ConfigSchema(**deployment.config)
    return deployment

def load_llm_configs(llm_configs_path):
    logger.info(f"Loading LLM configs from {llm_configs_path}")
    with open(llm_configs_path, "r") as file:
        llm_configs = json.loads(file.read())
    return [LLMConfig(**config) for config in llm_configs]

async def load_module_metadata(module_type: str, deployment: Union[AgentDeployment, ToolDeployment, EnvironmentDeployment, KBDeployment, MemoryDeployment, OrchestratorDeployment]):
    logger.info(f"Loading module metadata for deployment {deployment}")
    module_name = deployment.module["name"]

    logger.info(f"Loading module metadata for {module_name}")
    module_data = await list_modules(module_type, module_name)
    deployment.module = module_data

    if not module_data:
        raise ValueError(f"Module {module_name} not found")

    return module_data

async def load_node_metadata(deployment):
    # Node metadata is always loaded from input parameters
    logger.info(f"Loading node metadata for {deployment.node.ip}")
    assert deployment.node is not None, "Node is not set"
    if deployment.node.ip == "localhost" or deployment.node.ip == NODE_IP:
        node_data = get_node_config()
    else:
        node_data = await list_nodes(deployment.node.ip)
    deployment.node = node_data
    logger.info(f"Node metadata loaded")
    logger.debug(f"Node metadata: {deployment.node}")

async def load_module_config_data(deployment: Union[AgentDeployment, ToolDeployment, EnvironmentDeployment, KBDeployment, MemoryDeployment, OrchestratorDeployment], default_deployment: Dict):
    logger.info(f"Loading module config data for {deployment.module.name}")
    module_name = deployment.module.name
    module_type = deployment.module.id.split(":")[0]
    module_path = Path(f"{MODULES_SOURCE_DIR}/{module_name}/{module_name}")
 
    # Start with default config as base
    merged_config = default_deployment["config"].copy()
    
    # If deployment has config, merge with defaults
    if deployment.config:
        deployment_config = deployment.config.model_dump()
        merged_config = merge_config(deployment_config, merged_config)

    # handle llm_config
    if "llm_config" in merged_config and merged_config["llm_config"] is not None:
        # load llm_config from llm_configs.json
        config_path = f"{module_path}/configs/llm_configs.json"
        llm_configs = load_llm_configs(config_path)
        base_llm_config = next(config for config in llm_configs if config.config_name == merged_config["llm_config"]["config_name"])
        if isinstance(base_llm_config, BaseModel):
            default_llm_config = base_llm_config.model_dump()
        else:
            default_llm_config = base_llm_config
        merged_config["llm_config"] = merge_config(merged_config["llm_config"], default_llm_config)

    # update deployment with merged config
    deployment.config = merged_config
    logger.debug(f"Module config data loaded {deployment.config}")

    if 'persona_module' in merged_config and merged_config['persona_module'] is not None:
        persona_module = merged_config['persona_module']
        persona_module = await list_modules("persona", persona_module['name'])
        persona_dir = await download_persona(persona_module)
        merged_config["system_prompt"]["persona"] = load_persona(persona_dir, persona_module)

    # update deployment with merged config
    deployment.config = merged_config
    logger.info(f"Module config data loaded {deployment.config}")

async def load_subdeployments(deployment, main_deployment_default):
    logger.info(f"Loading subdeployments for {main_deployment_default['module']['name']}")
    logger.debug(f"Main deployment default: {main_deployment_default}")

    module_path = Path(f"{MODULES_SOURCE_DIR}/{main_deployment_default['module']['name']}/{main_deployment_default['module']['name']}")

    if hasattr(deployment, "agent_deployments") and deployment.agent_deployments:
        # Update defaults with non-None values from input
        agent_deployments = []
        for i, agent_deployment in enumerate(deployment.agent_deployments):
            deployment_name = main_deployment_default["agent_deployments"][i]["name"]
            agent_deployment = await setup_module_deployment("agent", module_path / "configs/agent_deployments.json", deployment_name, deployment.agent_deployments[i])
            agent_deployments.append(agent_deployment)
        deployment.agent_deployments = agent_deployments
    if hasattr(deployment, "tool_deployments") and deployment.tool_deployments:
        tool_deployments = []
        for i, tool_deployment in enumerate(deployment.tool_deployments):
            deployment_name = main_deployment_default["tool_deployments"][i]["name"]
            tool_deployment = await setup_module_deployment("tool", module_path / "configs/tool_deployments.json", deployment_name, deployment.tool_deployments[i])
            tool_deployments.append(tool_deployment)
        deployment.tool_deployments = tool_deployments
    if hasattr(deployment, "environment_deployments") and deployment.environment_deployments:
        environment_deployments = []
        for i, environment_deployment in enumerate(deployment.environment_deployments):
            deployment_name = main_deployment_default["environment_deployments"][i]["name"]
            environment_deployment = await setup_module_deployment("environment", module_path / "configs/environment_deployments.json", deployment_name, deployment.environment_deployments[i])
            environment_deployments.append(environment_deployment)
        deployment.environment_deployments = environment_deployments
    if hasattr(deployment, "kb_deployments") and deployment.kb_deployments:
        kb_deployments = []
        for i, kb_deployment in enumerate(deployment.kb_deployments):
            deployment_name = main_deployment_default["kb_deployments"][i]["name"]
            kb_deployment = await setup_module_deployment("kb", module_path / "configs/kb_deployments.json", deployment_name, deployment.kb_deployments[i])
            kb_deployments.append(kb_deployment)
        deployment.kb_deployments = kb_deployments
    logger.debug(f"Subdeployments loaded {deployment}")
    if hasattr(deployment, "memory_deployments") and deployment.memory_deployments:
        memory_deployments = []
        for i, memory_deployment in enumerate(deployment.memory_deployments):
            deployment_name = main_deployment_default["memory_deployments"][i]["name"]
            memory_deployment = await setup_module_deployment("memory", module_path / "configs/memory_deployments.json", deployment_name, deployment.memory_deployments[i])
            memory_deployments.append(memory_deployment)
        deployment.memory_deployments = memory_deployments
    logger.debug(f"Subdeployments loaded {deployment}")
    return deployment

async def setup_module_deployment(module_type: str, main_deployment_default_path: str, deployment_name: str, deployment: Union[AgentDeployment, ToolDeployment, EnvironmentDeployment, KBDeployment, OrchestratorDeployment]):
    logger.info(f"Setting up module deployment for {deployment_name}")
    logger.debug(f"Deployment: {deployment}")

    # Map deployment types to their corresponding classes
    deployment_map = {
        "agent": AgentDeployment,
        "tool": ToolDeployment,
        "environment": EnvironmentDeployment,
        "kb": KBDeployment,
        "memory": MemoryDeployment,
        "orchestrator": OrchestratorDeployment
    }

    if deployment.module:
        # Install module from input parameters
        deployment.module = await load_module_metadata(module_type, deployment)
        await install_module_with_lock(deployment.module)

    # Load default deployment config from module
    with open(main_deployment_default_path, "r") as file:
        main_deployment_default = json.loads(file.read())

    if deployment_name is None:
        default_deployment = main_deployment_default[0]
    else:
        # Get the first deployment with matching name
        default_deployment = next((d for d in main_deployment_default if d["name"] == deployment_name), None)
        if default_deployment is None:
            # raise ValueError(f"No default deployment found with name {deployment_name}")
            default_deployment = main_deployment_default[0]

    if not deployment.module:
        # Install module from default deployment
        deployment.module = await load_module_metadata(module_type, deployment_map[module_type](**default_deployment))
        await install_module_with_lock(deployment.module)
    
    if 'data_generation_config' in deployment_map[module_type].__fields__:
        if "data_generation_config" not in default_deployment:
            default_deployment["data_generation_config"] = DataGenerationConfig().model_dump()
        if "data_generation_config" in default_deployment and default_deployment["data_generation_config"] is None:
            default_deployment["data_generation_config"] = DataGenerationConfig().model_dump()
        if hasattr(deployment, "data_generation_config") or "data_generation_config" in default_deployment:
            await load_data_generation_config(deployment, default_deployment)

    # Fill in metadata and config data
    await load_node_metadata(deployment)
    await load_module_config_data(deployment, default_deployment)
    deployment = await load_subdeployments(deployment, default_deployment)

    # Override default deployment with input values
    for key, value in deployment.__dict__.items():    
        if value is not None:
            default_deployment[key] = value

    deployment.initialized = True

    return deployment_map[module_type](**default_deployment)

async def load_module(module_run):

    module_name = module_run.deployment.module['name']

    module_run = await load_and_validate_input_schema(module_run)
    
    module_run.deployment = load_and_validate_config_schema(module_run.deployment)

    # Load the module function
    module_name = module_name.replace("-", "_")
    entrypoint = module_run.deployment.module["module_entrypoint"].split(".")[0]
    main_module = importlib.import_module(f"{module_name}.run")
    main_module = importlib.reload(main_module)
    module_func = getattr(main_module, entrypoint)
    
    return module_func, module_run


from dotenv import load_dotenv
import logging
import logging.config
import os
from pathlib import Path
import platform
import psutil
import requests
import subprocess
from typing import List
from node.schemas import NodeConfigInput, NodeConfig, NodeServer

_logging_initialized = False
logger = logging.getLogger(__name__)
load_dotenv()
NUM_NODE_COMMUNICATION_SERVERS = int(os.getenv("NUM_NODE_COMMUNICATION_SERVERS"))
NODE_COMMUNICATION_PORT = int(os.getenv("NODE_COMMUNICATION_PORT"))
MODELS = os.getenv("VLLM_MODELS").split(",") if os.getenv("LLM_BACKEND") == "vllm" else os.getenv("OLLAMA_MODELS").split(",")
# in future we will make it optional for nodes to provide certain services 
# such as inference, storage and deployment of agents and other modules 
# provider types will be used to display which services are available on a node
PROVIDER_TYPES=["models", "storage", "modules"]
VRAM = 0 

def setup_logging(logging_level=logging.INFO):
    """Setup logging configuration"""
    global _logging_initialized
    if _logging_initialized:
        return

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": log_format,
                "datefmt": date_format,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "level": "DEBUG",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "": {  # root logger
                "handlers": ["console"],
                "level": logging_level,
                "propagate": True,
            }
        },
    }

    logging.config.dictConfig(logging_config)
    _logging_initialized = True


def get_logger(name):
    if not _logging_initialized:
        setup_logging()
    return logging.getLogger(name)


def node_to_url(node_schema: NodeConfigInput):
    if node_schema.user_communication_protocol == 'grpc':
        return f"{node_schema.ip}:{node_schema.user_communication_port}"
    else:
        return f"{node_schema.user_communication_protocol}://{node_schema.ip}:{node_schema.user_communication_port}"

def get_external_ip():
    """Get the external IP address of the node. If the IP address is not found, raise an error."""
    try:
        response = requests.get("https://api.ipify.org", timeout=15)
        return response.text
    except requests.RequestException as e:
        raise f"""Error retrieving IP: {e}\n\nPlease pass the IP address manually in the .env file"""


def create_output_dir(base_output_dir):
    """Create the output directory for the node."""
    if base_output_dir is None:
        raise Exception("base_output_dir not found in environment")

    try:
        if not os.path.isabs(base_output_dir):
            file_path = Path(__file__).resolve()
            parent_dir = file_path.parent
            base_output_dir = base_output_dir.replace(".", "")
            base_output_dir = f"{parent_dir}/{base_output_dir}"
            logging.info(f"base_output_dir: {base_output_dir}")

        if not Path(base_output_dir).exists():
            Path(base_output_dir).mkdir(parents=True, exist_ok=True)

        return base_output_dir

    except Exception as e:
        raise Exception(f"Error creating base_output_dir: {e}")


def run_subprocess(cmd: List) -> str:
    """Run a subprocess"""
    logger.debug(f"Running subprocess: {cmd}")
    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )
        out, err = process.communicate()

        # Log the output
        if out:
            logger.debug(f"Subprocess output: {out}")

        # Check if there's any stderr output
        if err:
            # Check if it's a pip warning about running as root
            if "WARNING: Running pip as the 'root' user" in err:
                logger.warning(f"Pip warning: {err}")
            else:
                logger.error(f"Subprocess error: {err}")
                raise Exception(err)

        return out

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise


def add_credentials_to_env(username, password):
    env_file_path = os.path.join(os.getcwd(), ".env")
    updated_lines = []
    hub_user_found = False
    hub_pass_found = False

    # Read the existing .env file
    with open(env_file_path, "r") as env_file:
        for line in env_file:
            if line.startswith("HUB_USERNAME="):
                updated_lines.append(f"HUB_USERNAME={username}\n")
                hub_user_found = True
            elif line.startswith("HUB_PASSWORD="):
                updated_lines.append(f"HUB_PASSWORD={password}\n")
                hub_pass_found = True
            else:
                updated_lines.append(line)

    # Append new credentials if not found
    if not hub_user_found:
        updated_lines.append(f"HUB_USERNAME={username}\n")
    if not hub_pass_found:
        updated_lines.append(f"HUB_PASSWORD={password}\n")

    # Write the updated content back to the .env file
    with open(env_file_path, "w") as env_file:
        env_file.writelines(updated_lines)

    logger.info(
        "Your credentials have been updated in the .env file. You can now use these credentials to authenticate in future sessions."
    )


class AsyncMixin:
    def __init__(self, *args, **kwargs):
        """
        Standard constructor used for arguments pass
        Do not override. Use __ainit__ instead
        """
        self.__storedargs = args, kwargs
        self.async_initialized = False

    async def __ainit__(self, *args, **kwargs):
        """Async constructor, you should implement this"""

    async def __initobj(self):
        """Crutch used for __await__ after spawning"""
        assert not self.async_initialized
        self.async_initialized = True
        # pass the parameters to __ainit__ that passed to __init__
        await self.__ainit__(*self.__storedargs[0], **self.__storedargs[1])
        return self

    def __await__(self):
        return self.__initobj().__await__()

def get_node_config():
    """Get the node configuration."""
    from node.user import get_public_key_from_pem
    public_key = get_public_key_from_pem(os.getenv("PRIVATE_KEY"))
    node_config = NodeConfig(
        id=f"node:{public_key}",
        owner=os.getenv("HUB_USERNAME"),
        public_key=public_key,
        ip=os.getenv("NODE_IP"),
        user_communication_protocol=os.getenv("USER_COMMUNICATION_PROTOCOL"),
        user_communication_port=os.getenv("USER_COMMUNICATION_PORT"),
        node_communication_protocol=os.getenv("NODE_COMMUNICATION_PROTOCOL"),
        num_node_communication_servers=os.getenv("NUM_NODE_COMMUNICATION_SERVERS"),
        provider_types=PROVIDER_TYPES,
        servers=[NodeServer(communication_protocol=os.getenv("NODE_COMMUNICATION_PROTOCOL"), port=NODE_COMMUNICATION_PORT+i, node_id=f"node:{public_key}") for i in range(NUM_NODE_COMMUNICATION_SERVERS)],
        models=MODELS,
        docker_jobs=os.getenv("DOCKER_JOBS"),
        routing_type=os.getenv("ROUTING_TYPE"),
        routing_url=os.getenv("ROUTING_URL"),
        ports=[NODE_COMMUNICATION_PORT+i for i in range(NUM_NODE_COMMUNICATION_SERVERS)],
        num_gpus=int(os.getenv("NUM_GPUS")),
        arch=platform.machine(),
        os=platform.system(),
        ram=psutil.virtual_memory().total,
        vram=VRAM,
    )
    logger.debug("Created node config:", node_config)
    return node_config
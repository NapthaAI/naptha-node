import os
from dotenv import load_dotenv
import asyncio
import time
from typing import Dict, Optional
from datetime import datetime
import pytz
import docker
from docker.types import DeviceRequest
from docker.models.containers import Container
from docker.errors import ContainerError, ImageNotFound, APIError
from node.schemas import DockerParams, AgentRun
from node.utils import get_logger
from node.worker.main import app
from node.worker.utils import (
    handle_ipfs_input,
    update_db_with_status_sync,
    upload_to_ipfs,
)
import traceback

logger = get_logger(__name__)

load_dotenv()
BASE_OUTPUT_DIR = os.getenv("BASE_OUTPUT_DIR")

def prepare_volume_directory(
    base_dir: str,
    bind_path: str,
    mode: str,
    agent_run_id: Optional[str] = None,
    input_dir: Optional[str] = None,
    input_ipfs_hash: Optional[str] = None,
) -> Dict:
    """Prepare a volume directory"""
    if input_dir and input_ipfs_hash:
        raise ValueError("Only one of input_dir and input_ipfs_hash can be set")
    if input_dir:
        local_path = f"{base_dir}/{input_dir}"
        if not os.path.exists(local_path):
            raise ValueError(f"Input directory {input_dir} does not exist")
        return {local_path: {"bind": bind_path, "mode": mode}}
    elif input_ipfs_hash:
        local_path = handle_ipfs_input(input_ipfs_hash)
        return {local_path: {"bind": bind_path, "mode": mode}}
    elif agent_run_id:
        local_path = f"{base_dir}/{agent_run_id}"
        if not os.path.exists(local_path):
            os.makedirs(local_path)
        return {local_path: {"bind": bind_path, "mode": mode}}
    else:
        return {}


def monitor_container_logs(
    container: Container, agent_run: Dict, save_location: Optional[str] = None
) -> str:
    """Monitor container logs"""
    output = ""
    for line in container.logs(stream=True, follow=True):
        output += line.strip().decode("utf-8") + "\n"
        agent_run.status = "running"
        asyncio.run(update_db_with_status_sync(module_run=agent_run))

    if save_location == "node":
        out_msg = {"output": str(output), "node_storage_path": agent_run.id}
    elif save_location == "ipfs":
        out_msg = upload_to_ipfs(f"{BASE_OUTPUT_DIR}/{agent_run.id.split(':')[1]}")
        out_msg = {"output": str(output), "output_ipfs_hash": out_msg}
    else:
        out_msg = {
            "output": str(output),
        }

    agent_run.status = "completed"
    agent_run.results = [out_msg["output"]]
    agent_run.error = False
    agent_run.error_message = ""
    agent_run.completed_time = datetime.now(pytz.utc).isoformat()
    asyncio.run(update_db_with_status_sync(module_run=agent_run))
    time.sleep(5)

    return output


def cleanup_container(container: Container) -> None:
    """Cleanup a container"""
    logger.debug(f"Removing container: {container}")
    if container:
        container.stop()
        container.remove()


def run_container_agent(agent_run: AgentRun = None, **kwargs) -> None:
    if agent_run.inputs.save_location:
        if agent_run.inputs.save_location not in ["node", "ipfs"]:
            raise ValueError("save_location must be either 'node' or 'ipfs'")

    volumes = {}
    if (
        agent_run.inputs.input_dir
        or agent_run.inputs.input_ipfs_hash
    ):
        logger.debug("Preparing input directory")
        inp_vol = prepare_volume_directory(
            base_dir=BASE_OUTPUT_DIR,
            bind_path=agent_run.inputs.bind_input_dir,
            mode="ro",
            input_dir=agent_run.inputs.input_dir,
            input_ipfs_hash=agent_run.inputs.input_ipfs_hash,
        )
        volumes.update(inp_vol)

    if agent_run.inputs.docker_output_dir:
        logger.info("Preparing output directory")
        out_vol = prepare_volume_directory(
            base_dir=BASE_OUTPUT_DIR,
            agent_run=agent_run.id.split(":")[1],
            bind_path=agent_run.inputs.docker_output_dir,
            mode="rw",
        )
        volumes.update(out_vol)

    client = docker.from_env()

    # if kwargs does not exist, create it
    if not kwargs:
        kwargs = {}

    try:
        # GPU allocation
        if agent_run.inputs.docker_num_gpus != 0:
            gpu_request = DeviceRequest(
                count=agent_run.inputs.docker_num_gpus, capabilities=[["gpu"]]
            )
            kwargs["device_requests"] = [gpu_request]

        # Environment variables
        if agent_run.inputs.docker_env_vars:
            kwargs["environment"] = agent_run.inputs.docker_env_vars

        # Volumes
        if volumes:
            kwargs["volumes"] = volumes

        logger.debug(f"Running container with kwargs: {kwargs}")

        container = client.containers.run(
            image=agent_run.inputs.docker_image,
            command=agent_run.inputs.docker_command,
            detach=True,
            **kwargs,
        )

        monitor_container_logs(
            container, agent_run, save_location=agent_run.inputs.save_location
        )

        # Update the agent_run status to completed
        logger.info(f"Container finished running: {container}")
        logger.info(f"Container agent run completed: {agent_run}")

    except (ContainerError, ImageNotFound, APIError) as e:
        logger.error(f"An error occurred: {str(e)}")
        error_details = traceback.format_exc()
        logger.error(f"Full traceback: {error_details}")

        agent_run.status = "error"
        agent_run.results = {
            "output": str(
                container.logs(stdout=True, stderr=False).decode().strip()
                if container
                else ""
            )
        }
        agent_run.error = True
        agent_run.error_message = str(e) + error_details
        agent_run.completed_time = datetime.now(pytz.utc).isoformat()

        asyncio.run(
            update_db_with_status_sync(
                module_run=agent_run,
            )
        )

    except Exception as e:
        logger.error(f"An unexpected error occurred: {str(e)}")
        error_details = traceback.format_exc()
        logger.error(f"Full traceback: {error_details}")

        agent_run.status = "error"
        agent_run.results = {
            "output": str(
                container.logs(stdout=True, stderr=False).decode().strip()
                if container
                else ""
            )
        }
        agent_run.error = True
        agent_run.error_message = str(e) + error_details
        agent_run.completed_time = datetime.now(pytz.utc).isoformat()

        # Update the agent run status to error
        asyncio.run(
            update_db_with_status_sync(
                module_run=agent_run,
            )
        )

    finally:
        logger.info(f"Celery task done for agent run: {agent_run}")
        logger.info(f"Done. Removing container: {container}")
        if container:
            cleanup_container(container)


# Function to execute a docker agent
@app.task(bind=True, acks_late=True)
def execute_docker_agent(self, agent_run: Dict) -> None:
    try:
        agent_run = AgentRun(**agent_run)
        docker_params = DockerParams(**agent_run.inputs)
        agent_run.inputs = docker_params
        logger.info(f"Executing docker agent run: {agent_run}")

        agent_run.status = "processing"
        agent_run.start_processing_time = datetime.now(pytz.utc).isoformat()

        # Update the agent run status to processing
        asyncio.run(
            update_db_with_status_sync(
                module_run=agent_run,
            )
        )
        try:
            run_container_agent(
                agent_run=agent_run,
            )

        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")
            error_details = traceback.format_exc()
            logger.error(f"Full traceback: {error_details}")
    finally:
        # Force cleanup of channels
        app.backend.cleanup()
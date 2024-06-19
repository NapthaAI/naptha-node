import asyncio
from datetime import datetime
from dotenv import load_dotenv
import importlib
import inspect
import json
import os
import pytz
import time
import requests
import traceback
from typing import Dict
from node.worker.main import app
from node.worker.utils import (
    load_yaml_config, 
    MODULES_PATH, 
    BASE_OUTPUT_DIR,
    prepare_input_dir, 
    update_db_with_status_sync, 
    upload_to_ipfs, 
    handle_ipfs_input
)
from naptha_sdk.client.node import Node
from naptha_sdk.schemas import ModuleRun
from node.utils import get_logger

logger = get_logger(__name__)

# Load environment variables
load_dotenv(".env")

@app.task
def run_flow(flow_run: Dict) -> None:
    flow_run = ModuleRun(**flow_run)
    loop = asyncio.get_event_loop()
    workflow_engine = FlowEngine(flow_run)
    try:
        loop.run_until_complete(workflow_engine.init_run())
        loop.run_until_complete(workflow_engine.start_run())
        while True:
            if workflow_engine.flow_run.status == "error":
                loop.run_until_complete(workflow_engine.fail())
                break
            else:
                loop.run_until_complete(workflow_engine.complete())
                break
            time.sleep(3)
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        loop.run_until_complete(workflow_engine.fail())


class FlowEngine:
    def __init__(self, flow_run: ModuleRun):
        self.flow_run = flow_run
        self.flow = None
        self.flow_name = flow_run.module_name
        self.parameters = flow_run.module_params
        self.node_type = os.getenv("NODE_TYPE")
        if self.node_type == "direct":
            self.orchestrator_node = Node(f'{os.getenv("NODE_IP")}:{os.getenv("NODE_PORT")}')
            logger.info(f"Orchestrator node: {self.orchestrator_node.node_url}")
        else:
            node_id = requests.get("http://localhost:7001/node_id").json()
            if not node_id:
                raise ValueError("NODE_ID environment variable is not set")
            self.orchestrator_node = Node(
                indirect_node_id=node_id,
                routing_url=os.getenv("NODE_ROUTING")
            )

        if flow_run.worker_nodes is not None:
            self.worker_nodes = [Node(worker_node) for worker_node in flow_run.worker_nodes]
        else:
            self.worker_nodes = None

        logger.info(f"Worker Nodes: {self.worker_nodes}")

        self.consumer = {
            "public_key": flow_run.consumer_id.split(':')[1],
            'id': flow_run.consumer_id,
        }

    async def init_run(self):
        logger.info(f"Initializing flow run: {self.flow_run}")
        self.flow_run.status = "processing"
        self.flow_run.start_processing_time = datetime.now(pytz.utc).isoformat()
        await update_db_with_status_sync(module_run=self.flow_run)

        if "input_dir" in self.parameters or "input_ipfs_hash" in self.parameters:
            self.parameters = prepare_input_dir(
                parameters=self.parameters,
                input_dir=self.parameters.get("input_dir", None),
                input_ipfs_hash=self.parameters.get("input_ipfs_hash", None)
            )

        self.flow_func, self.validated_data, self.cfg = await self.load_flow()

    async def handle_ipfs_output(self, cfg, results):
        """
        Handles the outputs of the flow
        """
        save_location = self.parameters.get("save_location", None)
        if save_location:
            self.cfg["outputs"]["location"] = save_location

        if self.cfg["outputs"]["save"]:
            if self.cfg["outputs"]["location"] == "ipfs":
                out_msg = upload_to_ipfs(self.parameters["output_path"])
                out_msg = f"IPFS Hash: {out_msg}"
                logger.info(f"Output uploaded to IPFS: {out_msg}")
                self.flow_run.results = [out_msg]

    async def start_run(self):
        logger.info(f"Starting flow run: {self.flow_run}")
        self.flow_run.status = "running"
        await update_db_with_status_sync(module_run=self.flow_run)

        if inspect.iscoroutinefunction(self.flow_func):
            response = await self.flow_func(
                inputs=self.validated_data, 
                worker_nodes=self.worker_nodes,
                orchestrator_node=self.orchestrator_node, 
                flow_run=self.flow_run, 
                cfg=self.cfg
            )
        else:
            response = self.flow_func(
                inputs=self.validated_data, 
                worker_nodes=self.worker_nodes,
                orchestrator_node=self.orchestrator_node, 
                flow_run=self.flow_run, 
                cfg=self.cfg
            )
        logger.info(f"Flow run response: {response}")

        if isinstance(response, dict):
            response = json.dumps(response)

        self.flow_run.results = [response]
        await self.handle_ipfs_output(self.cfg, response)

    async def complete(self):
        self.flow_run.status = "completed"
        self.flow_run.error = False
        self.flow_run.error_message = ""
        self.flow_run.completed_time = datetime.now(pytz.timezone("UTC")).isoformat()
        self.flow_run.duration = (datetime.fromisoformat(self.flow_run.completed_time) - datetime.fromisoformat(self.flow_run.start_processing_time)).total_seconds()
        await update_db_with_status_sync(module_run=self.flow_run)
        logger.info(f"Flow run completed: {self.flow_run}")

    async def fail(self):
        logger.error(f"Error running template flow_run")
        error_details = traceback.format_exc()
        logger.error(f"Full traceback: {error_details}")
        self.flow_run.status = "error"
        self.flow_run.error = True
        self.flow_run.error_message = error_details
        self.flow_run.completed_time = datetime.now(pytz.timezone("UTC")).isoformat()
        self.flow_run.duration = (datetime.fromisoformat(self.flow_run.completed_time) - datetime.fromisoformat(self.flow_run.start_processing_time)).total_seconds()
        await update_db_with_status_sync(module_run=self.flow_run)

    def load_and_validate_input_schema(self):
        tn = self.flow_name.replace("-", "_")
        schemas_module = importlib.import_module(f"{tn}.schemas")
        InputSchema = getattr(schemas_module, "InputSchema")
        return InputSchema(**self.parameters)

    async def load_flow(self):
        """
        Loads the flow from the module and returns the workflow
        """
        # Load the flow from the module
        workflow_path = f"{MODULES_PATH}/{self.flow_name}"

        # Load the component.yaml file
        cfg = load_yaml_config(f"{workflow_path}/{self.flow_name}/component.yaml")
        
        # If the output is set to save, save the output to the outputs folder
        if cfg["outputs"]["save"]:
            output_path = f"{BASE_OUTPUT_DIR}/{self.flow_run.id.split(':')[1]}"
            self.parameters["output_path"] = output_path
            if not os.path.exists(output_path):
                os.makedirs(output_path)

        validated_data = self.load_and_validate_input_schema()
        tn = self.flow_name.replace("-", "_")
        entrypoint = cfg["implementation"]["package"]["entrypoint"].split(".")[0]
        main_module = importlib.import_module(f"{tn}.run")
        flow_func = getattr(main_module, entrypoint)
        return flow_func, validated_data, cfg
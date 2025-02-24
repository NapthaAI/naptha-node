# node/client.py
import asyncio
from datetime import datetime, timedelta
import httpx
from httpx import HTTPStatusError, RemoteProtocolError
import json
from node.schemas import AgentRun, AgentRunInput
import time
import traceback
from typing import Dict, Any
import uuid
import websockets
import grpc
import logging
from contextlib import asynccontextmanager
from node.server import grpc_server_pb2, grpc_server_pb2_grpc
from google.protobuf.struct_pb2 import Struct
from google.protobuf.json_format import MessageToDict
from node.server.grpc_pool_manager import get_grpc_pool_instance
from node.schemas import NodeConfigInput

from node.utils import node_to_url

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 300


class Node:
    def __init__(self, node_schema: NodeConfigInput):
        self.node_schema = node_schema
        self.node_url = node_to_url(node_schema)
        self.communication_protocol = node_schema.communication_protocol
        self.connections = {}
        self.access_token = None

    @asynccontextmanager
    async def get_stub(self):
        pool = get_grpc_pool_instance()
        channel = None
        try:
            channel = await pool.get_channel(self.node_url)
            if channel is None:
                logger.error(
                    f"Failed to acquire channel for {self.node_url}. Channel is None."
                )
                raise ValueError(f"Failed to acquire channel for {self.node_url}.")
            stub = grpc_server_pb2_grpc.GrpcServerStub(channel)
            logger.info(f"GrpcServerStub created for node_url: {self.node_url}")
            yield stub
        except Exception as e:
            logger.error(
                f"Exception occurred while getting stub for {self.node_url}: {e}"
            )
            raise
        finally:
            if channel:
                try:
                    await pool.release_channel(self.node_url, channel)
                    logger.info(
                        f"Channel released back to pool for node_url: {self.node_url}"
                    )
                except Exception as e:
                    logger.error(
                        f"Exception occurred while releasing channel for {self.node_url}: {e}"
                    )

    async def connect_ws(self, action: str):
        client_id = str(uuid.uuid4())
        full_url = f"{self.node_url}/ws/{action}/{client_id}"
        logger.info(f"Connecting to WebSocket: {full_url}")
        ws = await websockets.connect(full_url)
        self.connections[client_id] = ws
        self.current_client_id = client_id
        return client_id

    async def disconnect_ws(self, client_id: str):
        if client_id in self.connections:
            await self.connections[client_id].close()
            del self.connections[client_id]
        if self.current_client_id == client_id:
            self.current_client_id = None

    async def send_receive_ws(self, data, action: str):
        client_id = await self.connect_ws(action)

        try:
            message = json.dumps(data)
            logger.debug(f"Sending message: {message}")
            await self.connections[client_id].send(message)

            response = await self.connections[client_id].recv()
            logger.debug(f"Received response: {response}")
            return json.loads(response)
        finally:
            await self.disconnect_ws(client_id)

    async def check_health(self):
        # only works for http and ws
        if self.communication_protocol == "http" or self.communication_protocol == "ws":
            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    response = await client.get(f"{self.node_url}/health")
                    response.raise_for_status()
                    return True
            except Exception as e:
                logger.error(f"Error checking health: {e}")
                return False
        else:
            raise ValueError("Invalid server type")

    async def check_user(self, user_input):
        logger.debug("Checking user... ", user_input)
        if self.communication_protocol == "http":
            return await self.check_user_http(user_input)
        elif self.communication_protocol == "ws":
            return await self.check_user_ws(user_input)
        elif self.communication_protocol == "grpc":
            return await self.check_user_grpc(user_input)
        else:
            raise ValueError("Invalid server type")

    async def register_user(self, user_input):
        if self.communication_protocol == "http":
            result = await self.register_user_http(user_input)
        elif self.communication_protocol == "ws":
            result = await self.register_user_ws(user_input)
        elif self.communication_protocol == "grpc":
            result = await self.register_user_grpc(user_input)
        else:
            raise ValueError("Invalid server type")

        if result is None:
            raise ValueError("User registration failed: returned None")

        return result

    async def run_agent(self, agent_run_input: AgentRunInput) -> AgentRun:
        if self.communication_protocol == "http":
            result = await self.run_agent_and_poll(agent_run_input)
        elif self.communication_protocol == "ws":
            result = await self.run_agent_ws(agent_run_input)
        elif self.communication_protocol == "grpc":
            result = await self.run_agent_grpc(agent_run_input)
        else:
            raise ValueError("Invalid server type")

        if result is None:
            raise ValueError("run_agent returned None")

        return result

    async def run_agent_http(self, agent_run_input: AgentRunInput) -> Dict[str, Any]:
        """
        Run a agent on a node
        """
        logger.info("Running agent...")
        logger.debug(f"Node URL: {self.node_url}")

        endpoint = self.node_url + "/agent/run"

        if isinstance(agent_run_input, dict):
            agent_run_input = AgentRunInput(**agent_run_input)

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.access_token}",
                }
                response = await client.post(
                    endpoint, json=agent_run_input.model_dict(), headers=headers
                )
                response.raise_for_status()
            return AgentRun(**json.loads(response.text))
        except HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e}")
            raise
        except RemoteProtocolError as e:
            error_msg = f"Run agent failed to connect to the server at {self.node_url}. Please check if the server URL is correct and the server is running. Error details: {str(e)}"
            logger.error(error_msg)
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            raise

    async def run_agent_ws(self, agent_run_input: AgentRunInput) -> AgentRun:
        data = {
            "agent_name": agent_run_input.agent_name,
            "consumer_id": agent_run_input.consumer_id,
            "agent_run_params": agent_run_input.agent_run_params,
            "agent_run_type": agent_run_input.agent_run_type,
        }
        response = await self.send_receive_ws(data, "run_agent")

        if response["status"] == "success":
            logger.debug(f"Ran agent successfully: {response['data']}")
            response["data"] = response["data"]
            return AgentRun(**response["data"])
        else:
            logger.error(f"Error running agent: {response['message']}")
            raise Exception(response["message"])

    async def run_agent_and_poll(self, agent_run_input: AgentRunInput) -> AgentRun:
        assert (
            self.communication_protocol == "http"
        ), "run_agent_and_poll should only be called for HTTP server type"
        agent_run = await self.run_agent_http(agent_run_input)
        logger.info(f"Agent run started: {agent_run}")

        current_results_len = 0
        while True:
            agent_run = await self.check_agent_run_http(agent_run)
            output = (
                f"{agent_run.status} {agent_run.agent_deployment.module['module_type']} {agent_run.agent_deployment.module['name']}"
            )

            if len(agent_run.results) > current_results_len:
                logger.debug("Output: ", agent_run.results[-1])
                current_results_len += 1

            if agent_run.status == "completed":
                break
            if agent_run.status == "error":
                break

            time.sleep(3)

        if agent_run.status == "completed":
            logger.debug(agent_run.results)
        else:
            logger.error(agent_run.error_message)
        return agent_run

    async def run_agent_grpc(self, agent_run_input: AgentRunInput) -> AgentRun:
        logger.debug(f"run_agent_grpc called with input: {agent_run_input}")
        try:
            async with self.get_stub() as stub:
                # Convert agent_run_params to Struct
                agent_run_params = Struct()
                for key, value in agent_run_input.agent_run_params.items():
                    agent_run_params.fields[key].string_value = str(value)

                request = grpc_server_pb2.RunAgentRequest(
                    agent_name=agent_run_input.agent_name,
                    consumer_id=agent_run_input.consumer_id,
                    agent_run_params=agent_run_params,
                    agent_nodes=agent_run_input.agent_nodes,
                )

                timeout = 60 * 60  # 60 minutes in seconds
                start_time = datetime.now()

                async for response in stub.RunAgent(request):
                    logger.debug(f"Received response: {response}")
                    response_dict = MessageToDict(
                        response, preserving_proto_field_name=True
                    )

                    if response.status in ["completed", "error"]:
                        logger.info(
                            f"Agent run completed with status: {response.status}"
                        )
                        return AgentRun(**response_dict)

                    if (datetime.now() - start_time) > timedelta(seconds=timeout):
                        logger.error("RunAgent operation timed out after 60 minutes")
                        raise TimeoutError(
                            "RunAgent operation timed out after 60 minutes"
                        )

                logger.error("RunAgent stream ended without a final response")
                raise Exception("RunAgent stream ended without a final response")
        except grpc.RpcError as e:
            logger.error(f"RPC error occurred in run_agent_grpc: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred in run_agent_grpc: {e}")
            raise

    async def check_user_http(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        endpoint = self.node_url + "/user/check"
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                headers = {
                    "Content-Type": "application/json",
                }
                response = await client.post(endpoint, json=user_input, headers=headers)
                response.raise_for_status()
            return json.loads(response.text)
        except HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e}")
            raise
        except RemoteProtocolError as e:
            error_msg = f"Check user failed to connect to the server at {self.node_url}. Please check if the server URL is correct and the server is running. Error details: {str(e)}"
            logger.error(error_msg)
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            raise

    async def check_user_ws(self, user_input: Dict[str, str]):
        response = await self.send_receive_ws(user_input, "check_user")
        logger.debug(f"Check user response: {response}")
        return response

    async def check_user_grpc(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug(f"check_user_grpc called with user_input: {user_input}")
        try:
            async with self.get_stub() as stub:
                request = grpc_server_pb2.CheckUserRequest(
                    public_key=user_input["public_key"]
                )
                logger.debug(f"Sending CheckUser request: {request}")
                response = await stub.CheckUser(request)
                logger.debug(f"Received CheckUser response: {response}")
                return {
                    "id": response.id,
                    "public_key": response.public_key,
                    "is_registered": response.is_registered,
                }
        except grpc.RpcError as e:
            logger.error(f"RPC error occurred in check_user_grpc: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred in check_user_grpc: {e}")
            raise

    async def register_user_http(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a user on a node
        """
        endpoint = self.node_url + "/user/register"
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                headers = {
                    "Content-Type": "application/json",
                }
                response = await client.post(endpoint, json=user_input, headers=headers)
                response.raise_for_status()
            return json.loads(response.text)
        except HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e}")
            raise
        except RemoteProtocolError as e:
            error_msg = f"Register user failed to connect to the server at {self.node_url}. Please check if the server URL is correct and the server is running. Error details: {str(e)}"
            logger.error(error_msg)
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            raise

    async def register_user_ws(self, user_input: Dict[str, str]):
        response = await self.send_receive_ws(user_input, "register_user")
        logger.debug(f"Register user response: {response}")
        return response

    async def register_user_grpc(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug(f"register_user_grpc called with user_input: {user_input}")
        try:
            async with self.get_stub() as stub:
                request = grpc_server_pb2.RegisterUserRequest(
                    public_key=user_input["public_key"]
                )
                logger.debug(f"Sending RegisterUser request: {request}")
                response = await stub.RegisterUser(request)
                logger.debug(f"Received RegisterUser response: {response}")
                return {
                    "id": response.id,
                    "public_key": response.public_key,
                }
        except grpc.RpcError as e:
            logger.error(f"RPC error occurred in register_user_grpc: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred in register_user_grpc: {e}")
            raise

    async def check_agent_run_http(self, agent_run: AgentRun) -> AgentRun:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.post(
                    f"{self.node_url}/agent/check", json=agent_run.model_dict()
                )
                response.raise_for_status()
            return AgentRun(**json.loads(response.text))
        except HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")

    async def send_receive_multiple(self, data_list, action: str):
        results = []

        for data in data_list:
            client_id = await self.connect_ws(action)

            message = json.dumps(data)
            logger.debug(f"Sending message: {message}")
            await self.connections[client_id].send(message)

            response = await self.connections[client_id].recv()
            logger.debug(f"Received response: {response}")
            results.append(json.loads(response))

            await self.disconnect_ws(client_id)

        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        for client_id in list(self.connections.keys()):
            await self.disconnect_ws(client_id)


class NodeIndirect:
    def __init__(self, node_url: str, routing_url: str):
        self.node_url = node_url
        self.routing_url = routing_url
        if "ws" not in self.routing_url:
            self.routing_url = f"ws://{self.routing_url}"
        self.lock = asyncio.Lock()
        self.websocket = None

    async def get_websocket(self):
        async with self.lock:
            if self.websocket is None or self.websocket.closed:
                full_url = f"{self.routing_url}/ws"
                logger.info(f"Connecting to WebSocket: {full_url}")
                self.websocket = await websockets.connect(full_url)
            return self.websocket

    async def send_receive(self, data: Dict, action: str):
        websocket = await self.get_websocket()
        source_node = f"{self.node_url}"

        message = {
            "target_node": self.node_url,
            "source_node": source_node,
            "task": action,
            "params": data,
        }

        async with self.lock:
            message_json = json.dumps(message)
            logger.debug(f"Sending message: {message_json}")
            await websocket.send(message_json)

            response = await websocket.recv()
            logger.debug(f"Received raw response: {response}")

        if isinstance(response, str):
            response_data = json.loads(response)
            logger.debug(f"Received response: {response_data}")
        else:
            logger.error(f"Received non-string response: {response}")
            raise Exception("Received non-string response")

        return response_data["params"]

    async def run_agent(self, agent_run_input: AgentRunInput) -> AgentRun:
        data = {
            "agent_name": agent_run_input.agent_name,
            "consumer_id": agent_run_input.consumer_id,
            "agent_run_params": agent_run_input.agent_run_params,
            "agent_run_type": agent_run_input.agent_run_type,
        }
        response = await self.send_receive(data, "run_agent")

        if response["status"] == "success":
            logger.debug(f"Ran agent successfully: {response['data']}")
            return AgentRun(**response["data"])
        else:
            logger.error(f"Error running agent: {response['message']}")
            raise Exception(response["message"])

    async def check_user(self, user_input: Dict[str, str]):
        response = await self.send_receive(user_input, "check_user")
        logger.debug(f"Check user response: {response}")
        return response

    async def register_user(self, user_input: Dict[str, str]):
        response = await self.send_receive(user_input, "register_user")
        logger.debug(f"Register user response: {response}")
        return response

    async def close(self):
        if self.websocket:
            await self.websocket.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

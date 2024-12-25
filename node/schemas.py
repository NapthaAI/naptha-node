from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field

class NodeServer(BaseModel):
    server_type: str
    port: int
    node_id: str

class NodeConfig(BaseModel):
    id: str
    owner: str
    public_key: str
    ip: str = Field(default="localhost")
    server_type: str = Field(default="ws")
    http_port: int = Field(default=7001)
    num_servers: int = Field(default=1)
    servers: List[NodeServer]
    ollama_models: List[str]
    docker_jobs: bool
    routing_type: Optional[str] = Field(default="direct")
    routing_url: Optional[str] = Field(default=None)
    num_gpus: Optional[int] = Field(default=None)
    arch: Optional[str] = Field(default=None)
    os: Optional[str] = Field(default=None)
    ram: Optional[int] = Field(default=None)
    vram: Optional[int] = Field(default=None)

    class Config:
        allow_mutation = True

class NodeSchema(BaseModel):
    ip: str
    http_port: Optional[int] = None
    num_servers: Optional[int] = None
    server_type: Optional[str] = None
    servers: Optional[List[str]] = None

class LLMClientType(str, Enum):
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    ANTHROPIC = "anthropic"
    VLLM = "vllm"
    LITELLM = "litellm"
    OLLAMA = "ollama"
    STABILITY = "stability"

class LLMConfig(BaseModel):
    config_name: Optional[str] = None
    client: Optional[LLMClientType] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    api_base: Optional[str] = None

class AgentModuleType(str, Enum):
    package = "package"
    docker = "docker"

class Module(BaseModel):
    id: str
    name: str
    description: str
    author: str
    module_url: str
    module_type: Optional[AgentModuleType] = AgentModuleType.package
    module_version: Optional[str] = "0.1"
    module_entrypoint: Optional[str] = "run.py"

class AgentModule(Module):
    personas_urls: Optional[List[str]] = None

class AgentConfig(BaseModel):
    config_name: Optional[str] = None
    llm_config: Optional[LLMConfig] = None
    persona_module: Optional[Union[Dict, BaseModel]] = None
    system_prompt: Optional[Union[Dict, BaseModel]] = None

class ToolConfig(BaseModel):
    config_name: Optional[str] = None
    llm_config: Optional[LLMConfig] = None

class OrchestratorConfig(BaseModel):
    config_name: Optional[str] = "orchestrator_config"
    max_rounds: Optional[int] = 5

class EnvironmentConfig(BaseModel):
    config_name: Optional[str] = None
    environment_type: Optional[str] = None

class DataGenerationConfig(BaseModel):
    save_outputs: Optional[bool] = None
    save_outputs_location: Optional[str] = None
    save_outputs_path: Optional[str] = None
    save_inputs: Optional[bool] = None
    save_inputs_location: Optional[str] = None
    default_filename: Optional[str] = None

class ToolDeployment(BaseModel):
    node: NodeSchema
    name: Optional[str] = "tool_deployment"
    module: Optional[Union[Dict, AgentModule]] = None
    tool_config: Optional[ToolConfig] = None
    data_generation_config: Optional[DataGenerationConfig] = None

class KBDeployment(BaseModel):
    node: NodeSchema
    name: Optional[str] = "kb_deployment"
    module: Optional[Union[Dict, AgentModule]] = None
    kb_config: Optional[Dict] = None

class EnvironmentDeployment(BaseModel):
    node: NodeSchema
    name: Optional[str] = "environment_deployment"
    module: Optional[Union[Dict, AgentModule]] = None
    environment_config: Optional[Union[Dict, BaseModel]] = None

class AgentDeployment(BaseModel):
    node: NodeSchema
    name: Optional[str] = "agent_deployment"
    module: Optional[Union[Dict, AgentModule]] = None
    agent_config: Optional[AgentConfig] = None
    data_generation_config: Optional[DataGenerationConfig] = None
    tool_deployments: Optional[List[ToolDeployment]] = None
    kb_deployments: Optional[List[KBDeployment]] = None
    environment_deployments: Optional[List[EnvironmentDeployment]] = None

class OrchestratorDeployment(BaseModel):
    node: NodeSchema
    name: Optional[str] = "orchestrator_deployment"
    module: Optional[Union[Dict, AgentModule]] = None
    orchestrator_config: Optional[OrchestratorConfig] = None
    agent_deployments: Optional[List[AgentDeployment]] = None
    environment_deployments: Optional[List[EnvironmentDeployment]] = None
    kb_deployments: Optional[List[KBDeployment]] = None

class DockerParams(BaseModel):
    docker_image: str
    docker_command: Optional[str] = ""
    docker_num_gpus: Optional[int] = 0
    docker_env_vars: Optional[Dict] = None
    input_dir: Optional[str] = None
    input_ipfs_hash: Optional[str] = None
    docker_input_dir: Optional[str] = None
    docker_output_dir: Optional[str] = None
    save_location: str = "node"

    class Config:
        allow_mutation = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

    def model_dict(self):
        model_dict = self.dict()
        for key, value in model_dict.items():
            if isinstance(value, datetime):
                model_dict[key] = value.isoformat()
        return model_dict


class AgentRun(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: AgentDeployment
    orchestrator_runs: List['OrchestratorRun'] = []
    status: str = "pending"
    error: bool = False
    id: Optional[str] = None
    results: list[str] = []
    error_message: Optional[str] = None
    created_time: Optional[str] = None
    start_processing_time: Optional[str] = None
    completed_time: Optional[str] = None
    duration: Optional[float] = None
    input_schema_ipfs_hash: Optional[str] = None

    class Config:
        allow_mutation = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

    def model_dict(self):
        model_dict = self.dict()
        for key, value in model_dict.items():
            if isinstance(value, datetime):
                model_dict[key] = value.isoformat()
            elif isinstance(value, AgentModuleType):
                model_dict[key] = value.value
        for i, orchestrator_run in enumerate(model_dict['orchestrator_runs']):
            for key, value in orchestrator_run.items():
                if isinstance(value, datetime):
                    model_dict['orchestrator_runs'][i][key] = value.isoformat()
        return model_dict


class AgentRunInput(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: AgentDeployment = None
    orchestrator_runs: List['OrchestratorRun'] = []

class ToolRunInput(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: ToolDeployment
    agent_run: Optional[AgentRun] = None

class ToolRun(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: ToolDeployment
    agent_run: Optional[AgentRun] = None
    status: str = "pending"
    error: bool = False
    id: Optional[str] = None
    results: list[str] = []
    error_message: Optional[str] = None
    created_time: Optional[str] = None
    start_processing_time: Optional[str] = None
    completed_time: Optional[str] = None
    duration: Optional[float] = None

class OrchestratorRunInput(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: OrchestratorDeployment

class OrchestratorRun(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: OrchestratorDeployment
    status: str = "pending"
    error: bool = False
    id: Optional[str] = None
    results: list[str] = []
    error_message: Optional[str] = None
    created_time: Optional[str] = None
    start_processing_time: Optional[str] = None
    completed_time: Optional[str] = None
    duration: Optional[float] = None
    agent_runs: List['AgentRun'] = []
    input_schema_ipfs_hash: Optional[str] = None

class EnvironmentRunInput(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: EnvironmentDeployment
    orchestrator_runs: List['OrchestratorRun'] = []

class EnvironmentRun(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: EnvironmentDeployment
    orchestrator_runs: List['OrchestratorRun'] = []
    status: str = "pending"
    error: bool = False
    id: Optional[str] = None
    results: list[str] = []
    error_message: Optional[str] = None
    created_time: Optional[str] = None
    start_processing_time: Optional[str] = None
    completed_time: Optional[str] = None
    duration: Optional[float] = None
    input_schema_ipfs_hash: Optional[str] = None

class KBRunInput(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: KBDeployment
    orchestrator_runs: List['OrchestratorRun'] = []

class KBRun(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: KBDeployment
    orchestrator_runs: List['OrchestratorRun'] = []
    status: str = "pending"
    error: bool = False
    id: Optional[str] = None
    results: list[Optional[str]] = []   
    error_message: Optional[str] = None
    created_time: Optional[str] = None
    start_processing_time: Optional[str] = None
    completed_time: Optional[str] = None
    duration: Optional[float] = None

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop: Optional[List[str]] = None
    stream: Optional[bool] = None


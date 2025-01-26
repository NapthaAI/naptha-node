from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Union, Any
from pydantic import BaseModel, Field
from node.storage.schemas import StorageType, StorageConfig

class NodeServer(BaseModel):
    communication_protocol: str
    port: int
    node_id: str

class NodeConfig(BaseModel):
    id: str
    owner: str
    public_key: str
    ip: str = Field(default="localhost")
    user_communication_protocol: str = Field(default="http")
    node_communication_protocol: str = Field(default="ws")
    user_communication_port: int = Field(default=7001)
    num_node_communication_servers: int = Field(default=1)
    provider_types: List[str] = Field(default=["models", "storage", "modules"])
    servers: List[NodeServer]
    models: List[str]
    docker_jobs: bool
    ports: Optional[List[int]] = None
    routing_type: Optional[str] = Field(default="direct")
    routing_url: Optional[str] = Field(default=None)
    num_gpus: Optional[int] = Field(default=None)
    arch: Optional[str] = Field(default=None)
    os: Optional[str] = Field(default=None)
    ram: Optional[int] = Field(default=None)
    vram: Optional[int] = Field(default=None)

class NodeConfigInput(BaseModel):
    ip: str
    user_communication_port: Optional[int] = None
    user_communication_protocol: Optional[str] = None

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
    options: Optional[Dict] = None

class ModuleType(str, Enum):
    agent = "agent"
    tool = "tool"
    environment = "environment"
    kb = "kb"
    memory = "memory"
    orchestrator = "orchestrator"
    persona = "persona"

class ModuleExecutionType(str, Enum):
    package = "package"
    docker = "docker"

class Module(BaseModel):
    id: str
    name: str
    description: str
    author: str
    module_url: str
    module_type: Optional[ModuleType] = ModuleType.agent
    module_version: Optional[str] = "0.1"
    module_entrypoint: Optional[str] = "run.py"
    execution_type: Optional[ModuleExecutionType] = ModuleExecutionType.package

class AgentConfig(BaseModel):
    config_name: Optional[str] = None
    config_schema: Optional[str] = None
    llm_config: Optional[LLMConfig] = None
    persona_module: Optional[Union[Dict, Module]] = None
    system_prompt: Optional[Union[Dict, BaseModel]] = None

class ToolConfig(BaseModel):
    config_name: Optional[str] = None
    config_schema: Optional[str] = None
    llm_config: Optional[LLMConfig] = None

class OrchestratorConfig(BaseModel):
    config_name: Optional[str] = "orchestrator_config"
    config_schema: Optional[str] = None
    max_rounds: Optional[int] = 5

class EnvironmentConfig(BaseModel):
    config_name: Optional[str] = None
    config_schema: Optional[str] = None
    environment_type: Optional[str] = None
    storage_config: Optional[StorageConfig] = None

    def model_dict(self):
        if isinstance(self.storage_config, StorageConfig):
            self.storage_config = self.storage_config.model_dict()
        model_dict = self.dict()
        model_dict['storage_config'] = self.storage_config
        return model_dict

class KBConfig(BaseModel):
    config_name: Optional[str] = None
    storage_config: Optional[StorageConfig] = None
    llm_config: Optional[LLMConfig] = None

    def model_dict(self):
        if isinstance(self.storage_config, StorageConfig):
            self.storage_config = self.storage_config.model_dict()
        model_dict = self.dict()
        model_dict['storage_config'] = self.storage_config
        return model_dict

class MemoryConfig(BaseModel):
    config_name: Optional[str] = None
    storage_config: Optional[StorageConfig] = None

    def model_dict(self):
        if isinstance(self.storage_config, StorageConfig):
            self.storage_config = self.storage_config.model_dict()
        model_dict = self.dict()
        model_dict['storage_config'] = self.storage_config
        return model_dict

class DataGenerationConfig(BaseModel):
    save_outputs: Optional[bool] = None
    save_outputs_location: Optional[str] = None
    save_outputs_path: Optional[str] = None
    save_inputs: Optional[bool] = None
    save_inputs_location: Optional[str] = None
    default_filename: Optional[str] = None

class ToolDeployment(BaseModel):
    node: Union[NodeConfig, NodeConfigInput]
    name: Optional[str] = None
    module: Optional[Union[Dict, Module]] = None
    config: Optional[Union[ToolConfig, BaseModel]] = None
    data_generation_config: Optional[DataGenerationConfig] = None
    initialized: Optional[bool] = False

class MemoryDeployment(BaseModel):
    node: Union[NodeConfig, NodeConfigInput]
    name: Optional[str] = "memory_deployment"
    module: Optional[Union[Dict, Module]] = None
    config: Optional[Union[MemoryConfig, BaseModel]] = None
    initialized: Optional[bool] = False

class KBDeployment(BaseModel):
    node: Union[NodeConfig, NodeConfigInput]
    name: Optional[str] = None
    module: Optional[Union[Dict, Module]] = None
    config: Optional[Union[KBConfig, BaseModel]] = None
    initialized: Optional[bool] = False

class EnvironmentDeployment(BaseModel):
    node: Union[NodeConfig, NodeConfigInput]
    name: Optional[str] = None
    module: Optional[Union[Dict, Module]] = None
    config: Optional[Union[EnvironmentConfig, BaseModel]] = None
    initialized: Optional[bool] = False

class AgentDeployment(BaseModel):
    node: Union[NodeConfig, NodeConfigInput]
    name: Optional[str] = None
    module: Optional[Union[Dict, Module]] = None
    config: Optional[AgentConfig] = None
    data_generation_config: Optional[DataGenerationConfig] = None
    tool_deployments: Optional[List[ToolDeployment]] = None
    kb_deployments: Optional[List[KBDeployment]] = None
    memory_deployments: Optional[List[MemoryDeployment]] = None
    environment_deployments: Optional[List[EnvironmentDeployment]] = None
    initialized: Optional[bool] = False

class OrchestratorDeployment(BaseModel):
    node: Union[NodeConfig, NodeConfigInput]
    name: Optional[str] = None
    module: Optional[Union[Dict, Module]] = None
    config: Optional[OrchestratorConfig] = None
    agent_deployments: Optional[List[AgentDeployment]] = None
    environment_deployments: Optional[List[EnvironmentDeployment]] = None
    kb_deployments: Optional[List[KBDeployment]] = None
    memory_deployments: Optional[List[MemoryDeployment]] = None
    initialized: Optional[bool] = False

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
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        for key, value in model_dict.items():
            if isinstance(value, ModuleExecutionType):
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
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict

class ToolRunInput(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: ToolDeployment
    agent_run: Optional[AgentRun] = None
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict
    
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
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict

class OrchestratorRunInput(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: OrchestratorDeployment
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict

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
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict

class EnvironmentRunInput(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: EnvironmentDeployment
    orchestrator_runs: List['OrchestratorRun'] = []
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict

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
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict

class KBRunInput(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: KBDeployment
    orchestrator_runs: List['OrchestratorRun'] = []
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict

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
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict

class MemoryRunInput(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: MemoryDeployment
    orchestrator_runs: List['OrchestratorRun'] = []
    signature: str

    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict

class MemoryRun(BaseModel):
    consumer_id: str
    inputs: Optional[Union[Dict, BaseModel, DockerParams]] = None
    deployment: MemoryDeployment
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
    signature: str
    
    def model_dict(self):
        model_dict = self.dict()
        if isinstance(self.deployment.config, BaseModel):
            config = self.deployment.config.model_dump()
            model_dict['deployment']['config'] = config
        if isinstance(self.inputs, BaseModel):
            inputs = self.inputs.model_dump()
            model_dict['inputs'] = inputs
        return model_dict

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
    stream_options: Optional[dict] = None
    n: Optional[int] = None
    response_format: Optional[dict] = None
    seed: Optional[int] = None
    tools: Optional[List] = None
    tool_choice: Optional[str] = None
    parallel_tool_calls: Optional[bool] = None

class CompletionRequest(BaseModel):
    model: str
    prompt: str
    max_tokens: Optional[int] = 50
    temperature: Optional[float] = 0.7

class EmbeddingsRequest(BaseModel):
    model: str
    input: Union[str, List[str]]
    
class SecretInput(BaseModel):
    user_id: str
    secret_value: str
    key_name: str
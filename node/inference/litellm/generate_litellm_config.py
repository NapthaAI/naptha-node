#!/usr/bin/env python3
import logging
import os
from pathlib import Path
import sys
import subprocess
from typing import Dict, List, Optional
root_dir = Path(__file__).parent.parent.parent.parent
sys.path.append(str(root_dir))

logger = logging.getLogger(__name__)

LAUNCH_DOCKER = os.getenv("LAUNCH_DOCKER").lower() == "true"
LLM_BACKEND = os.getenv("LLM_BACKEND")
OPENAI_MODELS = os.getenv("OPENAI_MODELS")
OLLAMA_MODELS = os.getenv("OLLAMA_MODELS")
VLLM_MODELS = os.getenv("VLLM_MODELS")

MODEL_DEVICE_REQUIREMENTS = {
    "NousResearch/Hermes-3-Llama-3.1-8B": 1,
    "Qwen/Qwen2.5-7B-Instruct": 1,
    "meta-llama/Llama-3.1-8B-Instruct": 1,
    "Team-ACE/ToolACE-8B": 1,
    "ibm-granite/granite-3.1-8b-instruct": 1,
    "internlm/internlm2_5-7b-chat": 1,
    "meetkai/functionary-small-v3.1": 1,
    "jinaai/jina-embeddings-v2-base-en": 1,
    "katanemo/Arch-Function-7B": 1,
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B": 2,
    "microsoft/phi-4": 1,
    "mistralai/Mistral-Small-24B-Instruct-2501": 2,
    "Qwen/QwQ-32B-Preview": 2,
    "NousResearch/DeepHermes-3-Llama-3-8B-Preview": 1
}

if VLLM_MODELS:
    VLLM_MODELS = VLLM_MODELS.split(",")
    VLLM_MODELS = {model.strip(): MODEL_DEVICE_REQUIREMENTS[model.strip()] for model in VLLM_MODELS}

logger.info(f"LAUNCH_DOCKER: {LAUNCH_DOCKER}")
logger.info(f"LLM_BACKEND: {LLM_BACKEND}")
logger.info(f"OPENAI_MODELS: {OPENAI_MODELS}")
logger.info(f"OLLAMA_MODELS: {OLLAMA_MODELS}")
logger.info(f"VLLM_MODELS: {VLLM_MODELS}")

def format_yaml_value(value: any) -> str:
    """Format a value for YAML output."""
    if isinstance(value, str):
        if any(c in value for c in ":{}\n[]'\""):
            return "'{}'".format(value.replace("'", "''"))
        return value
    if isinstance(value, (bool, int, float)):
        return str(value).lower()
    return str(value)

def dict_to_yaml(data: Dict, indent: int = 0) -> str:
    """Convert a dictionary to YAML string."""
    yaml_str = []
    spaces = " " * indent
    
    for key, value in data.items():
        if isinstance(value, dict):
            yaml_str.append(f"{spaces}{key}:")
            yaml_str.append(dict_to_yaml(value, indent + 2))
        elif isinstance(value, list):
            yaml_str.append(f"{spaces}{key}:")
            for item in value:
                if isinstance(item, dict):
                    # Start dictionary items in a list with "- key:" format
                    first_key = next(iter(item))
                    yaml_str.append(f"{spaces}- {first_key}: {format_yaml_value(item[first_key])}")
                    # Handle remaining key-value pairs with increased indentation
                    remaining = {k: v for k, v in item.items() if k != first_key}
                    if remaining:
                        yaml_str.append(dict_to_yaml(remaining, indent + 2))
                else:
                    yaml_str.append(f"{spaces}- {format_yaml_value(item)}")
        else:
            yaml_str.append(f"{spaces}{key}: {format_yaml_value(value)}")
    
    return "\n".join(yaml_str)

def validate_openai_key() -> Optional[str]:
    """Validate OpenAI API key from environment."""
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logger.error("No OPENAI_API_KEY found in environment")
        return None
    
    if len(api_key) < 10:
        logger.error("OPENAI_API_KEY seems invalid (length < 10)")
        return None
        
    return api_key

def get_openai_models() -> List[str]:
    """Get OpenAI models from config."""
    if not OPENAI_MODELS:
        return []
    return [model.strip() for model in OPENAI_MODELS.split(',') if model.strip()]

def get_ollama_models() -> List[str]:
    """Get Ollama models from config."""
    if not OLLAMA_MODELS:
        return []
     # NOTE requires that we
    return [model.strip() for model in OLLAMA_MODELS.split(',') if model.strip()]

def generate_litellm_config() -> Dict:
    """Generate LiteLLM configuration."""
    config = {
        'model_list': []
    }
    
    # Add OpenAI models if API key is valid
    if validate_openai_key():
        openai_models = get_openai_models()
        for model in openai_models:
            config['model_list'].append({
                'model_name': model,
                'litellm_params': {
                    'model': f'openai/{model}',
                    'api_key': 'os.environ/OPENAI_API_KEY'
                }
            })
    
    # Add models based on LLM_BACKEND
    if LLM_BACKEND == "ollama":
        ollama_models = get_ollama_models()
        for model in ollama_models:
            config['model_list'].append({
                'model_name': model,
                'litellm_params': {
                    'model': f'ollama/{model}',
                    'api_base': 'http://localhost:11434' if not LAUNCH_DOCKER else 'http://ollama:11434'
                }
            })

    elif LLM_BACKEND == "vllm":
        vllm_models = get_vllm_models()
        for model in vllm_models:
            service_name = model.split("/")[-1]
            if service_name:
                if "embeddings" not in service_name:
                    config['model_list'].append({
                        'model_name': model,
                        'litellm_params': {
                            'model': f'openai/{model}',
                            'api_base': f'http://{service_name}:8000/v1',
                            'api_key': 'none'
                        }
                    })
                else:
                    config['model_list'].append({
                        'model_name': model,
                        'litellm_params': {
                            'model': f'openai/{model}',
                            'api_base': f'http://{service_name}/v1',
                            'api_key': 'none'
                        }
                    })
            else:
                logger.error(f"Model {model} not found in MODEL_SERVICE_MAP")

    # add api key at the bottom of the config
    config['general_settings'] = {
        'master_key': os.getenv('LITELLM_MASTER_KEY')
    }
    
    return config

def get_vllm_models() -> List[str]:
    """Get VLLM models from config."""
    if not VLLM_MODELS:
        return []
    return list(VLLM_MODELS.keys())

def get_gpu_var_name(model_name: str) -> str:
    """Generate standardized GPU ID variable name from model name."""
    # Get the part after the last slash
    base_name = model_name.split('/')[-1]
    # Convert to lowercase and replace special chars with underscores
    normalized = base_name.lower().replace('-', '_').replace('.', '_')
    return f"GPU_ID_{normalized}"

def count_available_gpus() -> int:
    """Count available GPUs using nvidia-smi."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True
        )
        gpu_list = [gpu for gpu in result.stdout.strip().split("\n") if gpu.strip()]
        logger.info(f"Found {len(gpu_list)} GPUs")
        return len(gpu_list)
    except Exception as e:
        logger.error(f"Warning: Could not detect GPUs via nvidia-smi: {e}")
        # Fallback to a default value
        return 8
    
def allocate_gpus(model_map):
    """
    Allocate GPUs based on model requirements.
    Returns a space-separated string of GPU assignments for docker compose.
    """
    available_gpus = count_available_gpus()
    total_required = sum(model_map.values())

    if total_required > available_gpus:
        logger.error(
            f"Error: Insufficient GPUs available. The system has {available_gpus} GPUs, "
            f"but the selected models require a total of {total_required} GPUs.",
        )
        sys.exit(1)

    current_gpu = 0
    gpu_assignments = []
    for model, gpu_count in model_map.items():
        gpu_var_name = get_gpu_var_name(model)
        gpu_list = ",".join(str(i) for i in range(current_gpu, current_gpu + gpu_count))
        gpu_assignments.append(f"{gpu_var_name}={gpu_list}")
        current_gpu += gpu_count

    return " ".join(gpu_assignments)

def main():
    config = generate_litellm_config()
    
    script_dir = Path(__file__).parent
    output_path = script_dir / 'litellm_config.yml'
    
    if not config['model_list']:
        logger.warning("Warning: No models configured.")
        # write an empty config to avoid LiteLLM 'config file not found error'
        yaml_content = dict_to_yaml({'model_list': []})
        with open(output_path, 'w') as f:
            f.write(yaml_content)
        sys.exit(1)

    try:
        yaml_content = dict_to_yaml(config)
        with open(output_path, 'w') as f:
            f.write(yaml_content)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

    if LLM_BACKEND == "vllm":
        gpu_assignments = allocate_gpus(VLLM_MODELS)
        with open('gpu_assignments.txt', 'w') as f:
            f.write(gpu_assignments)

if __name__ == "__main__":
    main()
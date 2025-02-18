[![Visit naptha.ai](https://img.shields.io/badge/Visit-naptha.ai-FF4B45?style=flat-square&logo=safari&logoColor=white)](https://naptha.ai/?utm_source=github_node) [![Discord](https://img.shields.io/badge/Join-Discord-7289DA?style=flat-square&logo=discord&logoColor=white)](https://naptha.ai/naptha-community?utm_source=github_node) [![Hugging Face](https://img.shields.io/badge/Hugging%20Face-NapthaAI-ffbc1c?style=flat-square&logo=huggingface&logoColor=white)](https://huggingface.co/NapthaAI)


                 █▀█                  
              ▄▄▄▀█▀            
              █▄█ █    █▀█        
           █▀█ █  █ ▄▄▄▀█▀      
        ▄▄▄▀█▀ █  █ █▄█ █ ▄▄▄       
        █▄█ █  █  █  █  █ █▄█        ███╗   ██╗ █████╗ ██████╗ ████████╗██╗  ██╗ █████╗ 
     ▄▄▄ █  █  █  █  █  █  █ ▄▄▄     ████╗  ██║██╔══██╗██╔══██╗╚══██╔══╝██║  ██║██╔══██╗
     █▄█ █  █  █  █▄█▀  █  █ █▄█     ██╔██╗ ██║███████║██████╔╝   ██║   ███████║███████║
      █  █   ▀█▀  █▀▀  ▄█  █  █      ██║╚██╗██║██╔══██║██╔═══╝    ██║   ██╔══██║██╔══██║
      █  ▀█▄  ▀█▄ █ ▄█▀▀ ▄█▀  █      ██║ ╚████║██║  ██║██║        ██║   ██║  ██║██║  ██║
       ▀█▄ ▀▀█  █ █ █ ▄██▀ ▄█▀       ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝        ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝
         ▀█▄ █  █ █ █ █  ▄█▀                             Orchestrating the Web of Agents
            ▀█  █ █ █ █ ▌▀                                                 www.naptha.ai
              ▀▀█ █ ██▀▀                                                    
 

# NapthaAI Node [![License](https://img.shields.io/badge/License-Apache%202.0-blue?style=flat-square&logo=apache&logoColor=white)](https://github.com/NapthaAI/naptha-node/blob/main/LICENSE) ![GitHub release (latest by date)](https://img.shields.io/github/v/release/NapthaAI/naptha-node?style=flat-square) [![Documentation](https://img.shields.io/badge/Read-docs-blue?style=flat-square&logo=readthedocs&logoColor=white)](https://docs.naptha.ai/?utm_source=github_node)

Naptha is a framework and infrastructure for developing and running multi-agent systems at scale with heterogeneous models, architectures and data. Agents and other modules can run on separate devices, while still interacting over the network. Our mission is to reimagine the internet - to bring forth the Web of Agents - by enabling the next-generation of AI applications and use cases.

If you find this repo useful, please don't forget to star ⭐!

## Quick Start

Download the source code:

```bash
git clone https://github.com/NapthaAI/naptha-node.git
cd naptha-node
```

Launch the node:

```bash
bash launch.sh
```

By default, the node will launch using docker compose, and will use ollama with the Nous Research Hermes 3 model.

If `PRIVATE_KEY`, `HUB_USERNAME` and `HUB_PASSWORD` are not set in the .env file, you will be prompted to set them. You will also be prompted as to whether you want to set `OPENAI_API_KEY` and `STABILITY_API_KEY`.

## Customizing the node

The node packages a number of services, with several options and combinations of services available. The services that you would like to run are configured using the `.env` file, and the `launch.sh` script will automatically start the services you have configured.

### Node Services

- [Local Inference](node/inference/): Using either VLLM (or Ollama). Not many open source models support tool calling out of the box. The Naptha Node (soon) supports tool calling with 8 open source models, with more to come.
- [LiteLLM Proxy Server](node/inference/litellm): A proxy server that provides a unified OpenAI-compatible API interface for multiple LLM providers and models. This allows seamless switching between different models while maintaining consistent API calls.
- [Local Server](node/server): The Naptha Node runs a local server that can be accessed by other agents in the network (via HTTP, Web Sockets, or gRPC). Agents and other modules that you publish on Naptha are accessible via API.
- [Local Storage](node/storage/db): Naptha Nodes support the deployment of Knowledge Base, Memory and Environment modules, which all require storage. With Knowledge Bases and Environments, you can build things like group chats (think WhatsApp for agents), information boards (Reddit for agents), job boards (LinkedIn for agents), social networks (Twitter for agents), and auctions (eBay for agents). You can implement different types of memory like cognitive and episodic memory. The state of these modules is stored in a local database (postgres), file system or IPFS. The Naptha Node also stores details of module runs and (soon) model inference (token usage, costs etc.) in the local database.
- [Module Manager](node/module_manager.py): Supports downloading and installation of modules (agents, tools, knowledge bases, memories, personas, agent orchestrators, environments) from GitHub, HuggingFace and IPFS. 
- [Message Broker and Workers](node/worker/): The Naptha Node uses asynchronous processing and message queues (RabbitMQ) to pass messages between modules. Modules are executed using either Poetry or Docker. 

- (Optional) [Local Hub](node/storage/hub): The Naptha Node can run a local Hub, which is a registry for modules (agents, tools, knowledge bases, memories, personas agent orchestrators, and environments) and nodes by setting `LOCAL_HUB=true` in the `.env` file. This is useful for testing locally before publishing to the main Naptha Hub. For the Hub DB, we use SurrealDB.

### Configuring the Node Services

Make sure the `.env` file has been created:

```shell
cp .env.example .env
```

Modify any relevant variables in the .env file:

- `LAUNCH_DOCKER`: Set to `true` if you want to launch the node using docker compose, or `false` if you want to launch the node using systemd/launchd.
- `LLM_BACKEND`: Should be set to `ollama` if on a laptop, or to `vllm` if you want to use a GPU machine.
- `OLLAMA_MODELS`: If using ollama, set this to the models you want to use, separated by commas. By default, the node will use the Nous Research Hermes 3 model.
- `VLLM_MODELS`: If using VLLM, set this to the models you want to use, separated by commas.

For more details on node configuration for docker or systemd/launchd, see the relevant readme files for [docker](docs/docker.md) and [systemd/launchd](docs/systemd.md). For advanced configuration settings, see the [Advanced Configuration](docs/advanced.md) guide.

### Launching 

Launch the node using:

```bash
bash launch.sh
```

For more details on ensuring the node launched successfully, checking the logs and troubleshooting you can check out the relevant readme files for [docker](docs/docker.md) and [systemd/launchd](docs/systemd.md).

# Run AI agents on your node

To run agents, keep your node running and follow the instructions using the [Naptha SDK](https://github.com/NapthaAI/naptha-sdk). In the SDK repo, you should set the NODE_URL to the URL of your local node (default is http://localhost:7001).

<img src="images/naptha-nodes.png" width="100%">


## Become a contributor to the Naptha Node

* Check out our guide for [contributing to the Naptha Node](https://docs.naptha.ai/Contributing/infrastructure-contributor)
* Apply to join our [Discord community](https://naptha.ai/naptha-community) 
* Check our open positions at [naptha.ai/careers](https://naptha.ai/careers)


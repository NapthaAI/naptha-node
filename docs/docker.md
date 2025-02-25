# Managing your Naptha Node with Docker

The Naptha Node provides support for launching using docker compose. The node packages a number of services, with several options and combinations of services available e.g. running ollama or vLLM, running multiple models across multiple GPUs (from a selection of 13 open source models), running a local hub, etc. The services that you would like to run are configured using the .env file, and the `launch.sh` script will automatically start the services you have configured.

## Configuring your Naptha Node

Start by copying the provided `.env` file:

```shell
cp .env.example .env
```

Configure the following variables in the `.env` file:

- `LAUNCH_DOCKER`: Set to `true` if you want to launch the node using Docker.
- `LLM_BACKEND`: Should be set to `ollama` if not using a GPU, or to `vllm` if you want to use a GPU.
- `OLLAMA_MODELS`: If using `ollama`, set this to the models you want to use, separated by commas. By default, the node will use the Nous Research Hermes 3 model. By default, ollama models will be downloaded to `node/inference/ollama` and mounted as a bind volume in the ollama container.
- `VLLM_MODELS`: If using `vllm`, set this to the models you want to use, separated by commas.
- `HUGGINGFACE_TOKEN`: If you plan to access private/gated models (such as Llama 3.1 8B, or others by Meta and Mistral) you need to make sure to request access to this model on HuggingFace and set a HuggingFace access token in the `.env` file.
- `HF_HOME`: If you plan to serve models with vLLM, make sure to set the `HF_HOME` environment variable to the path to your HuggingFace cache directory, so the models can be mounted as volumes rather than being re-downloaded every time a container is created. Your cache directory will be mounted into vLLM containers, so that models are downloaded and cached on your disk and can be easily re-loaded and re-used. If you're not sure what to set this to, `/home/<your user>/.cache/huggingface` is the default path on linux and MacOS systems.

For advanced configuration settings, see the [Advanced Configuration](./advanced.md) guide.

## Launching the Naptha Node

You can run the node using:

```bash
bash launch.sh
```

This will automatically call `docker compose up` with the appropriate compose file based on your configuration. 

The images will be pulled from `napthaai/node:latest` on Docker hub. It will not build the image from source (see the development workflows in the [Advanced Configuration](./advanced.md) guide to build the container from source.)

## Checking the logs 

The docker compose runs in detached mode, so you can use `docker compose logs -f` to see the logs of the node. You can check the logs of individual services using:

```bash
docker logs -f <container_id>
```

where `<container_id>` is the id of the service you want to check the logs of. You can get a list of all currently-running containers and their IDs by running `docker ps`. 
Some containers in the compose configuration have human-readable `container_name` fields set, e.g. `node-app`, `litellm`, `node-ollama`, `Hermes-3-Llama-3.1-8B`, `node-pgvector`, etc. in which can you can run 

```bash 
docker logs -f <container_name>
```

### Accessing a Service's Container

To run commands inside a container using an interactive shell, e.g. to explore the filesystem, you can use:

```bash
docker exec -it <container_id> /bin/bash

# or, for some containers that don't have bash:
docker exec -it <container_id> /bin/sh
```

Then, you can run `exit` to exit the shell inside the container when you are finished. This will not stop the container, it will just exit the shell.

## Stopping the Node

To stop the node, you can use:

```bash
bash docker-ctl.sh down
```

This script is _auto-generated_ by `launch.sh` and is used to stop the node and remove the containers. It will not be present in the repository until you start the node with `launch.sh`.

Note that by default, this will _not_ remove persistant volumes created by certain containers, e.g. the postgres database and the rabbitMQ server. If you want to remove these volumes, you can run `docker volume ls` and `docker volume rm` to find, list, and remove the volume(s) that you want to remove. 




# Advanced Configuration

1. [Run a Hub DB locally](#run-a-hub-db-locally)
2. [Make your node available to other nodes on the network](#make-your-node-available-to-other-nodes-on-the-network)
3. [Customize the node communication servers](#customize-the-node-communication-servers)
4. [Running Naptha Modules in Docker containers](#running-naptha-modules-in-docker-containers)
5. [Routing to non-public IP addresses](#routing-to-non-public-ip-addresses)
6. [Running a separate LiteLLM instance](#running-a-separate-litellm-instance)
7. [Configuring RabbitMQ and PostgreSQL](#configuring-rabbitmq-and-postgresql)
8. [Building the Docker Image](#building-the-docker-image)

## Run a Hub DB locally

For development purposes, it is sometimes useful to run a local hub DB (e.g. to prevent the need for registering incomplete modules in the public Naptha Hub). To do this, set the following variable:

- `LOCAL_HUB`: Set to True if you want to run a local hub.

By default, the local hub will be available at `ws://localhost:3001/rpc` with the namespace defined by `HUB_DB_SURREAL_NS`, the database name defined by `HUB_DB_SURREAL_NAME` in the config.py file, and the root user and password defined by `HUB_DB_SURREAL_ROOT_USER` and `HUB_DB_SURREAL_ROOT_PASS` in the .env file.

If using docker, you should see the `surrealdb` service in the `docker ps -a` output. You can also check the logs of the `surrealdb` service with `docker logs -f surrealdb`.

## Make your node available to other nodes on the network

By default, the node will not register with the Naptha Hub, which means that running `naptha nodes` will not show your node. If you would like your node to be available to other nodes on the network, you can set the following variable:

- `REGISTER_NODE_WITH_HUB`: Set to True if you want to register your node with the hub.

You will also need to change `NODE_IP` from localhost to the IP address of the machine you are running the node on.

## Customize the node communication servers

By default, the node will use web sockets for communication between nodes. To use a different node communication protocol, you can set the following variable:

- `NODE_COMMUNICATION_PROTOCOL`: Set to "ws" or "grpc".

By default, the node will run a single node communication server. If you want to run more than one, you can set the following variables:

- `NUM_NODE_COMMUNICATION_SERVERS`: Set to the number of node communication servers you want to run.

A different `NODE_COMMUNICATION_PORT` will be used for each server, starting from `NODE_COMMUNICATION_PORT` and incrementing by 1.

## Running Naptha Modules in Docker containers

If you want to run Naptha Modules in Docker containers, you can set the following variable:

- `DOCKER_JOBS`: Set to True if you want to run Naptha Modules in Docker containers.

This means that modules written in different languages e.g. Python and Typescript can be used together (with communication via API).

## Routing to non-public IP addresses

If you are running a Naptha Node on a machine behind a WiFi router, the IP address of your machine will be a private IP address, and not accessible from the public internet. We have previously demonstrated routing using relay servers and this is what the `ROUTING_URL` and `ROUTING_TYPE` variables are for. However, this is not currently functional. If you are interested in this feature, please contact us at team@naptha.ai.

## Running a separate LiteLLM instance

If you are running LiteLLM externally to the node, you can specify the `LITELLM_URL` value in `node/config.py`, and add `LITELLM_MASTER_KEY` in your `.env` file so that your node is able to access your LiteLLM instance.

## Configuring RabbitMQ and PostgreSQL

The `rabbitmq` and `postgres` containers have persistent volumes that will survive the containers being shut down. Once the container has been started for the first time, the username and password values in the `.env` file cannot be changed without authentication failing, unless you run `docker compose -f <compose file name> down --volumes` to destroy the persistent volumes, and then rebuilding with `docker compose -f <compose file name> up`

Note that the `RMQ_*` variables will be passed in to create the default RMQ user, and to authenticate with RMQ. `RMQ_HOST` should be set to `rabbitmq` in this case, since that's the name of the rabbitmq service in the docker-compose files. The username and password can be whatever you want.

`scripts/init.sql` is run the first time that the postgres container is launched, but its' results and the persisted postgres data are saved in postgres's named volume. If you want to re-run the script, you need to destroy the volume once the container is stopped.

## Building the Docker Image

The Naptha node uses a platform-agnostic Dockerfile intended for use with `docker buildx`. 

This is automatically used by Naptha's CI/CD, so when you pull the image from `napthaai/node:latest`, the right architecture will be available for your device, and will be pulled automatically. However, legacy `docker build` commands are automatically supported: 

```shell
docker build -t account/repository:tag -f Dockerfile-node .
```


To build the image with `docker buildx` yourself, you must first install Docker on your system. Once you have done that, complete the following steps to enable the `buildx` plugin:


```shell 
docker buildx install # install the buildx plugin
docker buildx create --name builder --use # create a builder 
docker build use builder
```

Once you have done this, you can build the `buildx.Dockerfile` for your platform of choice.

Note that if you are specifying a _single_ target platform with `--platform`, you can use `--load` to load the image
into your local docker cache. If you are building for multiple platforms with `--platform`, you must use `--push` to 
push the manifests up to your dockerhub / other container repo, since the local docker cache
does not support manifest lists for multi-platform builds. In that case, you need to specify a full container tag of 
`account/repository:tag`

To build the image for the architecture of your machine, run:

```shell 
docker buildx build \
  -t account/repository:tag \
  -f Dockerfile-node \
  . --load 
```

Or, you can use the `--platform` flag to specify one or more specific architectures to build for.
This can be useful for example if you want to build the node on an ARM machine (e.g. a M-series Macbook) 
and then run it on a remote server with a different architecture.

```shell
# for ARM CPUs only:
docker buildx build \
  --platform linux/arm64 # you can specify one or more target 
  -t example-docker-tag \
  -f Dockerfile-node \
  . --load
  
# for multiple target platforms:
docker buildx build \
  --platform linux/arm64,linux/amd64 \
  -t account/repository:tag \
  -f Dockerfile-node \
  . --load
```

Remember that with `docker buildx`, images are not automatically added to your build cache. You can use `--load` to load the image into your local docker cache, or use `--push` to push the image to a remote container repository.
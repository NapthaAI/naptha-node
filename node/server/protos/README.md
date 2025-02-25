# Node gRPC Communication

This repository contains the gRPC protocol definition and code generation utilities for inter-agent communication in the distributed node system.

## Overview

The gRPC server defined in this codebase facilitates communication between agents in a distributed system. It provides services for user authentication, module execution, and system health checks.

## Code Generation

### Prerequisites

- Python
- gRPC tools for Python (`grpc_tools`)

### Generating Python Code

To generate the Python code from the proto file, run:

```bash
python -m grpc_tools.protoc -I./protos --python_out=. --grpc_python_out=. ./protos/grpc_server.proto
```

>Note: This command should be executed from the `node/server` directory.

### Post-Generation Steps

After generating the code, you need to make the following manual changes:

1. In `grpc_server_pb2_grpc.py`, change:
   ```python
   import grpc_server_pb2 as grpc__server__pb2
   ```
   to:
   ```python
   from node.server import grpc_server_pb2 as grpc__server__pb2
   ```

2. For the naptha-sdk client, copy both generated files to the `naptha_sdk/client` folder and modify the import in `grpc_server_pb2_grpc.py` to:
   ```python
   from naptha_sdk.client import grpc_server_pb2 as grpc__server__pb2
   ```

## Service Description

The gRPC service provides the following RPC methods:

- `is_alive`: Health check endpoint
- `stop`: Gracefully stop the server
- `CheckUser`: Verify user credentials
- `RegisterUser`: Register a new user
- `RunModule`: Execute a module with streaming results
- `CheckModuleRun`: Check the status of a module execution
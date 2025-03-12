#!/bin/bash

# Function to stop SurrealDB
stop_surrealdb() {
    # Find and kill the SurrealDB process running on port 3001
    surrealdb_hub_pid=$(lsof -ti:3001)
    if [ ! -z "$surrealdb_hub_pid" ]; then
        echo "Stopping SurrealDB on port 3001"
        kill -9 $surrealdb_hub_pid
    else
        echo "No SurrealDB process found running on port 3001"
    fi
}

# Load the .env file
if [ -f .env ]; then
    set -o allexport
    source .env
    set +o allexport
else
    echo ".env file not found. Using default values."
    NUM_NODE_COMMUNICATION_SERVERS=1
fi

node_communication_protocol=${NODE_COMMUNICATION_PROTOCOL:-"ws"}
start_port=${NODE_COMMUNICATION_PORT:-7002} 

os=$(uname)
if [ "$os" = "Darwin" ]; then
    # Define LaunchAgents path
    LAUNCH_AGENTS_PATH=~/Library/LaunchAgents

    # Stop the services
    launchctl unload $LAUNCH_AGENTS_PATH/com.example.celeryworker.plist
    launchctl unload $LAUNCH_AGENTS_PATH/com.example.nodeapp.http.plist
    for i in $(seq 0 $((${NUM_NODE_COMMUNICATION_SERVERS:-1} - 1))); do
        current_port=$((start_port + i))
        echo "Unloading com.example.nodeapp.${node_communication_protocol}_${current_port}.plist"
        launchctl unload $LAUNCH_AGENTS_PATH/com.example.nodeapp.${node_communication_protocol}_${current_port}.plist
    done
    # Stop LiteLLM
    if launchctl list | grep -q "com.litellm.proxy"; then
        echo "Stopping LiteLLM..."
        launchctl unload ~/Library/LaunchAgents/com.litellm.proxy.plist
    fi
    
    # Stop MPC
    if launchctl list | grep -q "com.naptha.mpc"; then
        echo "Stopping MPC server..."
        launchctl unload ~/Library/LaunchAgents/com.naptha.mpc.plist
    fi

    launchctl unload $LAUNCH_AGENTS_PATH/com.example.ollama.plist
    brew services stop rabbitmq

    # Remove the service files
    rm $LAUNCH_AGENTS_PATH/com.example.celeryworker.plist
    rm $LAUNCH_AGENTS_PATH/com.example.nodeapp.http.plist
    for i in $(seq 0 $((${NUM_NODE_COMMUNICATION_SERVERS:-1} - 1))); do
        current_port=$((start_port + i))
        rm $LAUNCH_AGENTS_PATH/com.example.nodeapp.${node_communication_protocol}_${current_port}.plist
    done
    rm $LAUNCH_AGENTS_PATH/com.litellm.proxy.plist
    rm ~/Library/LaunchAgents/com.naptha.mpc.plist
    rm $LAUNCH_AGENTS_PATH/com.example.ollama.plist

    # Stop SurrealDB
    stop_surrealdb

    # Provide feedback
    echo "Services stopped and plist files removed."
else
    # Function to stop a systemd service with timeout handling
    stop_service() {
        local service_name=$1
        echo "Stopping $service_name..."
        
        if [[ $service_name == "nodeapp_http.service" ]]; then
            echo "Gracefully stopping HTTP server..."
            # First try SIGTERM
            sudo systemctl stop $service_name
            
            # Give it time to unregister and shutdown
            for i in {1..35}; do
                if ! systemctl is-active --quiet $service_name; then
                    echo "HTTP server stopped successfully"
                    return 0
                fi
                if (( i % 5 == 0 )); then
                    echo "Waiting for HTTP server to shutdown... ($i/35)"
                fi
                sleep 1
            done
            
            # If still running, try one more SIGTERM with longer timeout
            echo "Server still running, sending final SIGTERM..."
            sudo systemctl stop --signal=SIGTERM $service_name
            sleep 5
            
            # Finally, if still running, use SIGKILL
            if systemctl is-active --quiet $service_name; then
                echo "Server didn't stop gracefully, sending SIGKILL..."
                sudo systemctl kill -s SIGKILL $service_name
                sleep 2
            fi
        else
            sudo systemctl stop $service_name
            sleep 2

            # force stop if still running
            if systemctl is-active --quiet $service_name; then
                echo "Server didn't stop gracefully, sending SIGKILL..."
                sudo systemctl kill -s SIGKILL $service_name
                sleep 2
            fi
        fi
    }

    # Stop all services with timeout handling
    stop_service celeryworker.service
    stop_service nodeapp_http.service
    
    # Stop additional node communication servers
    for i in $(seq 0 $((${NUM_NODE_COMMUNICATION_SERVERS:-1} - 1))); do
        current_port=$((start_port + i))
        stop_service "nodeapp_${node_communication_protocol}_${current_port}.service"
    done
    
    stop_service litellm.service
    stop_service mpc.service
    stop_service ollama.service
    stop_service rabbitmq-server.service

    # Wait a moment for processes to clean up
    sleep 2

    # Disable all services
    echo "Disabling services..."
    sudo systemctl disable celeryworker.service
    sudo systemctl disable nodeapp_http.service
    for i in $(seq 0 $((${NUM_NODE_COMMUNICATION_SERVERS:-1} - 1))); do
        current_port=$((start_port + i))
        sudo systemctl disable "nodeapp_${node_communication_protocol}_${current_port}.service"
    done
    sudo systemctl disable litellm.service
    sudo systemctl disable mpc.service
    sudo systemctl disable ollama.service
    sudo systemctl disable rabbitmq-server.service

    # Remove service files
    echo "Removing service files..."
    sudo rm -f /etc/systemd/system/celeryworker.service
    sudo rm -f /etc/systemd/system/nodeapp_http.service
    for i in $(seq 0 $((${NUM_NODE_COMMUNICATION_SERVERS:-1} - 1))); do
        current_port=$((start_port + i))
        sudo rm -f "/etc/systemd/system/nodeapp_${node_communication_protocol}_${current_port}.service"
    done
    sudo rm -f /etc/systemd/system/litellm.service
    sudo rm -f /etc/systemd/system/mpc.service
    sudo rm -f /etc/systemd/system/ollama.service
    sudo rm -f /etc/systemd/system/rabbitmq-server.service

    # Reload systemd
    sudo systemctl daemon-reload

    # Stop SurrealDB
    stop_surrealdb

    # Stop PostgreSQL gracefully
    echo "Stopping PostgreSQL..."
    sudo systemctl stop postgresql
    sleep 2

    # Clean up any remaining processes
    echo "Cleaning up any remaining processes..."
    # Find and kill any remaining Python processes related to the servers
    pkill -f "server/server.py"
    pkill -f "node/mpc/server.py"
    pkill -f "celery"
    
    echo "All services stopped and systemd files removed."
fi
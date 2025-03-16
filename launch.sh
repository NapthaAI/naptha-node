#!/bin/bash

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
PINK='\033[0;35m'
NC='\033[0m'

# Function for prefixed logging
log_with_service_name() {
    local service_name=$1
    local color=$2
    while IFS= read -r line; do
        echo -e "${color}[$service_name]${NC} $line"
    done
}

# Function to detect architecture
get_architecture() {
    arch=$(uname -m)
    case $arch in
        x86_64|amd64)
            echo "amd64"
            ;;
        aarch64|arm64)
            echo "arm64"
            ;;
        *)
            echo "Unsupported architecture: $arch" >&2
            exit 1
            ;;
    esac
}

get_surrealdb_version() {
    surreal -V | awk '{print $6}'
}

install_surrealdb() {
    echo "Installing SurrealDB..." | log_with_service_name "SurrealDB" $GREEN

    if [ "$os" = "Darwin" ]; then
        SURREALDB_INSTALL_PATH="/Users/$(whoami)/.surrealdb"
    else
        SURREALDB_INSTALL_PATH="/home/$(whoami)/.surrealdb"
    fi
    mkdir -p "$SURREALDB_INSTALL_PATH"
    SURREALDB_BINARY="$SURREALDB_INSTALL_PATH/surreal"

    # Check if SurrealDB is already installed
    if [ -f /usr/local/bin/surreal ]; then
        CURRENT_VERSION=$(get_surrealdb_version)
        if [[ $CURRENT_VERSION == 2.* ]]; then
            echo "SurrealDB version 2 ($CURRENT_VERSION) is already installed." | log_with_service_name "SurrealDB" $GREEN
            return
        else
            echo "Removing existing SurrealDB version $CURRENT_VERSION..." | log_with_service_name "SurrealDB" $YELLOW
            sudo rm /usr/local/bin/surreal
        fi
    fi

    echo "Installing SurrealDB version 2..." | log_with_service_name "SurrealDB" $GREEN

    # Install SurrealDB
    curl -sSf https://install.surrealdb.com > /tmp/surreal_install.sh
    sh /tmp/surreal_install.sh -- "$SURREALDB_INSTALL_PATH"

    if [ -f "$SURREALDB_BINARY" ]; then
        echo "Moving SurrealDB binary to /usr/local/bin..." | log_with_service_name "SurrealDB" $GREEN
        sudo mv "$SURREALDB_BINARY" /usr/local/bin/surreal
        if [ $? -ne 0 ]; then
            echo "Failed to move SurrealDB binary. Trying to copy instead..." | log_with_service_name "SurrealDB" $YELLOW
            sudo cp "$SURREALDB_BINARY" /usr/local/bin/surreal
            if [ $? -ne 0 ]; then
                echo "Failed to copy SurrealDB binary. Installation failed." | log_with_service_name "SurrealDB" $RED
                exit 1
            fi
        fi
        echo "SurrealDB binary installed in /usr/local/bin." | log_with_service_name "SurrealDB" $GREEN
    else
        echo "SurrealDB binary not found at $SURREALDB_BINARY. Installation may have failed." | log_with_service_name "SurrealDB" $RED
        exit 1
    fi

    # Verify installed version
    if command -v surreal &> /dev/null; then
        INSTALLED_VERSION=$(get_surrealdb_version)
        if [[ $INSTALLED_VERSION == 2.* ]]; then
            echo "SurrealDB version 2 ($INSTALLED_VERSION) installed successfully." | log_with_service_name "SurrealDB" $GREEN
        else
            echo "Failed to install SurrealDB version 2. Got version: $INSTALLED_VERSION" | log_with_service_name "SurrealDB" $RED
            exit 1
        fi
    else
        echo "SurrealDB command not found. Installation failed." | log_with_service_name "SurrealDB" $RED
        exit 1
    fi
}

# Function for manual installation of Ollama
linux_install_ollama() {
    set -a
    source .env
    set +a

    # Echo start Ollama
    echo "Installing Ollama..." | log_with_service_name "Ollama" $RED

    # Set up directory paths based on current location
    CURRENT_DIR=$(pwd)
    PROJECT_MODELS_DIR="$CURRENT_DIR/node/inference/ollama/models"
    
    # Create the directory structure
    sudo mkdir -p "$PROJECT_MODELS_DIR"
    echo "Created models directory at: $PROJECT_MODELS_DIR" | log_with_service_name "Ollama" $RED

    install_ollama_app() {
        sudo curl -fsSL https://ollama.com/install.sh | sh
    }

    create_ollama_service() {
        # Create systemd service file
        cat > /tmp/ollama.service << EOF
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=/bin/bash -c 'exec $(which ollama) serve'
Environment=OLLAMA_MODELS=/var/lib/ollama/models
User=ollama
Group=ollama
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
        sudo mv /tmp/ollama.service /etc/systemd/system/ollama.service
    }

    create_ollama_directories() {
        # Create ollama user and group
        sudo useradd -r -s /bin/false ollama 2>/dev/null || true

        # Create and set permissions for ollama directories
        sudo mkdir -p /usr/share/ollama
        sudo mkdir -p /var/lib/ollama/models
        sudo chown -R ollama:ollama /usr/share/ollama /var/lib/ollama
        sudo chmod -R 755 /usr/share/ollama /var/lib/ollama

        # Create project directory structure
        sudo mkdir -p "$(dirname "$PROJECT_MODELS_DIR")"
        
        # Remove existing directory or link if it exists
        sudo rm -rf "$PROJECT_MODELS_DIR"
        
        # Create symbolic link from project directory to system models
        sudo ln -sf /var/lib/ollama/models "$PROJECT_MODELS_DIR"
        
        # Set permissions for the project directory and link
        sudo chown -R ollama:ollama "$(dirname "$PROJECT_MODELS_DIR")"
        sudo chmod -R 755 "$(dirname "$PROJECT_MODELS_DIR")"
    }

    restart_ollama_linux() {
        sudo systemctl daemon-reload
        sudo systemctl enable ollama
        sudo systemctl start ollama
    }

    # Get current version if Ollama exists
    local current_version=""
    current_version=$(ollama -v 2>/dev/null | grep -oP '(?:client version is |version is )(\K[\d.]+)')

    # Get latest version from GitHub release
    local latest_version=""
    latest_version=$(curl -sf https://api.github.com/repos/ollama/ollama/releases/latest | 
                    grep '"tag_name":' | 
                    sed -E 's/.*"v([^"]+)".*/\1/')

    if [ -z "$latest_version" ]; then
        echo "Failed to get latest version from GitHub" | log_with_service_name "Ollama" $RED
        exit 1
    fi

    echo "Current version: $current_version" | log_with_service_name "Ollama" $RED
    echo "Latest version: $latest_version" | log_with_service_name "Ollama" $RED   

    # Case 1: Ollama not installed
    if ! command -v ollama >/dev/null 2>&1; then
        echo "Installing Ollama..." | log_with_service_name "Ollama" $RED
        install_ollama_app
        echo "Ollama installed successfully" | log_with_service_name "Ollama" $RED

    # Case 2: Version needs update
    elif [ -z "$current_version" ] || [ "$current_version" != "$latest_version" ]; then
        echo "Updating Ollama from ${current_version:-unknown} to ${latest_version}" | log_with_service_name "Ollama" $RED
        install_ollama_app
        echo "Ollama updated successfully" | log_with_service_name "Ollama" $RED

    # Case 3: Latest version already installed
    else
        echo "Latest version of Ollama (${current_version}) is already installed" | log_with_service_name "Ollama" $RED
    fi

    # Create and install systemd service file
    create_ollama_service
    
    # Create necessary directories and set permissions
    create_ollama_directories
    
    # Restart the service
    restart_ollama_linux

    # Pull Ollama models
    echo "Pulling Ollama models: $OLLAMA_MODELS" | log_with_service_name "Ollama" $RED
    IFS=',' read -ra MODELS <<< "$OLLAMA_MODELS"
    for model in "${MODELS[@]}"; do
        echo "Pulling model: $model" | log_with_service_name "Ollama" $RED
        ollama pull "$model"
    done
}

pull_ollama_models() {
    # Pull Ollama models
    echo "Pulling Ollama models: $OLLAMA_MODELS" | log_with_service_name "Ollama" $RED
    IFS=',' read -ra MODELS <<< "$OLLAMA_MODELS"
    for model in "${MODELS[@]}"; do
        echo "Pulling model: $model" | log_with_service_name "Ollama" $RED
        ollama pull "$model"
    done
}

darwin_install_ollama() {
    echo "Installing Ollama..." | log_with_service_name "Ollama" $RED

    # Get current version if Ollama.app exists
    local current_version=""
    if [ -d "/Applications/Ollama.app" ]; then
        current_version=$(defaults read /Applications/Ollama.app/Contents/Info.plist CFBundleShortVersionString 2>/dev/null || echo "")
    fi

    # Get latest version from GitHub release
    # local latest_version=""
    # TODO (@enricorotundo): remove the hardcoded version
    local latest_version="0.5.11"
    # latest_version=$(curl -sf https://api.github.com/repos/ollama/ollama/releases/latest | 
    #                 grep '"tag_name":' | 
    #                 sed -E 's/.*"v([^"]+)".*/\1/')
    
    if [ -z "$latest_version" ]; then
        echo "Failed to get latest version from GitHub" | log_with_service_name "Ollama" $RED
        exit 1
    fi

    echo "Current version: $current_version" | log_with_service_name "Ollama" $RED
    echo "Latest version: $latest_version" | log_with_service_name "Ollama" $RED

    install_ollama_app() {
        local temp_dir=$(mktemp -d)
        curl -L https://github.com/ollama/ollama/releases/download/v${latest_version}/Ollama-darwin.zip -o "$temp_dir/ollama.zip"
        unzip -o "$temp_dir/ollama.zip" -d "$temp_dir"
        sudo rm -rf "/Applications/Ollama.app"
        sudo mv "$temp_dir/Ollama.app" "/Applications/"
        rm -rf "$temp_dir"
    }

    # Case 1: Ollama not installed
    if [ ! -d "/Applications/Ollama.app" ]; then
        echo "Ollama is not installed. Installing..." | log_with_service_name "Ollama" $RED
        install_ollama_app
        echo "Ollama installed successfully" | log_with_service_name "Ollama" $RED
    
    # Case 2: Version needs update
    elif [ -z "$current_version" ] || [ "$current_version" != "$latest_version" ]; then
        echo "Updating Ollama from ${current_version:-unknown} to ${latest_version}" | log_with_service_name "Ollama" $RED
        pkill -f "Ollama" || true
        install_ollama_app
        echo "Ollama updated successfully" | log_with_service_name "Ollama" $RED
    
    # Case 3: Latest version already installed
    else
        echo "Latest version of Ollama (${current_version}) is already installed" | log_with_service_name "Ollama" $RED
    fi

    # Start Ollama.app
    echo "Starting Ollama..." | log_with_service_name "Ollama" $RED
    open -a /Applications/Ollama.app
    sleep 2

    # Verify Ollama is running
    if ! pgrep -f "Ollama" >/dev/null; then
        echo "Failed to start Ollama" | log_with_service_name "Ollama" $RED
        exit 1
    fi

    pull_ollama_models

    echo "Ollama is now running" | log_with_service_name "Ollama" $RED
}

# Function to install Miniforge
linux_install_miniforge() {
    
    echo "Checking for Miniforge installation..." | log_with_service_name "Miniforge" $BLUE

    # Check if Miniforge is already installed
    if [ -d "$HOME/miniforge3" ]; then
        echo "Miniforge is already installed." | log_with_service_name "Miniforge" $BLUE
    else
        # Installation process
        echo "Installing Miniforge..." | log_with_service_name "Miniforge" $BLUE
        arch=$(get_architecture)
        if [ "$arch" = "amd64" ]; then
            MINIFORGE_INSTALLER="Miniforge3-Linux-x86_64.sh"
        else
            MINIFORGE_INSTALLER="Miniforge3-Linux-aarch64.sh"
        fi
        curl -sSL "https://github.com/conda-forge/miniforge/releases/latest/download/$MINIFORGE_INSTALLER" -o $MINIFORGE_INSTALLER
        chmod +x $MINIFORGE_INSTALLER
        ./$MINIFORGE_INSTALLER -b
        rm $MINIFORGE_INSTALLER
        "$HOME/miniforge3/bin/conda" init bash
    fi

    # Ensure Miniforge's bin directory is in PATH in .bashrc
    if ! grep -q 'miniforge3/bin' ~/.bashrc; then
        echo 'export PATH="$HOME/miniforge3/bin:$PATH"' >> ~/.bashrc
        source ~/.bashrc
        echo "Miniforge path added to .bashrc" | log_with_service_name "Miniforge" $BLUE
    fi

    # Activate Miniforge environment
    eval "$($HOME/miniforge3/bin/conda shell.bash hook)"
    conda activate

    # Check which Python is in use
    PYTHON_PATH=$(which python)
    if [[ $PYTHON_PATH == *"$HOME/miniforge3"* ]]; then
        echo "Miniforge Python is in use." | log_with_service_name "Miniforge" $BLUE
    else
        echo "Miniforge Python is not in use. Activating..." | log_with_service_name "Miniforge" $BLUE
        # Assuming there is a default environment to activate or using base
        conda activate base

        # Check which Python is in use again
        PYTHON_PATH=$(which python)
        echo "Python path: $PYTHON_PATH" | log_with_service_name "Miniforge" $BLUE
    fi
}

darwin_install_miniforge() {
    echo "Checking for Miniforge installation..." | log_with_service_name "Miniforge" $BLUE

    # Check if Miniforge is already installed
    if [ -d "$HOME/miniforge3" ]; then
        echo "Miniforge is already installed." | log_with_service_name "Miniforge" $BLUE
    else
        # Installation process
        echo "Installing Miniforge..." | log_with_service_name "Miniforge" $BLUE
        arch=$(get_architecture)
        if [ "$arch" = "amd64" ]; then
            MINIFORGE_INSTALLER="Miniforge3-Darwin-x86_64.sh"
        else
            MINIFORGE_INSTALLER="Miniforge3-Darwin-$arch.sh"
        fi
        curl -sSL "https://github.com/conda-forge/miniforge/releases/latest/download/$MINIFORGE_INSTALLER" -o $MINIFORGE_INSTALLER
        chmod +x $MINIFORGE_INSTALLER
        ./$MINIFORGE_INSTALLER -b
        rm $MINIFORGE_INSTALLER
        "$HOME/miniforge3/bin/conda" init zsh
    fi

    # Ensure Miniforge's bin directory is in PATH in .zshrc
    if ! grep -q 'miniforge3/bin' ~/.zshrc; then
        echo 'export PATH="$HOME/miniforge3/bin:$PATH"' >> ~/.zshrc
        source ~/.zshrc
        echo "Miniforge path added to .zshrc" | log_with_service_name "Miniforge" $BLUE
    fi

    # Activate Miniforge environment
    eval "$($HOME/miniforge3/bin/conda shell.zsh hook)"
    conda activate

    # Check which Python is in use
    PYTHON_PATH=$(which python)
    if [[ $PYTHON_PATH == *"$HOME/miniforge3"* ]]; then
        echo "Miniforge Python is in use." | log_with_service_name "Miniforge" $BLUE
    else
        echo "Miniforge Python is not in use. Activating..." | log_with_service_name "Miniforge" $BLUE
        # Assuming there is a default environment to activate or using base
        conda activate base

        # Check which Python is in use again
        PYTHON_PATH=$(which python)
        echo "Python path: $PYTHON_PATH" | log_with_service_name "Miniforge" $BLUE
    fi
}

# Fuction to clean the node
linux_clean_node() {
    # Eccho start cleaning
    echo "Cleaning node..." | log_with_service_name "Node" $BLUE

    # Remove node/agents if it exists
    if [ -d "node/agents" ]; then
        rm -rf node/agents
    fi

    if ! dpkg -l | grep -q "make"; then
        echo "Make not found. Installing Make..."
        sudo apt-get update
        sudo apt-get install -y make
    else
        echo "Make is already installed. Skipping installation."
    fi

    make pyproject-clean
}

darwin_clean_node() {
    # Echo start cleaning
    echo "Cleaning node..." | log_with_service_name "Node" $BLUE

    # Remove node_modules if it exists
    if [ -d "node_modules" ]; then
        rm -rf node_modules
        echo "Removed node_modules directory." | log_with_service_name "Node" $BLUE
    fi

    # Check if Homebrew is installed
    if ! command -v brew >/dev/null 2>&1; then
        echo "Homebrew not found. Installing Homebrew..." | log_with_service_name "Homebrew" $NC
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi

    # Install make using Homebrew
    if ! command -v make >/dev/null 2>&1; then
        echo "Installing make..." | log_with_service_name "Make" $NC
        brew install make
    else
        echo "Make is already installed." | log_with_service_name "Make" $NC
    fi

    # Run make pyproject-clean
    if [ -f "Makefile" ]; then
        echo "Running make pyproject-clean..." | log_with_service_name "Node" $BLUE
        make pyproject-clean
    else
        echo "Makefile not found. Skipping make pyproject-clean." | log_with_service_name "Node" $BLUE
    fi
}


# Function to check if Docker is running
check_docker() {
    # Echo start checking Docker
    echo "Checking Docker..." | log_with_service_name "Docker" $RED
    if ! docker info >/dev/null 2>&1; then
        echo "Docker does not seem to be running, please start Docker first." | log_with_service_name "Docker" $RED
        exit 1
    fi
}

linux_install_docker() {
    echo "Checking for Docker installation..." | log_with_service_name "Docker" $RED
    
    set -a
    source .env
    set +a

    if [ "$DOCKER_JOBS" = "True" ]; then
        echo "Docker jobs are enabled." | log_with_service_name "Docker" $RED
    else
        echo "Docker jobs are disabled." | log_with_service_name "Docker" $RED
        return
    fi

    if docker >/dev/null 2>&1; then
        echo "Docker is already installed." | log_with_service_name "Docker" $RED
    else
        echo "Installing Docker." | log_with_service_name "Docker" $RED

        sudo apt-get update
        sudo apt-get install ca-certificates curl
        sudo install -m 0755 -d /etc/apt/keyrings
        sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        sudo chmod a+r /etc/apt/keyrings/docker.asc

        # Add the repository to Apt sources:
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
        $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update

        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

        sudo chmod 666 /var/run/docker.sock

        echo "Docker installed." | log_with_service_name "Docker" $RED
        echo "Starting Docker." | log_with_service_name "Docker" $RED
    fi

    echo "Checking if Docker is running..." | log_with_service_name "Docker" $RED
    if docker info >/dev/null 2>&1; then
        echo "Docker is already running." | log_with_service_name "Docker" $RED
    else
        echo "Starting Docker." | log_with_service_name "Docker" $RED
        sudo systemctl enable docker.service
        sudo systemctl start docker
    fi

    if ! sudo docker info >/dev/null 2>&1; then
        echo "Docker still does not seem to be running. Exiting..." | log_with_service_name "Docker" $RED
        exit 1
    fi    

    echo "Docker is running." | log_with_service_name "Docker" $RED
}

darwin_install_docker() {
    echo "Checking for Docker installation..." | log_with_service_name "Docker" $RED
    
    set -a
    source .env
    set +a

    if [ "$DOCKER_JOBS" = "True" ]; then
        echo "Docker jobs are enabled." | log_with_service_name "Docker" $RED
    else
        echo "DOCKER_JOBS: $DOCKER_JOBS" | log_with_service_name "Docker" $RED
        echo "Docker jobs are disabled." | log_with_service_name "Docker" $RED
        return
    fi

    if docker --version >/dev/null 2>&1; then
        echo "Docker is already installed." | log_with_service_name "Docker" $RED
        
        # Try to start Docker even if it's installed
        echo "Starting Docker..." | log_with_service_name "Docker" $RED
        open -a Docker
    else
        echo "Installing Docker..." | log_with_service_name "Docker" $RED

        if ! command -v brew >/dev/null 2>&1; then
            echo "Homebrew not found. Installing Homebrew..." | log_with_service_name "Homebrew" $NC
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi

        brew install --cask docker
        echo "Docker installed." | log_with_service_name "Docker" $RED
        echo "Starting Docker..." | log_with_service_name "Docker" $RED
        open -a Docker
    fi

    # Wait for Docker to start with timeout
    echo "Waiting for Docker to start..." | log_with_service_name "Docker" $RED
    timeout=60
    start_time=$(date +%s)
    
    while ! docker info >/dev/null 2>&1; do
        current_time=$(date +%s)
        elapsed=$((current_time - start_time))
        
        if [ $elapsed -gt $timeout ]; then
            echo "Timeout after ${timeout} seconds waiting for Docker" | log_with_service_name "Docker" $RED
            return 1
        fi
        echo "Still waiting... (${elapsed}s)" | log_with_service_name "Docker" $RED
        sleep 5
    done

    echo "Docker is running." | log_with_service_name "Docker" $RED
    return 0
}

# Function to start RabbitMQ on Linux
linux_start_rabbitmq() {
    echo "Starting RabbitMQ on Linux..." | log_with_service_name "RabbitMQ" $PINK
    # Load the .env file
    set -a
    source .env
    set +a

    # Check if RabbitMQ is already installed
    if ! dpkg -l | grep -q "rabbitmq-server"; then
        echo "RabbitMQ not found. Installing RabbitMQ..."
        sudo apt-get update
        sudo apt-get install -y rabbitmq-server
    else
        echo "RabbitMQ is already installed. Skipping installation."
    fi

    # Enable the management plugin
    sudo rabbitmq-plugins enable rabbitmq_management

    # Start RabbitMQ
    sudo systemctl enable rabbitmq-server
    sudo systemctl start rabbitmq-server

    # Check if the user already exists
    if sudo rabbitmqctl list_users | grep -q "^$RMQ_USER"; then
        echo "User '$RMQ_USER' already exists. Skipping user creation."
    else
        # Create a new user with the credentials from .env
        sudo rabbitmqctl add_user "$RMQ_USER" "$RMQ_PASSWORD"
        sudo rabbitmqctl set_user_tags "$RMQ_USER" administrator
        sudo rabbitmqctl set_permissions -p / "$RMQ_USER" ".*" ".*" ".*"
    fi
    echo "RabbitMQ started with management console on default port." | log_with_service_name "RabbitMQ" $PINK
}

# Function to start RabbitMQ on macOS
darwin_start_rabbitmq() {
    echo "Starting RabbitMQ on macOS..." | log_with_service_name "RabbitMQ" $PINK

    # Load the .env file
    set -a
    source .env
    set +a

    # Install RabbitMQ using Homebrew
    if ! brew list rabbitmq &>/dev/null; then
        echo "RabbitMQ not found. Installing RabbitMQ..."
        brew install rabbitmq
    else
        echo "RabbitMQ is already installed. Skipping installation."
    fi

    # Enable the management plugin
    rabbitmq-plugins enable rabbitmq_management

    # Start RabbitMQ
    brew services start rabbitmq

    # Check if the user already exists
    if rabbitmqctl list_users | grep -q "^$RMQ_USER"; then
        echo "User '$RMQ_USER' already exists. Skipping user creation."
    else
        # Create a new user with the credentials from .env
        rabbitmqctl add_user "$RMQ_USER" "$RMQ_PASSWORD"
        rabbitmqctl set_user_tags "$RMQ_USER" administrator
        rabbitmqctl set_permissions -p / "$RMQ_USER" ".*" ".*" ".*"
    fi

    echo "RabbitMQ started with management console on default port." | log_with_service_name "RabbitMQ" $PINK
}

setup_uv() {
    echo "Setting up uv..." | log_with_service_name "uv" "$BLUE"
    
    # Ensure the script is running within a Conda environment
    if [ -z "$CONDA_DEFAULT_ENV" ]; then
        echo "Not inside a Conda environment. Activating Miniforge..." | log_with_service_name "uv" "$BLUE"
        source "$HOME/miniforge3/bin/activate"
        conda activate
    fi

    # Install uv if it's not already installed
    if ! command -v uv >/dev/null 2>&1; then
        echo "Installing uv..." | log_with_service_name "uv" "$BLUE"
        curl -LsSf https://astral.sh/uv/install.sh | sh
    else
        echo "uv is already installed." | log_with_service_name "uv" "$BLUE"
    fi

    os="$(uname)"
    if [ "$os" = "Darwin" ]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    else
        export PATH="$HOME/.cargo/bin:$PATH"
    fi

    # Create a virtual environment in the project directory
    echo "Creating virtual environment with uv..." | log_with_service_name "uv" "$BLUE"
    uv venv .venv

    # Install pip in the virtual environment
    echo "Installing pip in the virtual environment..." | log_with_service_name "uv" "$BLUE"
    source .venv/bin/activate
    curl -sSL https://bootstrap.pypa.io/get-pip.py -o get-pip.py
    python get-pip.py
    rm get-pip.py
    
    # Install dependencies
    echo "Installing dependencies with uv..." | log_with_service_name "uv" "$BLUE"
    
    # Set up PostgreSQL environment variables for building psycopg
    if [ "$os" = "Darwin" ]; then
        export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
        export LDFLAGS="-L/opt/homebrew/opt/postgresql@17/lib"
        export CPPFLAGS="-I/opt/homebrew/opt/postgresql@17/include"
    else
        export PATH="/usr/lib/postgresql/16/bin:$PATH"
        export LDFLAGS="-L/usr/lib/postgresql/16/lib"
        export CPPFLAGS="-I/usr/lib/postgresql/16/include"
    fi
    
    # Install dependencies from pyproject.toml
    uv pip install .
    
    # Install surrealdb version 0.3.2 specifically
    echo "Installing surrealdb==0.3.2..." | log_with_service_name "uv" "$BLUE"
    uv pip install surrealdb==0.3.2
    
    # Verify the presence of a .venv folder within the project directory
    if [ -d ".venv" ]; then
        echo ".venv folder is present in the project folder." | log_with_service_name "uv" "$BLUE"
    else
        echo "uv virtual environment setup failed." | log_with_service_name "uv" "$BLUE"
        exit 1
    fi
}


# Function to install Python 3.12 on Linux
install_python312() {
    echo "Checking for Python 3.12 installation..." | log_with_service_name "Python" $NC
    if python3.12 --version >/dev/null 2>&1; then
        echo "Python 3.12 is already installed." | log_with_service_name "Python" $NC
        return
    fi

    os="$(uname)"
    if [ "$os" = "Darwin" ]; then
        echo "Installing Python 3.12..." | log_with_service_name "Python" $NC
        brew install python@3.12
        python3.12 --version
    else
        echo "Installing Python 3.12..." | log_with_service_name "Python" $NC
        sudo add-apt-repository ppa:deadsnakes/ppa -y
        sudo apt update
        sudo apt install -y python3.12
        python3.12 --version
    fi
    echo "Python 3.12 is installed." | log_with_service_name "Python" $NC
}

# Function to start the Hub SurrealDB
start_hub_surrealdb() {
    PWD=$(pwd)
    echo "LOCAL_HUB: $LOCAL_HUB" | log_with_service_name "Config"
    if [ "$LOCAL_HUB" == "true" ]; then
        echo "Running Hub DB (SurrealDB) locally..." | log_with_service_name "HubDBSurreal" $RED
        
        INIT_PYTHON_PATH="$PWD/node/storage/hub/init_hub.py"
        chmod +x "$INIT_PYTHON_PATH"

        uv run python "$INIT_PYTHON_PATH" 2>&1
        PYTHON_EXIT_STATUS=$?
        if [ $PYTHON_EXIT_STATUS -ne 0 ]; then
            echo "Hub DB (SurrealDB) initialization failed. Python script exited with status $PYTHON_EXIT_STATUS." | log_with_service_name "HubDBSurreal" $RED
            exit 1
        fi

        # Check if Hub DB (SurrealDB) is running
        if curl -s http://localhost:$HUB_DB_SURREAL_PORT/health > /dev/null; then
            echo "Hub DB (SurrealDB) is running successfully." | log_with_service_name "HubDBSurreal" $RED
        else
            echo "Hub DB failed to start. Please check the logs." | log_with_service_name "HubDBSurreal" $RED
            exit 1
        fi
    else
        echo "Not running Hub DB (SurrealDB) locally..." | log_with_service_name "HubDBSurreal" $RED
    fi

    uv run python "$PWD/node/storage/hub/init_hub.py" --user 2>&1
    PYTHON_EXIT_STATUS=$?
    echo "PYTHON_EXIT_STATUS: $PYTHON_EXIT_STATUS"
    if [ $PYTHON_EXIT_STATUS -ne 0 ]; then
        echo "Hub DB (SurrealDB) sign in flow failed. Python script exited with status $PYTHON_EXIT_STATUS." | log_with_service_name "HubDBSurreal" $RED
        exit 1
    fi
}

start_local_surrealdb() {
    PWD=$(pwd)

    echo "Running Local DB..." | log_with_service_name "LocalDBPostgres" $RED
    
    INIT_PYTHON_PATH="$PWD/node/storage/db/init_db.py"
    chmod +x "$INIT_PYTHON_PATH"

    uv run python "$INIT_PYTHON_PATH" 2>&1
    PYTHON_EXIT_STATUS=$?

    if [ $PYTHON_EXIT_STATUS -ne 0 ]; then
        echo "Local DB initialization failed. Python script exited with status $PYTHON_EXIT_STATUS." | log_with_service_name "LocalDBPostgres" $RED
        exit 1
    fi

    # Check if Local DB is running
    if curl -s http://localhost:$SURREALDB_PORT/health > /dev/null; then
        echo "Local DB is running successfully." | log_with_service_name "LocalDBPostgres" $RED
    else
        echo "Local DB failed to start. Please check the logs." | log_with_service_name "LocalDBPostgres" $RED
        exit 1
    fi
}

# Function to check and copy the .env file
check_and_copy_env() {
    if [ ! -f .env ]; then
        cp .env.example .env
        echo ".env file created from .env.example"
    else
        echo ".env file already exists."
    fi
}

# Function to check and set the private key
check_and_set_private_key() {
    check_and_set_hub_credentials
    os="$(uname)"
    if [[ -f .env ]]; then
        if [ "$os" = "Darwin" ]; then
            key_file_value=$(grep '^PRIVATE_KEY=' .env | awk -F'=' '{print $2}')
        else
            key_file_value=$(grep -oP '(?<=^PRIVATE_KEY=).*' .env)
        fi
        if [[ -n "$key_file_value" && -f "$key_file_value" ]]; then
            echo "PRIVATE_KEY already set and file exists."
            return
        fi
    else
        touch .env
    fi

    read -p "No valid PRIVATE_KEY set. Would you like to generate one? (yes/no): " response
    if [[ "$response" == "yes" ]]; then
        source .env
        key_file=$(uv run python scripts/generate_user.py "$HUB_USERNAME")
        key_file=$(echo "$key_file" | tr -d '\n')
        key_file=$(basename "$key_file")
        if [ "$os" = "Darwin" ]; then
            sed -i '' "s/^PRIVATE_KEY=.*/PRIVATE_KEY=$key_file/" .env
        else
            sed -i "/^PRIVATE_KEY=/c\PRIVATE_KEY=$key_file" .env
        fi
        echo "Key pair generated and saved to PEM file. PRIVATE_KEY set in .env."
    else
        echo "Key pair generation aborted."
    fi
}


load_env_file() {
    CURRENT_DIR=$(pwd)
    ENV_FILE="$CURRENT_DIR/.env"
    
    # Debug: Check if .env file exists and permissions
    if [ -f "$ENV_FILE" ]; then
        echo ".env file found." | log_with_service_name "Config"
        # Load .env file
        set -a
        . "$ENV_FILE"
        set +a

        . .venv/bin/activate
    else
        echo ".env file does not exist in $CURRENT_DIR." | log_with_service_name "Config" 
        exit 1
    fi
}

linux_start_servers() {
    # Echo start Servers
    echo "Starting Servers..." | log_with_service_name "Server" $BLUE

    # Get the config from the .env file
    node_communication_protocol=${NODE_COMMUNICATION_PROTOCOL:-"ws"} # Default to ws if not set
    num_node_communication_servers=${NUM_NODE_COMMUNICATION_SERVERS:-1} # Default to 1 if not set
    start_port=${NODE_COMMUNICATION_PORT:-7002} # Starting port for alternate servers

    echo "Node communication protocol: $node_communication_protocol" | log_with_service_name "Server" $BLUE
    echo "Number of node communication servers: $num_node_communication_servers" | log_with_service_name "Server" $BLUE
    echo "Node communication servers start from port: $start_port" | log_with_service_name "Server" $BLUE

    # Define paths
    USER_NAME=$(whoami)
    CURRENT_DIR=$(pwd)
    PYTHON_APP_PATH="$CURRENT_DIR/.venv/bin/python"
    WORKING_DIR="$CURRENT_DIR/node"
    ENVIRONMENT_FILE_PATH="$CURRENT_DIR/.env"

    # First create HTTP server service (always port 7001)
    HTTP_SERVICE_FILE="nodeapp_http.service"
    echo "Starting HTTP server on port 7001..." | log_with_service_name "Server" $BLUE

    # Create the systemd service file for HTTP server
    cat <<EOF > /tmp/$HTTP_SERVICE_FILE
[Unit]
Description=Node HTTP Server
After=network.target

[Service]
ExecStart=$PYTHON_APP_PATH $WORKING_DIR/server/server.py --communication-protocol http --port 7001
WorkingDirectory=$CURRENT_DIR
EnvironmentFile=$ENVIRONMENT_FILE_PATH
User=$USER_NAME
Restart=always
TimeoutStopSec=90
KillMode=mixed
KillSignal=SIGTERM
SendSIGKILL=yes

# Environment variables for shutdown behavior
Environment=UVICORN_TIMEOUT=30
Environment=UVICORN_GRACEFUL_SHUTDOWN=30
Environment=PATH=$HOME/.local/bin:$HOME/.cargo/bin:${PATH}

[Install]
WantedBy=multi-user.target
EOF

    # Move the HTTP service file and start it
    sudo mv /tmp/$HTTP_SERVICE_FILE /etc/systemd/system/
    sudo systemctl daemon-reload
    if sudo systemctl enable $HTTP_SERVICE_FILE && sudo systemctl start $HTTP_SERVICE_FILE; then
        echo "HTTP server service started successfully on port 7001." | log_with_service_name "Server" $BLUE
    else
        echo "Failed to start HTTP server service." | log_with_service_name "Server" $RED
        return 1
    fi

    # Track all ports for .env file
    ports="7001"

    # Create services for additional servers
    for ((i=0; i<num_node_communication_servers; i++)); do
        current_port=$((start_port + i))
        SERVICE_FILE="nodeapp_${node_communication_protocol}_${current_port}.service"
        ports="${ports},${current_port}"

        echo "Starting $node_communication_protocol node communication server on port $current_port..." | log_with_service_name "Server" $BLUE

        # Create the systemd service file
        cat <<EOF > /tmp/$SERVICE_FILE
[Unit]
Description=Node $node_communication_protocol Node Communication Server on port $current_port
After=network.target nodeapp_http.service

[Service]
ExecStart=$PYTHON_APP_PATH $WORKING_DIR/server/server.py --communication-protocol $node_communication_protocol --port $current_port
WorkingDirectory=$CURRENT_DIR
EnvironmentFile=$ENVIRONMENT_FILE_PATH
User=$USER_NAME
Restart=always
TimeoutStopSec=3
KillMode=mixed
KillSignal=SIGTERM
SendSIGKILL=yes
Environment=PATH=$HOME/.local/bin:$HOME/.cargo/bin:${PATH}

[Install]
WantedBy=multi-user.target
EOF

        # Move the service file and start it
        sudo mv /tmp/$SERVICE_FILE /etc/systemd/system/
        sudo systemctl daemon-reload
        if sudo systemctl enable $SERVICE_FILE && sudo systemctl start $SERVICE_FILE; then
            echo "$node_communication_protocol server service started successfully on port $current_port." | log_with_service_name "Server" $BLUE
        else
            echo "Failed to start $node_communication_protocol server service on port $current_port." | log_with_service_name "Server" $RED
        fi
    done

    NODE_COMMUNICATION_PORTS=$ports
}

darwin_start_servers() {
    # Echo start Node
    echo "Starting Servers..." | log_with_service_name "Server" $BLUE

    # Get the config from the .env file
    node_communication_protocol=${NODE_COMMUNICATION_PROTOCOL:-"ws"} # Default to ws if not set
    num_node_communication_servers=${NUM_NODE_COMMUNICATION_SERVERS:-1} # Default to 1 if not set
    start_port=${NODE_COMMUNICATION_PORT:-7002} # Starting port for alternate servers

    echo "Node communication protocol: $node_communication_protocol" | log_with_service_name "Server" $BLUE
    echo "Number of node communication servers: $num_node_communication_servers" | log_with_service_name "Server" $BLUE
    echo "Node communication servers start from port: $start_port" | log_with_service_name "Server" $BLUE

    # Define paths
    USER_NAME=$(whoami)
    CURRENT_DIR=$(pwd)
    PYTHON_APP_PATH="$CURRENT_DIR/.venv/bin/python" # Changed to use Python directly
    WORKING_DIR="$CURRENT_DIR/node"
    ENVIRONMENT_FILE_PATH="$CURRENT_DIR/.env"
    SURRREALDB_PATH="/usr/local/bin"

    # First create HTTP server plist (always port 7001)
    HTTP_PLIST_FILE="com.example.nodeapp.http.plist"
    echo "Starting HTTP server on port 7001..." | log_with_service_name "Server" $BLUE

    PLIST_PATH=~/Library/LaunchAgents/$HTTP_PLIST_FILE

    # Create the launchd plist file for HTTP server
    cat <<EOF > ~/Library/LaunchAgents/$HTTP_PLIST_FILE
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.example.nodeapp.http</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_APP_PATH</string>
        <string>$WORKING_DIR/server/server.py</string>
        <string>--communication-protocol</string>
        <string>http</string>
        <string>--port</string>
        <string>7001</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$CURRENT_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>$CURRENT_DIR</string>
        <key>ENVIRONMENT_FILE_PATH</key>
        <string>$ENVIRONMENT_FILE_PATH</string>
        <key>PATH</key>
        <string>$HOME/.local/bin:$HOME/.cargo/bin:$CURRENT_DIR/.venv/bin:$SURRREALDB_PATH:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/nodeapp_http.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/nodeapp_http.log</string>
</dict>
</plist>
EOF

    # Load and start HTTP server with error checking
    echo "Loading HTTP server service..." | log_with_service_name "Server" $BLUE
    if ! launchctl load $PLIST_PATH; then
        echo "Failed to load HTTP server service. Checking permissions..." | log_with_service_name "Server" $RED
        ls -l $PLIST_PATH
        exit 1
    fi

    # Verify service is running
    sleep 2
    if launchctl list | grep -q "com.example.nodeapp.http"; then
        echo "HTTP server service loaded successfully." | log_with_service_name "Server" $GREEN
    else
        echo "HTTP server service failed to load. Check system logs:" | log_with_service_name "Server" $RED
        sudo log show --predicate 'processImagePath contains "nodeapp"' --last 5m
        exit 1
    fi

    # Track all ports for .env file
    ports="7001"

    # Create plists for additional servers
    for ((i=0; i<num_node_communication_servers; i++)); do
        current_port=$((start_port + i))
        PLIST_FILE="com.example.nodeapp.${node_communication_protocol}_${current_port}.plist"
        PLIST_PATH=~/Library/LaunchAgents/$PLIST_FILE
        ports="${ports},${current_port}"

        echo "Starting $node_communication_protocol server on port $current_port..." | log_with_service_name "Server" $BLUE

        cat <<EOF > ~/Library/LaunchAgents/$PLIST_FILE
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.example.nodeapp.${node_communication_protocol}_${current_port}</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_APP_PATH</string>
        <string>$WORKING_DIR/server/server.py</string>
        <string>--communication-protocol</string>
        <string>$node_communication_protocol</string>
        <string>--port</string>
        <string>$current_port</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$CURRENT_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>$CURRENT_DIR</string>
        <key>ENVIRONMENT_FILE_PATH</key>
        <string>$ENVIRONMENT_FILE_PATH</string>
        <key>PATH</key>
        <string>$HOME/.local/bin:$HOME/.cargo/bin:$CURRENT_DIR/.venv/bin:$SURRREALDB_PATH:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/nodeapp_${node_communication_protocol}_${current_port}.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/nodeapp_${node_communication_protocol}_${current_port}.log</string>
</dict>
</plist>
EOF

        # Load with error checking
        echo "Loading $node_communication_protocol server service on port $current_port..." | log_with_service_name "Server" $BLUE
        if ! launchctl load $PLIST_PATH; then
            echo "Failed to load $node_communication_protocol server service. Checking permissions..." | log_with_service_name "Server" $RED
            ls -l $PLIST_PATH
            exit 1
        fi

        # Verify service is running
        sleep 2
        if launchctl list | grep -q "com.example.nodeapp.${node_communication_protocol}_${current_port}"; then
            echo "$node_communication_protocol server service loaded successfully on port $current_port." | log_with_service_name "Server" $GREEN
        else
            echo "$node_communication_protocol server service failed to load on port $current_port." | log_with_service_name "Server" $RED
            exit 1
        fi
    done

    NODE_COMMUNICATION_PORTS=$ports
}

# Function to start the Celery worker
linux_start_celery_worker() {
    echo "Starting Celery worker..." | log_with_service_name "Celery" $GREEN
    
    # Prepare fields for the service file
    USER_NAME=$(whoami)
    CURRENT_DIR=$(pwd)
    WORKING_DIR="$CURRENT_DIR"
    ENVIRONMENT_FILE_PATH="$CURRENT_DIR/.env"

    # Create celery_worker_start.sh with proper Python path
    cat > celery_worker_start.sh << EOF
#!/bin/bash
export PYTHONPATH=$CURRENT_DIR
$CURRENT_DIR/.venv/bin/python -m celery -A node.worker.main.app worker --loglevel=info
EOF
    chmod +x celery_worker_start.sh

    # Create temporary systemd service file
    cat > /tmp/celeryworker.service << EOF
[Unit]
Description=Celery Worker Service
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$WORKING_DIR
EnvironmentFile=$ENVIRONMENT_FILE_PATH
ExecStart=$CURRENT_DIR/celery_worker_start.sh
Restart=always
Environment="PYTHONPATH=$CURRENT_DIR"
Environment=PATH=$HOME/.local/bin:$HOME/.cargo/bin:${PATH}

[Install]
WantedBy=multi-user.target
EOF

    # Move the temporary service file to systemd directory
    sudo cp /tmp/celeryworker.service /etc/systemd/system/celeryworker.service
    rm /tmp/celeryworker.service

    # Reload systemd to recognize new service
    sudo systemctl daemon-reload

    # Enable and start the Celery worker service
    sudo systemctl enable celeryworker
    sudo systemctl start celeryworker

    # Check until the Celery worker is up and running by checking the logs
    echo "Waiting for Celery worker to start..." | log_with_service_name "Celery" $GREEN
    
    # Try for a maximum of 30 seconds
    for i in {1..30}; do
        if sudo journalctl -u celeryworker.service -n 100 | grep -q "celery@$(hostname) ready"; then
            echo "Celery worker started successfully!" | log_with_service_name "Celery" $GREEN
            break
        fi
        
        if [ $i -eq 30 ]; then
            echo "Celery worker failed to start within 30 seconds. Check logs for details." | log_with_service_name "Celery" $RED
            sudo journalctl -u celeryworker.service -n 100 | log_with_service_name "Celery" $RED
        fi
        
        sleep 1
    done

    sudo systemctl status celeryworker | log_with_service_name "Celery" $GREEN
}

darwin_start_celery_worker() {
    echo "Starting Celery worker..." | log_with_service_name "Celery" $GREEN
    
    # Prepare fields for the service file
    USER_NAME=$(whoami)
    CURRENT_DIR=$(pwd)
    WORKING_DIR="$CURRENT_DIR"
    ENVIRONMENT_FILE_PATH="$CURRENT_DIR/.env"
    EXECUTION_PATH="$CURRENT_DIR/celery_worker_start.sh"

    # Write celery_worker_start.sh with direct Python path instead of activation
    cat <<EOF > celery_worker_start.sh
#!/bin/bash

# Exit on error
set -e

# Log function
log_error() {
    echo "\$(date '+%Y-%m-%d %H:%M:%S') ERROR: \$1" >> /tmp/celeryworker.log
}

# Check if virtual environment Python exists
if [ ! -f "$CURRENT_DIR/.venv/bin/python" ]; then
    log_error "Python not found at $CURRENT_DIR/.venv/bin/python"
    exit 1
fi

# Set Python path
export PYTHONPATH="$CURRENT_DIR"

# Set file descriptor limits
ulimit -n 65536 || log_error "Failed to set ulimit"

# Start Celery using the Python from virtual environment
exec "$CURRENT_DIR/.venv/bin/python" -m celery -A node.worker.main.app worker \
    --loglevel=info \
    --concurrency=120 \
    --max-tasks-per-child=100 \
    --max-memory-per-child=350000
EOF

    chmod +x celery_worker_start.sh

    # Create the launchd plist
    cat <<EOF > ~/Library/LaunchAgents/com.example.celeryworker.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.example.celeryworker</string>
    <key>ProgramArguments</key>
    <array>
        <string>$EXECUTION_PATH</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$WORKING_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>$CURRENT_DIR</string>
        <key>ENVIRONMENT_FILE_PATH</key>
        <string>$ENVIRONMENT_FILE_PATH</string>
        <key>PATH</key>
        <string>$HOME/.local/bin:$HOME/.cargo/bin:$CURRENT_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>SoftResourceLimits</key>
    <dict>
        <key>NumberOfFiles</key>
        <integer>65536</integer>
    </dict>
    <key>HardResourceLimits</key>
    <dict>
        <key>NumberOfFiles</key>
        <integer>65536</integer>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/celeryworker.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/celeryworker.log</string>
</dict>
</plist>
EOF

    # Unload if exists
    launchctl unload ~/Library/LaunchAgents/com.example.celeryworker.plist 2>/dev/null || true
    
    # Load and start
    if launchctl load ~/Library/LaunchAgents/com.example.celeryworker.plist; then
        echo "Celery worker service started successfully." | log_with_service_name "Celery" $GREEN
        
        # Monitor the log file for startup success or failure
        echo "Waiting for Celery worker to initialize..." | log_with_service_name "Celery" $GREEN
        
        # Try for a maximum of 30 seconds
        for i in {1..30}; do
            if grep -q "celery@.* ready" /tmp/celeryworker.log 2>/dev/null; then
                echo "Celery worker started successfully!" | log_with_service_name "Celery" $GREEN
                break
            fi
            
            if [ $i -eq 30 ]; then
                echo "Warning: Celery worker might not have initialized properly. Check logs." | log_with_service_name "Celery" $YELLOW
                tail -n 20 /tmp/celeryworker.log | log_with_service_name "Celery" $YELLOW
            fi
            
            sleep 1
        done
        
        return 0
    else
        echo "Failed to start Celery worker service." | log_with_service_name "Celery" $RED
        return 1
    fi
}

linux_setup_local_db() {
    echo "Starting PostgreSQL setup..." | log_with_service_name "PostgreSQL" $BLUE

    POSTGRES_BIN_PATH="/usr/lib/postgresql/16/bin"
    PSQL_BIN="$POSTGRES_BIN_PATH/psql"
    POSTGRESQL_CONF="/etc/postgresql/16/main/postgresql.conf"
    PG_HBA_CONF="/etc/postgresql/16/main/pg_hba.conf"

    # Check if PostgreSQL 16 is installed
    if command -v $PSQL_BIN &> /dev/null; then
        echo "PostgreSQL 16 is already installed." | log_with_service_name "PostgreSQL" $BLUE
    else
        echo "Installing PostgreSQL 16..." | log_with_service_name "PostgreSQL" $BLUE
        
        # Add PostgreSQL 16 repository
        sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
        wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
        
        # Update package lists
        sudo apt-get update
        
        # Install PostgreSQL 16 and pgvector
        sudo apt-get install -y postgresql-16 postgresql-contrib-16
        
        echo "PostgreSQL 16 and pgvector installed successfully." | log_with_service_name "PostgreSQL" $BLUE
    fi

    # Check and install pgvector
    echo "Checking pgvector extension..." | log_with_service_name "PostgreSQL" $BLUE
    if dpkg -l | grep -q "postgresql-16-pgvector"; then
        echo "pgvector extension is already installed." | log_with_service_name "PostgreSQL" $BLUE
    else
        echo "Installing pgvector extension..." | log_with_service_name "PostgreSQL" $BLUE
        sudo apt-get update
        sudo apt-get install -y postgresql-16-pgvector
        echo "pgvector extension installed successfully." | log_with_service_name "PostgreSQL" $BLUE
    fi

    echo "Configuring PostgreSQL..." | log_with_service_name "PostgreSQL" $BLUE
    
    sudo cp $POSTGRESQL_CONF ${POSTGRESQL_CONF}.bak
    
    echo "Setting port to $LOCAL_DB_POSTGRES_PORT" | log_with_service_name "PostgreSQL" $BLUE
    sudo sed -i "s/^\s*#*\s*port\s*=.*/port = $LOCAL_DB_POSTGRES_PORT/" $POSTGRESQL_CONF
    
    echo "Setting listen_addresses to '*'" | log_with_service_name "PostgreSQL" $BLUE
    sudo sed -i "s/^\s*#*\s*listen_addresses\s*=.*/listen_addresses = '*'/" $POSTGRESQL_CONF
    
    echo "Updating pg_hba.conf" | log_with_service_name "PostgreSQL" $BLUE
    if ! sudo grep -q "0.0.0.0/0" $PG_HBA_CONF; then
        echo "host    all             all             0.0.0.0/0               md5" | sudo tee -a $PG_HBA_CONF > /dev/null
    fi

    sudo sed -i "s/^local\s\+all\s\+all\s\+\(peer\|ident\)/local   all             all                                     md5/" $PG_HBA_CONF

    echo "PostgreSQL configured to listen on port $LOCAL_DB_POSTGRES_PORT" | log_with_service_name "PostgreSQL" $BLUE

    echo "Restarting PostgreSQL service..." | log_with_service_name "PostgreSQL" $BLUE
    sudo systemctl restart postgresql
    sleep 5

    echo "Verifying PostgreSQL is running..." | log_with_service_name "PostgreSQL" $BLUE
    if sudo -u postgres $PSQL_BIN -p $LOCAL_DB_POSTGRES_PORT -c "SELECT 1" >/dev/null 2>&1; then
        echo "PostgreSQL service started successfully on port $LOCAL_DB_POSTGRES_PORT." | log_with_service_name "PostgreSQL" $BLUE
    else
        echo "Failed to connect to PostgreSQL on port $LOCAL_DB_POSTGRES_PORT." | log_with_service_name "PostgreSQL" $BLUE
        exit 1
    fi

    echo "Creating database and user..." | log_with_service_name "PostgreSQL" $BLUE
    
    # Create user
    sudo -u postgres $PSQL_BIN -p $LOCAL_DB_POSTGRES_PORT <<EOF
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$LOCAL_DB_POSTGRES_USERNAME') THEN
            CREATE USER $LOCAL_DB_POSTGRES_USERNAME WITH ENCRYPTED PASSWORD '$LOCAL_DB_POSTGRES_PASSWORD';
        END IF;
    END
    \$\$;
EOF

    # Create database
    sudo -u postgres $PSQL_BIN -p $LOCAL_DB_POSTGRES_PORT -c "CREATE DATABASE $LOCAL_DB_POSTGRES_NAME WITH OWNER $LOCAL_DB_POSTGRES_USERNAME;"

    # Set permissions
    sudo -u postgres $PSQL_BIN -p $LOCAL_DB_POSTGRES_PORT -d $LOCAL_DB_POSTGRES_NAME <<EOF
    GRANT ALL PRIVILEGES ON DATABASE $LOCAL_DB_POSTGRES_NAME TO $LOCAL_DB_POSTGRES_USERNAME;
    GRANT ALL ON SCHEMA public TO $LOCAL_DB_POSTGRES_USERNAME;
    ALTER SCHEMA public OWNER TO $LOCAL_DB_POSTGRES_USERNAME;
    GRANT ALL ON ALL TABLES IN SCHEMA public TO $LOCAL_DB_POSTGRES_USERNAME;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $LOCAL_DB_POSTGRES_USERNAME;
EOF

    # Create pgvector extension
    echo "Creating pgvector extension..." | log_with_service_name "PostgreSQL" $BLUE
    sudo -u postgres $PSQL_BIN -p $LOCAL_DB_POSTGRES_PORT -d $LOCAL_DB_POSTGRES_NAME -c "CREATE EXTENSION IF NOT EXISTS vector;"
    
    echo "Database and user setup completed successfully" | log_with_service_name "PostgreSQL" $BLUE
}

linux_start_local_db() {
    PWD=$(pwd)
    POSTGRES_BIN_PATH="/usr/lib/postgresql/16/bin"
    PSQL_BIN="$POSTGRES_BIN_PATH/psql"

    echo "Running Local DB..." | log_with_service_name "LocalDBPostgres" $RED
    
    INIT_PYTHON_PATH="$PWD/node/storage/db/init_db.py"
    chmod +x "$INIT_PYTHON_PATH"

    echo "Running init_db.py script..." | log_with_service_name "LocalDBPostgres" $RED
    uv run python "$INIT_PYTHON_PATH" 2>&1
    PYTHON_EXIT_STATUS=$?

    if [ $PYTHON_EXIT_STATUS -ne 0 ]; then
        echo "Local DB initialization failed. Python script exited with status $PYTHON_EXIT_STATUS." | log_with_service_name "LocalDBPostgres" $RED
        exit 1
    fi

    echo "Checking if PostgreSQL is running..." | log_with_service_name "LocalDBPostgres" $RED
    if sudo -u postgres $PSQL_BIN -p $LOCAL_DB_POSTGRES_PORT -c "SELECT 1" >/dev/null 2>&1; then
        echo "Local DB (PostgreSQL) is running successfully." | log_with_service_name "LocalDBPostgres" $RED
    else
        echo "Local DB (PostgreSQL) failed to start. Please check the logs." | log_with_service_name "LocalDBPostgres" $RED
        exit 1
    fi
}

darwin_setup_local_db() {
    echo "Starting PostgreSQL 16 setup..." | log_with_service_name "PostgreSQL" $BLUE

    # uninstall PostgreSQL 16
    brew uninstall postgresql@16

    # Install PostgreSQL 17
    if ! brew list postgresql@17 &>/dev/null; then
        echo "Installing PostgreSQL 17..." | log_with_service_name "PostgreSQL" $BLUE
        brew install postgresql@17
    else
        echo "PostgreSQL 17 is already installed." | log_with_service_name "PostgreSQL" $BLUE
    fi

    # Install pgvector
    if ! brew list pgvector &>/dev/null; then
        echo "Installing pgvector..." | log_with_service_name "PostgreSQL" $BLUE
        brew install pgvector
        brew link pgvector
    fi

    # Link PostgreSQL 17
    brew link --force postgresql@17
    export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"

    POSTGRESQL_CONF="/opt/homebrew/var/postgresql@17/postgresql.conf"
    PG_HBA_CONF="/opt/homebrew/var/postgresql@17/pg_hba.conf"

    # Stop PostgreSQL
    echo "Stopping PostgreSQL services..." | log_with_service_name "PostgreSQL" $BLUE
    brew services stop postgresql@17
    sleep 3

    # Backup and update configuration
    if [ -f "$POSTGRESQL_CONF" ]; then
        cp "$POSTGRESQL_CONF" "${POSTGRESQL_CONF}.bak"
        sed -i '' "s/^#port = .*/port = $LOCAL_DB_POSTGRES_PORT/" "$POSTGRESQL_CONF"
        sed -i '' "s/^#listen_addresses = .*/listen_addresses = '*'/" "$POSTGRESQL_CONF"
        sed -i '' "s/^#max_connections = .*/max_connections = 2000/" "$POSTGRESQL_CONF"
    fi

    if [ -f "$PG_HBA_CONF" ]; then
        cp "$PG_HBA_CONF" "${PG_HBA_CONF}.bak"
        echo "host    all             all             0.0.0.0/0               md5" >> "$PG_HBA_CONF"
    fi

    # Link pgvector files
    PGVECTOR_LIB="/opt/homebrew/opt/pgvector/lib/postgresql"
    PG17_LIB="/opt/homebrew/opt/postgresql@17/lib/postgresql"
    PGVECTOR_EXT="/opt/homebrew/opt/pgvector/share/postgresql/extension"
    PG17_EXT="/opt/homebrew/opt/postgresql@17/share/postgresql@17/extension"

    # Create links for pgvector
    mkdir -p "$PG17_LIB"
    mkdir -p "$PG17_EXT"
    ln -sf "$PGVECTOR_LIB/vector.so" "$PG17_LIB/"
    ln -sf "$PGVECTOR_EXT/vector.control" "$PG17_EXT/"
    ln -sf "$PGVECTOR_EXT/vector--*.sql" "$PG17_EXT/"

    # Start PostgreSQL
    echo "Starting PostgreSQL..." | log_with_service_name "PostgreSQL" $BLUE
    brew services start postgresql@17
    sleep 5

    # Wait for PostgreSQL to be ready
    max_attempts=10
    attempt=1
    while [ $attempt -le $max_attempts ]; do
        if pg_isready -p "$LOCAL_DB_POSTGRES_PORT"; then
            echo "PostgreSQL is ready." | log_with_service_name "PostgreSQL" $BLUE
            break
        fi
        echo "Waiting for PostgreSQL to start (attempt $attempt/$max_attempts)..." | log_with_service_name "PostgreSQL" $BLUE
        sleep 2
        attempt=$((attempt + 1))
    done

    if [ $attempt -gt $max_attempts ]; then
        echo "Failed to start PostgreSQL. Check logs at /opt/homebrew/var/log/postgresql@17.log" | log_with_service_name "PostgreSQL" $RED
        exit 1
    fi

    # Create user and database
    echo "Creating database user and database..." | log_with_service_name "PostgreSQL" $BLUE
    psql postgres -p "$LOCAL_DB_POSTGRES_PORT" <<EOF
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$LOCAL_DB_POSTGRES_USERNAME') THEN
            CREATE USER $LOCAL_DB_POSTGRES_USERNAME WITH PASSWORD '$LOCAL_DB_POSTGRES_PASSWORD';
        END IF;
    END \$\$;
    CREATE DATABASE $LOCAL_DB_POSTGRES_NAME WITH OWNER $LOCAL_DB_POSTGRES_USERNAME;
EOF

    # Set permissions
    psql -d "$LOCAL_DB_POSTGRES_NAME" -p "$LOCAL_DB_POSTGRES_PORT" <<EOF
    GRANT ALL PRIVILEGES ON DATABASE $LOCAL_DB_POSTGRES_NAME TO $LOCAL_DB_POSTGRES_USERNAME;
    GRANT ALL ON SCHEMA public TO $LOCAL_DB_POSTGRES_USERNAME;
    ALTER SCHEMA public OWNER TO $LOCAL_DB_POSTGRES_USERNAME;
EOF

    # Create pgvector extension
    echo "Creating pgvector extension..." | log_with_service_name "PostgreSQL" $BLUE
    psql -d "$LOCAL_DB_POSTGRES_NAME" -p "$LOCAL_DB_POSTGRES_PORT" -c "CREATE EXTENSION IF NOT EXISTS vector;"
    
    if [ $? -eq 0 ]; then
        echo "PostgreSQL setup completed successfully." | log_with_service_name "PostgreSQL" $GREEN
    else
        echo "Failed to create vector extension. Please check PostgreSQL logs." | log_with_service_name "PostgreSQL" $RED
        exit 1
    fi
}

darwin_start_local_db() {
    PWD=$(pwd)

    echo "Running Local DB..." | log_with_service_name "LocalDBPostgres" $RED
    
    INIT_PYTHON_PATH="$PWD/node/storage/db/init_db.py"
    chmod +x "$INIT_PYTHON_PATH"

    echo "Running init_db.py script..." | log_with_service_name "LocalDBPostgres" $RED
    uv run python "$INIT_PYTHON_PATH" 2>&1
    PYTHON_EXIT_STATUS=$?

    if [ $PYTHON_EXIT_STATUS -ne 0 ]; then
        echo "Local DB initialization failed. Python script exited with status $PYTHON_EXIT_STATUS." | log_with_service_name "LocalDBPostgres" $RED
        exit 1
    fi

    echo "Checking if PostgreSQL 16 is running..." | log_with_service_name "LocalDBPostgres" $RED
    if psql -p $LOCAL_DB_POSTGRES_PORT -c "SELECT 1" postgres >/dev/null 2>&1; then
        echo "Local DB (PostgreSQL 16) is running successfully." | log_with_service_name "LocalDBPostgres" $RED
    else
        echo "Local DB (PostgreSQL 16) failed to start. Please check the logs." | log_with_service_name "LocalDBPostgres" $RED
        exit 1
    fi
}

linux_start_litellm() {
    echo "Starting LiteLLM proxy server..." | log_with_service_name "LiteLLM" $BLUE
    
    # Get absolute paths
    CURRENT_DIR=$(pwd)
    PROJECT_DIR="$CURRENT_DIR/node/inference/litellm"
    VENV_PATH="$PROJECT_DIR/.venv/bin"
    
    # Create and set up virtual environment for LiteLLM
    echo "Setting up LiteLLM environment..." | log_with_service_name "LiteLLM" $BLUE
    cd $PROJECT_DIR
    
    # Create a separate virtual environment for LiteLLM
    uv venv
    
    # Install pip in the LiteLLM virtual environment
    echo "Installing pip in the virtual environment..." | log_with_service_name "LiteLLM" $BLUE
    curl -sSL https://bootstrap.pypa.io/get-pip.py | $VENV_PATH/python -
    
    # Install LiteLLM from the pyproject.toml
    echo "Installing LiteLLM dependencies from pyproject.toml..." | log_with_service_name "LiteLLM" $BLUE
    $VENV_PATH/pip install -e .
    
    # Generate LiteLLM config using main project's venv
    echo "Generating LiteLLM config..." | log_with_service_name "LiteLLM" $BLUE
    cd $CURRENT_DIR
    PYTHONPATH=$CURRENT_DIR $CURRENT_DIR/.venv/bin/python $PROJECT_DIR/generate_litellm_config.py
    cd $PROJECT_DIR
    
    # Create startup script for LiteLLM - using the litellm command directly
    cat > $PROJECT_DIR/start_litellm.sh << EOF
#!/bin/bash
export PYTHONPATH=$PROJECT_DIR
exec $VENV_PATH/litellm --config $PROJECT_DIR/litellm_config.yml
EOF
    
    chmod +x $PROJECT_DIR/start_litellm.sh
    
    # Create systemd service file
    cat > /tmp/litellm.service << EOF
[Unit]
Description=LiteLLM Proxy Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$VENV_PATH:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=$PROJECT_DIR
EnvironmentFile=$CURRENT_DIR/.env
ExecStart=$PROJECT_DIR/start_litellm.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    # Move service file and start service
    sudo mv /tmp/litellm.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable litellm
    sudo systemctl start litellm

    # Check service status with improved error handling
    echo "Checking LiteLLM service status..." | log_with_service_name "LiteLLM" $BLUE
    
    # Check several times with increasing sleep intervals
    for attempt in 1 2 3; do
        sleep $((attempt * 2))
        if sudo systemctl is-active --quiet litellm; then
            echo "LiteLLM proxy server started successfully on attempt $attempt." | log_with_service_name "LiteLLM" $GREEN
            return 0
        else
            echo "LiteLLM start attempt $attempt failed, waiting longer..." | log_with_service_name "LiteLLM" $YELLOW
        fi
    done
    
    # If we reach here, all attempts failed
    echo "Failed to start LiteLLM proxy server after multiple attempts. Checking logs..." | log_with_service_name "LiteLLM" $RED
    sudo journalctl -u litellm --no-pager -n 50
    exit 1
}

darwin_start_litellm() {
    echo "Starting LiteLLM proxy server..." | log_with_service_name "LiteLLM" $BLUE
    
    # Get absolute paths
    CURRENT_DIR=$(pwd)
    PROJECT_DIR="$CURRENT_DIR/node/inference/litellm"
    VENV_PATH="$PROJECT_DIR/.venv/bin"
    
    # Create and set up virtual environment for LiteLLM
    echo "Setting up LiteLLM environment..." | log_with_service_name "LiteLLM" $BLUE
    cd $PROJECT_DIR
    
    # Create a separate virtual environment for LiteLLM
    uv venv
    
    # Install pip in the LiteLLM virtual environment
    echo "Installing pip in the virtual environment..." | log_with_service_name "LiteLLM" $BLUE
    curl -sSL https://bootstrap.pypa.io/get-pip.py | $VENV_PATH/python -
    
    # Install LiteLLM from the pyproject.toml
    echo "Installing LiteLLM dependencies from pyproject.toml..." | log_with_service_name "LiteLLM" $BLUE
    $VENV_PATH/pip install -e .
    
    # Generate LiteLLM config using main project's venv
    echo "Generating LiteLLM config..." | log_with_service_name "LiteLLM" $BLUE
    cd $CURRENT_DIR
    PYTHONPATH=$CURRENT_DIR $CURRENT_DIR/.venv/bin/python $PROJECT_DIR/generate_litellm_config.py
    cd $PROJECT_DIR
    
    # Create startup script for LiteLLM - using the litellm command directly
    cat > $PROJECT_DIR/start_litellm.sh << EOF
#!/bin/bash
export PYTHONPATH=$PROJECT_DIR
exec $VENV_PATH/litellm --config $PROJECT_DIR/litellm_config.yml
EOF
    
    chmod +x $PROJECT_DIR/start_litellm.sh

    # Create launchd plist file
    cat > ~/Library/LaunchAgents/com.litellm.proxy.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.litellm.proxy</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PROJECT_DIR/start_litellm.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$VENV_PATH:/usr/local/bin:/usr/bin:/bin</string>
        <key>PYTHONPATH</key>
        <string>$PROJECT_DIR</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/litellm.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/litellm.log</string>
</dict>
</plist>
EOF

    # Load and start service
    launchctl unload ~/Library/LaunchAgents/com.litellm.proxy.plist 2>/dev/null || true
    launchctl load ~/Library/LaunchAgents/com.litellm.proxy.plist

    # Check if service is running with improved error handling
    echo "Checking if LiteLLM service is running..." | log_with_service_name "LiteLLM" $BLUE
    
    # Try multiple times with increasing wait periods
    for attempt in 1 2 3; do
        sleep $((attempt * 2))
        if pgrep -f "litellm.*config" > /dev/null; then
            echo "LiteLLM proxy server started successfully on attempt $attempt." | log_with_service_name "LiteLLM" $GREEN
            return 0
        else
            echo "LiteLLM start attempt $attempt failed, waiting longer..." | log_with_service_name "LiteLLM" $YELLOW
        fi
    done
    
    # If we reach here, all attempts failed
    echo "Failed to start LiteLLM proxy server after multiple attempts. Check logs:" | log_with_service_name "LiteLLM" $RED
    tail -n 50 /tmp/litellm.log
    exit 1
}

startup_summary() {
    echo "🔍 Checking status of all services..." | log_with_service_name "Summary" $BLUE
    
    # Use simple arrays with consistent indexing instead of associative arrays
    services=()
    statuses=()
    logs=()
    
    # Check PostgreSQL
    services+=("PostgreSQL")
    if [ "$os" = "Darwin" ]; then
        if psql -p $LOCAL_DB_POSTGRES_PORT -c "SELECT 1" postgres >/dev/null 2>&1; then
            statuses+=("✅")
            logs+=("")
        else
            statuses+=("❌")
            logs+=("$(tail -n 20 /opt/homebrew/var/log/postgresql@16.log)")
        fi
    else
        if sudo -u postgres psql -p $LOCAL_DB_POSTGRES_PORT -c "SELECT 1" >/dev/null 2>&1; then
            statuses+=("✅")
            logs+=("")
        else
            statuses+=("❌")
            logs+=("$(sudo journalctl -u postgresql -n 20)")
        fi
    fi

    # Check Local Hub if enabled
    if [ "$LOCAL_HUB" == "true" ]; then
        services+=("Hub_DB")
        if curl -s http://localhost:$HUB_DB_SURREAL_PORT/health > /dev/null; then
            statuses+=("✅")
            logs+=("")
        else
            statuses+=("❌")
            logs+=("$(tail -n 20 /tmp/hub_db.log 2>/dev/null || echo 'Log file not found')")
        fi
    fi

    # Check Celery
    services+=("Celery")
    if [ "$os" = "Darwin" ]; then
        if pgrep -f "celery.*worker" > /dev/null; then
            statuses+=("✅")
            logs+=("")
        else
            statuses+=("❌")
            logs+=("$(tail -n 20 /tmp/celeryworker.log 2>/dev/null || echo 'Log file not found')")
        fi
    else
        if systemctl is-active --quiet celeryworker; then
            statuses+=("✅")
            logs+=("")
        else
            statuses+=("❌")
            logs+=("$(sudo journalctl -u celeryworker -n 20)")
        fi
    fi

    # Wait before checking HTTP and WS servers
    echo "Waiting for HTTP and WebSocket servers to fully initialize..." | log_with_service_name "Summary" $BLUE
    sleep 8

    # Check Node HTTP Server
    services+=("HTTP_Server")
    if [ "$os" = "Darwin" ]; then
        if curl -s http://localhost:7001/health > /dev/null; then
            statuses+=("✅")
            logs+=("")
        else
            statuses+=("❌")
            logs+=("$(tail -n 20 /tmp/nodeapp_http.log 2>/dev/null || echo 'Log file not found')")
        fi
    else
        if curl -s http://localhost:7001/health > /dev/null; then
            statuses+=("✅")
            logs+=("")
        else
            statuses+=("❌")
            logs+=("$(sudo journalctl -u nodeapp_http -n 20)")
        fi
    fi

    # Check Secondary Servers (WS or gRPC)
    for port in $(echo $NODE_COMMUNICATION_PORTS | tr ',' ' '); do
        if [ "$port" != "7001" ]; then  # Skip HTTP port
            services+=("$(echo $NODE_COMMUNICATION_PROTOCOL | tr '[:lower:]' '[:upper:]')_Server_${port}")
            
            # Health check based on server type
            if [ "${NODE_COMMUNICATION_PROTOCOL}" = "ws" -o "${NODE_COMMUNICATION_PROTOCOL}" = "wss" ]; then
                # WebSocket health check using /health endpoint
                if curl -s http://localhost:$port/health > /dev/null; then
                    statuses+=("✅")
                    logs+=("")
                else
                    if [ "$os" = "Darwin" ]; then
                        logs+=("$(tail -n 20 /tmp/nodeapp_ws_$port.log 2>/dev/null || echo 'Log file not found')")
                    else
                        logs+=("$(sudo journalctl -u nodeapp_ws_$port -n 20)")
                    fi
                    statuses+=("❌")
                fi
            else  # grpc
                # gRPC health check using is_alive
                if python3 -c "
import grpc
import asyncio
import sys
from node.server import grpc_server_pb2_grpc, grpc_server_pb2
from google.protobuf.empty_pb2 import Empty

async def check_health():
    async with grpc.aio.insecure_channel('localhost:$port') as channel:
        stub = grpc_server_pb2_grpc.GrpcServerStub(channel)
        try:
            response = await stub.is_alive(Empty())
            return response.ok
        except Exception as e:
            return False

if asyncio.run(check_health()):
    sys.exit(0)
else:
    sys.exit(1)
" > /dev/null 2>&1; then
                    statuses+=("✅")
                    logs+=("")
                else
                    if [ "$os" = "Darwin" ]; then
                        logs+=("$(tail -n 20 /tmp/nodeapp_grpc_$port.log 2>/dev/null || echo 'Log file not found')")
                    else
                        logs+=("$(sudo journalctl -u nodeapp_grpc_$port -n 20)")
                    fi
                    statuses+=("❌")
                fi
            fi
        fi
    done

    # Check LiteLLM
    services+=("LiteLLM")
    sleep 2
    if curl -s http://localhost:4000/health > /dev/null; then
        statuses+=("✅")
        logs+=("")
    else
        statuses+=("❌")
        if [ "$os" = "Darwin" ]; then
            logs+=("$(tail -n 20 /tmp/litellm.log 2>/dev/null || echo 'Log file not found')")
        else
            logs+=("$(sudo journalctl -u litellm -n 20)")
        fi
    fi

    # Print formatted summary
    echo -e "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | log_with_service_name "Summary" $BLUE
    echo -e "           🔍 SERVICE STATUS              " | log_with_service_name "Summary" $BLUE
    echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | log_with_service_name "Summary" $BLUE
    echo -e "                                         " | log_with_service_name "Summary" $BLUE

    # Print status for each service
    local failed_services=0
    for i in "${!services[@]}"; do
        service_name="${services[$i]}"
        service_name="${service_name//_/ }"  # Replace underscores with spaces
        printf "  %-20s %s\n" "$service_name" "${statuses[$i]}" | log_with_service_name "Summary" $BLUE
        if [ "${statuses[$i]}" == "❌" ]; then
            failed_services=$((failed_services + 1))
        fi
    done

    echo -e "                                         " | log_with_service_name "Summary" $BLUE
    echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" | log_with_service_name "Summary" $BLUE

    # Print logs for failed services
    if [ $failed_services -gt 0 ]; then
        echo -e "\n📋 Error Logs for Failed Services:" | log_with_service_name "Summary" $RED
        for i in "${!services[@]}"; do
            if [ "${statuses[$i]}" == "❌" ]; then
                service_name="${services[$i]}"
                service_name="${service_name//_/ }"
                echo -e "\n🔴 ${service_name} Logs:" | log_with_service_name "Summary" $RED
                echo "${logs[$i]}" | log_with_service_name "Summary" $RED
            fi
        done
        exit 1
    else
        echo -e "\n✨ All services started successfully!" | log_with_service_name "Summary" $GREEN
    fi
}   

print_logo(){
    printf """
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
            ▀█  █ █ █ █ ▌▀                                                 \e]8;;https://www.naptha.ai\e\\www.naptha.ai\e]8;;\e\\
              ▀▀█ █ ██▀▀                                                          
    """
    echo -e "\n"
    printf "✨ ✨ ✨ Launching... While you wait, please star our repo \e]8;;https://github.com/NapthaAI/node\e\\https://github.com/NapthaAI/node\e]8;;\e\\ ✨ ✨ ✨"
    echo -e "\n"
}

check_huggingface_env() {
    # Check HUGGINGFACE_TOKEN
    hf_token=$(grep '^HUGGINGFACE_TOKEN=' .env | cut -d'=' -f2)
    if [ -z "$hf_token" ]; then
        read -p "HUGGINGFACE_TOKEN is not set. Please enter your HUGGINGFACE_TOKEN: " hf_token
        if [ -z "$hf_token" ]; then
            echo "HUGGINGFACE_TOKEN cannot be empty." | log_with_service_name "Docker" "$RED"
            exit 1
        fi
        if grep -q '^HUGGINGFACE_TOKEN=' .env; then
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s/^HUGGINGFACE_TOKEN=.*/HUGGINGFACE_TOKEN=$hf_token/" .env
            else
                sed -i "s/^HUGGINGFACE_TOKEN=.*/HUGGINGFACE_TOKEN=$hf_token/" .env
            fi
        else
            echo "HUGGINGFACE_TOKEN=$hf_token" >> .env
        fi
        echo "HUGGINGFACE_TOKEN set." | log_with_service_name "Docker" "$BLUE"
    else
        echo "HUGGINGFACE_TOKEN already set." | log_with_service_name "Docker" "$BLUE"
    fi

    # Check HF_HOME
    hf_home=$(grep '^HF_HOME=' .env | cut -d'=' -f2)
    # If HF_HOME is empty or contains the placeholder "<youruser>", it's not valid
    if [ -z "$hf_home" ] || [[ "$hf_home" == *"<youruser>"* ]]; then
        echo "HF_HOME is not set to a valid directory." | log_with_service_name "Docker" "$RED"
        read -p "Please enter a valid directory for HF_HOME (e.g., \$HOME/.cache/huggingface): " hf_home_input
        if [ -z "$hf_home_input" ]; then
            echo "HF_HOME cannot be empty." | log_with_service_name "Docker" "$RED"
            exit 1
        fi
        hf_home="$hf_home_input"
        if ! [ -d "$hf_home" ]; then
            echo "Directory $hf_home does not exist. Creating it..." | log_with_service_name "Docker" "$BLUE"
            mkdir -p "$hf_home"
        fi
        if grep -q '^HF_HOME=' .env; then
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s|^HF_HOME=.*|HF_HOME=$hf_home|" .env
            else
                sed -i "s|^HF_HOME=.*|HF_HOME=$hf_home|" .env
            fi
        else
            echo "HF_HOME=$hf_home" >> .env
        fi
        echo "HF_HOME set to $hf_home." | log_with_service_name "Docker" "$BLUE"
    else
        if ! [ -d "$hf_home" ]; then
            echo "HF_HOME directory $hf_home does not exist. Creating it..." | log_with_service_name "Docker" "$BLUE"
            mkdir -p "$hf_home"
        fi
        echo "HF_HOME already set and valid: $hf_home." | log_with_service_name "Docker" "$BLUE"
    fi
}

check_and_set_private_key_docker() {
    # First check if ecdsa is installed and install if needed
    if ! python -c "import ecdsa" 2>/dev/null; then
        echo "ecdsa package not found. Installing..."
        pip install ecdsa
        if [ $? -ne 0 ]; then
            echo "Failed to install ecdsa package. Please check your Python/pip installation."
            return 1
        fi
        echo "ecdsa package installed successfully."
    fi
    source .env
    pem_file="${HUB_USERNAME}.pem"
    # If the PEM file exists, read its content; else generate a new key and save it.
    if [ -f "$pem_file" ]; then
        echo "PEM file $pem_file found."
        generated_key=$(tr -d '\n' < "$pem_file")
    else
        echo "PEM file $pem_file not found. Generating new key..."
        generated_key=$(python -c "from ecdsa import SigningKey, SECP256k1; print(SigningKey.generate(curve=SECP256k1).to_string().hex())")
        echo "$generated_key" > "$pem_file"
        echo "New key generated and saved to $pem_file."
    fi

    # Update the .env file: set PRIVATE_KEY to point to the PEM file path.
    if grep -q '^PRIVATE_KEY=' .env; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s/^PRIVATE_KEY=.*/PRIVATE_KEY=$pem_file/" .env
        else
            sed -i "s/^PRIVATE_KEY=.*/PRIVATE_KEY=$pem_file/" .env
        fi
        echo "Updated PRIVATE_KEY in .env to $pem_file."
    else
        echo "PRIVATE_KEY=$pem_file" >> .env
        echo "Added PRIVATE_KEY to .env as $pem_file."
    fi
}

check_and_set_hub_credentials() {
    # Ensure HUB_USERNAME is set, otherwise prompt and update .env
    hub_username=$(grep '^HUB_USERNAME=' .env | cut -d'=' -f2)
    if [ -z "$hub_username" ]; then
        read -p "HUB_USERNAME is not set. Please enter HUB_USERNAME: " hub_username
        if [ -z "$hub_username" ]; then
            echo "HUB_USERNAME cannot be empty." | log_with_service_name "Docker" "$RED"
            exit 1
        fi
        if grep -q '^HUB_USERNAME=' .env; then
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s/^HUB_USERNAME=.*/HUB_USERNAME=$hub_username/" .env
            else
                sed -i "s/^HUB_USERNAME=.*/HUB_USERNAME=$hub_username/" .env
            fi
        else
            echo "HUB_USERNAME=$hub_username" >> .env
        fi
        echo "HUB_USERNAME set to $hub_username." | log_with_service_name "Docker" "$BLUE"
    else
        echo "HUB_USERNAME already set to $hub_username." | log_with_service_name "Docker" "$BLUE"
    fi

    # Ensure HUB_PASSWORD is set, otherwise prompt and update .env
    hub_password=$(grep '^HUB_PASSWORD=' .env | cut -d'=' -f2)
    if [ -z "$hub_password" ]; then
        read -p "HUB_PASSWORD is not set. Please enter HUB_PASSWORD: " hub_password
        if [ -z "$hub_password" ]; then
            echo "HUB_PASSWORD cannot be empty." | log_with_service_name "Docker" "$RED"
            exit 1
        fi
        if grep -q '^HUB_PASSWORD=' .env; then
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s/^HUB_PASSWORD=.*/HUB_PASSWORD=$hub_password/" .env
            else
                sed -i "s/^HUB_PASSWORD=.*/HUB_PASSWORD=$hub_password/" .env
            fi
        else
            echo "HUB_PASSWORD=$hub_password" >> .env
        fi
        echo "HUB_PASSWORD set." | log_with_service_name "Docker" "$BLUE"
    else
        echo "HUB_PASSWORD already set." | log_with_service_name "Docker" "$BLUE"
    fi
}

launch_docker() {
    echo "Launching Docker..." | log_with_service_name "Docker" "$BLUE"
    check_and_set_hub_credentials
    check_and_set_private_key_docker

    COMPOSE_DIR="node/compose-files"
    COMPOSE_FILES=""

    # Read and export environment variables from .env
    if [ -f .env ]; then
        echo "Loading environment variables from .env file..." | log_with_service_name "LiteLLM" "$BLUE"
        
        # Use a simpler env var loading approach
        set -a
        source .env
        set +a
    fi

    # Check if development mode is enabled
    if [[ "$DOCKER_DEV_MODE" == "true" ]]; then
        echo "Running in development mode with Dockerfile-node-dev..." | log_with_service_name "Docker" "$BLUE"
        COMPOSE_BASE_FILE="docker-compose.development.yml"
    else
        echo "Running in production mode with napthaai/node:latest image..." | log_with_service_name "Docker" "$BLUE"
        COMPOSE_BASE_FILE="docker-compose.yml"
    fi

    if [[ "$LLM_BACKEND" == "ollama" ]]; then
        python node/inference/litellm/generate_litellm_config.py
        COMPOSE_FILES+=" -f ${COMPOSE_DIR}/ollama.yml"
    elif [[ "$LLM_BACKEND" == "vllm" ]]; then
        check_huggingface_env
        echo "Generating Litellm Config..." | log_with_service_name "Docker" "$BLUE"
        python node/inference/litellm/generate_litellm_config.py
        GPU_ASSIGNMENTS=$(cat gpu_assignments.txt)
        echo "GPU Assignments: $GPU_ASSIGNMENTS" | log_with_service_name "Docker" "$BLUE"
        
        IFS=',' read -ra MODEL_ARRAY <<< "${VLLM_MODELS//$'\\\n'}"
        for model in "${MODEL_ARRAY[@]}"
        do
            model=$(echo "$model" | tr -d '[:space:]')
            model_name=${model##*/}
            echo "Model Name: $model_name" | log_with_service_name "Docker" "$BLUE"
            if [ -f "${COMPOSE_DIR}/vllm-models/${model_name}.yml" ]; then
                COMPOSE_FILES+=" -f ${COMPOSE_DIR}/vllm-models/${model_name}.yml"
            else
                echo "Warning: Compose file not found for ${model_name}" | log_with_service_name "Docker" "$YELLOW"
            fi
        done
    else
        echo "Invalid LLM backend: $LLM_BACKEND" | log_with_service_name "LiteLLM" "$RED"
        exit 1
    fi

    if [[ "$LOCAL_HUB" == "true" ]]; then
        COMPOSE_FILES+=" -f ${COMPOSE_DIR}/hub.yml"
    fi

    docker network inspect naptha-network >/dev/null 2>&1 || docker network create naptha-network

    # Store compose command base for reuse
    if [[ "$LLM_BACKEND" == "vllm" ]]; then
        # Get environment variables from .env as a string
        ENV_VARS=$(cat .env | grep -v '^#' | xargs)
        
        # Start the containers with environment variables
        echo "Starting containers in VLLM mode..." | log_with_service_name "Docker" "$BLUE"
        env $ENV_VARS $GPU_ASSIGNMENTS docker compose -f $COMPOSE_BASE_FILE $COMPOSE_FILES up -d
        
        # Create docker-ctl.sh script for VLLM mode
        cat > docker-ctl.sh << 'EOF'
#!/bin/bash
case "$1" in
    "down")
        ENV_VARS=$(cat .env | grep -v '^#' | xargs)
        env $ENV_VARS $(cat gpu_assignments.txt) docker compose -f COMPOSE_BASE_FILE COMPOSE_FILES down
        ;;
    "logs")
        ENV_VARS=$(cat .env | grep -v '^#' | xargs)
        env $ENV_VARS $(cat gpu_assignments.txt) docker compose -f COMPOSE_BASE_FILE COMPOSE_FILES logs -f
        ;;
    *)
        echo "Usage: ./docker-ctl.sh [down|logs]"
        exit 1
        ;;
esac
EOF
        # Replace placeholders with actual values
        sed -i "s|COMPOSE_BASE_FILE|$COMPOSE_BASE_FILE|g" docker-ctl.sh
        sed -i "s|COMPOSE_FILES|$COMPOSE_FILES|g" docker-ctl.sh
    else
        echo "Starting containers in Ollama mode..." | log_with_service_name "Docker" "$BLUE"
        docker compose -f $COMPOSE_BASE_FILE $COMPOSE_FILES up -d
        
        # Create docker-ctl.sh script for Ollama mode
        cat > docker-ctl.sh << EOF
#!/bin/bash
case "\$1" in
    "down")
        docker compose -f $COMPOSE_BASE_FILE $COMPOSE_FILES down
        ;;
    "logs")
        docker compose -f $COMPOSE_BASE_FILE $COMPOSE_FILES logs -f
        ;;
    *)
        echo "Usage: ./docker-ctl.sh [down|logs]"
        exit 1
        ;;
esac
EOF
    fi
    
    chmod +x docker-ctl.sh
    
    # Clean up temp files
    if [[ -f "gpu_assignments.txt" ]]; then
        rm -f gpu_assignments.txt
    fi
}

main() {
    print_logo
    load_env_file
    os="$(uname)"
    if [ "$LAUNCH_DOCKER" = "true" ]; then
        launch_docker
    else
        # use systemd/launchd
        if [ "$os" = "Darwin" ]; then
            install_python312
            darwin_install_miniforge
            # darwin_clean_node
            darwin_setup_local_db
            setup_uv
            install_surrealdb
            check_and_copy_env
            darwin_install_ollama
            darwin_install_docker
            darwin_start_rabbitmq
            check_and_set_private_key
            start_hub_surrealdb
            darwin_start_local_db
            darwin_start_servers
            darwin_start_celery_worker
            darwin_start_litellm
            startup_summary
        else
            install_python312
            linux_install_miniforge
            # linux_clean_node
            linux_setup_local_db
            setup_uv
            install_surrealdb
            check_and_copy_env
            linux_install_ollama
            linux_install_docker
            linux_start_rabbitmq
            check_and_set_private_key
            start_hub_surrealdb
            linux_start_local_db
            linux_start_servers
            linux_start_celery_worker
            linux_start_litellm
            startup_summary
        fi
    fi

    echo "Setup complete. Applications are running." | log_with_service_name "System" $GREEN

}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main
fi

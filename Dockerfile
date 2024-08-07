# Use Miniforge as the base image
FROM condaforge/miniforge3:latest

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV RABBITMQ_LOG_BASE /var/log/rabbitmq

# Set work directory
WORKDIR /app

# Install system dependencies, build tools, and networking utilities
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    lsb-release \
    supervisor \
    gcc \
    python3-dev \
    net-tools \  
    psmisc \     
    lsof \  
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Install SurrealDB
RUN curl -sSf https://install.surrealdb.com | sh

# Install RabbitMQ and Erlang from CloudSmith repository
RUN curl -1sLf "https://dl.cloudsmith.io/public/rabbitmq/rabbitmq-erlang/setup.deb.sh" | bash && \
    curl -1sLf "https://dl.cloudsmith.io/public/rabbitmq/rabbitmq-server/setup.deb.sh" | bash && \
    apt-get update && \
    apt-get install -y erlang-base \
                       erlang-asn1 erlang-crypto erlang-eldap erlang-ftp erlang-inets \
                       erlang-mnesia erlang-os-mon erlang-parsetools erlang-public-key \
                       erlang-runtime-tools erlang-snmp erlang-ssl \
                       erlang-syntax-tools erlang-tftp erlang-tools erlang-xmerl \
                       rabbitmq-server && \
    rm -rf /var/lib/apt/lists/*

# Set up RabbitMQ directories and permissions
RUN mkdir -p /var/log/rabbitmq /var/lib/rabbitmq && \
    chown -R rabbitmq:rabbitmq /var/log/rabbitmq /var/lib/rabbitmq && \
    chmod 777 /var/log/rabbitmq /var/lib/rabbitmq

# Install Ollama
RUN curl https://ollama.ai/install.sh | sh

# Create conda environment
COPY environment.yml .
RUN conda env create -f environment.yml

# Activate conda environment
SHELL ["conda", "run", "-n", "myenv", "/bin/bash", "-c"]

# Copy the rest of the project files
COPY . .

# Run the setup script
RUN chmod +x /app/setup_venv.sh
RUN /bin/bash -c "source $HOME/.profile && /app/setup_venv.sh"

# Create log directory and files
RUN mkdir -p /var/log && \
    touch /var/log/supervisord.log && \
    touch /var/log/rabbitmq.log && \
    touch /var/log/rabbitmq.err.log && \
    touch /var/log/ollama.log && \
    touch /var/log/ollama.err.log && \
    touch /var/log/gateway.log && \
    touch /var/log/gateway.err.log && \
    touch /var/log/celery.log && \
    touch /var/log/celery.err.log && \
    chmod 666 /var/log/*.log

# Copy .env file
COPY .env /app/.env

# Expose ports
EXPOSE 3001 3002 7001 7002 5672 15672 11434

# Set up supervisord configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Start supervisord
CMD ["conda", "run", "--no-capture-output", "-n", "myenv", "/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
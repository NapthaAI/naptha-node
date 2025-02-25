from celery import Celery
from dotenv import load_dotenv
from node.utils import get_logger
from celery.signals import worker_init, worker_shutdown, celeryd_after_setup
import os
import asyncio
import traceback
import resource
from node.server.grpc_pool_manager import get_grpc_pool_instance, close_grpc_pool
import psutil

logger = get_logger(__name__)

PRIVATE_KEY = os.environ.get("PRIVATE_KEY")
PRIVATE_KEY = os.path.abspath(PRIVATE_KEY)
os.environ["PRIVATE_KEY_FULL_PATH"] = PRIVATE_KEY

NODE_COMMUNICATION_PROTOCOL = os.environ.get("NODE_COMMUNICATION_PROTOCOL")

def log_system_limits():
    """Log current system limits and resource usage"""
    try:
        # Get file descriptor limits
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        logger.info(f"File descriptor limits - Soft: {soft}, Hard: {hard}")

        # Get process information
        process = psutil.Process()
        logger.info(f"Open files count: {len(process.open_files())}")
        logger.info(f"Process memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")
        logger.info(f"CPU usage: {process.cpu_percent()}%")
        
        # Log event loop info
        loop = asyncio.get_event_loop()
        logger.info(f"Event loop running: {loop.is_running()}")
        logger.info(f"Event loop closed: {loop.is_closed()}")

    except Exception as e:
        logger.error(f"Error logging system limits: {e}")

# Load environment variables
load_dotenv(".env")
logger.info("Environment variables loaded")

# Validate OPENAI_API_KEY
try:
    OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
    logger.info("✓ OPENAI_API_KEY found in environment")
except KeyError:
    logger.error("✗ OPENAI_API_KEY not found in environment")
    raise Exception("OPENAI_API_KEY not found in environment")

# Celery config
RMQ_USER = os.environ.get("RMQ_USER")
RMQ_PASSWORD = os.environ.get("RMQ_PASSWORD")
RMQ_HOST = "rabbitmq" if os.getenv("LAUNCH_DOCKER") == "true" else "localhost"
BROKER_URL = f"amqp://{RMQ_USER}:{RMQ_PASSWORD}@{RMQ_HOST}:5672/"
BACKEND_URL = f"rpc://{RMQ_USER}:{RMQ_PASSWORD}@{RMQ_HOST}:5672/"
NUM_GRPC_CONNECTIONS = 200
BUFFER_SIZE = 20

logger.info(f"Configuration loaded:")
logger.info(f"✓ BROKER_URL configured: {BROKER_URL}")
if NODE_COMMUNICATION_PROTOCOL == "grpc":
    logger.info(f"✓ NUM_GRPC_CONNECTIONS: {NUM_GRPC_CONNECTIONS}")
    logger.info(f"✓ BUFFER_SIZE: {BUFFER_SIZE}")

@worker_init.connect
def initialize_grpc_pool(**kwargs):
    """Initializes the GlobalGrpcPool when a Celery worker starts."""
    if NODE_COMMUNICATION_PROTOCOL == "grpc":
        logger.info("Starting GlobalGrpcPool initialization...")
        try:
            pool = get_grpc_pool_instance(
                max_channels=NUM_GRPC_CONNECTIONS, buffer_size=BUFFER_SIZE
            )
            logger.info(f"✓ gRPC pool created with {NUM_GRPC_CONNECTIONS} max channels")

            # Set up event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    logger.info("Creating new event loop as current one is closed")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                loop.create_task(pool.monitor_pool())
                logger.info("✓ Pool monitor task created successfully")
                
            except Exception as e:
                logger.error(f"✗ Event loop setup failed: {e}")
                raise

            log_system_limits()
            logger.info("✓ GlobalGrpcPool initialization complete")
        except Exception as e:
            logger.error(f"✗ Failed to initialize GlobalGrpcPool: {e}")
            raise

@worker_shutdown.connect
def shutdown_grpc_pool_signal(**kwargs):
    """Shuts down the GlobalGrpcPool when a Celery worker stops."""
    if NODE_COMMUNICATION_PROTOCOL == "grpc":
        logger.info("Starting GlobalGrpcPool shutdown...")
        try:
            # Get or create event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            if loop.is_closed():
                logger.warning("Event loop was closed, creating new one for shutdown")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            logger.info("Closing gRPC pool connections...")
            # Create a new task for cleanup
            cleanup_task = loop.create_task(close_grpc_pool())
            loop.run_until_complete(cleanup_task)
            
            log_system_limits()
            logger.info("✓ GlobalGrpcPool shutdown complete")
            
        except Exception as e:
            logger.error(f"✗ Error during gRPC pool shutdown: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        finally:
            try:
                if not loop.is_closed():
                    loop.close()
            except Exception as e:
                logger.error(f"Error closing event loop: {e}")

# Celery app
app = Celery(
    "docker_tasks",
    broker=BROKER_URL,
    backend=BACKEND_URL,
    include=["node.worker.package_worker", "node.worker.docker_worker"],
)

@app.on_after_configure.connect
def setup_eventloop(sender, **kwargs):
    logger.info("Setting up event loop...")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            logger.info("Creating new event loop as current one is closed")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        logger.info("✓ Event loop setup complete")
        log_system_limits()
    except RuntimeError as e:
        logger.warning(f"RuntimeError during event loop setup: {e}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logger.info("✓ New event loop created and set")
    except Exception as e:
        logger.error(f"✗ Unexpected error setting up event loop: {e}")
        raise

@celeryd_after_setup.connect
def capture_worker_settings(sender, instance, **kwargs):
    """Log worker settings after setup is complete"""
    logger.info(f"Worker {sender} initialized with settings:")
    logger.info(f"✓ Concurrency: {instance.concurrency}")
    logger.info(f"✓ Consumer: {instance.consumer}")
    log_system_limits()


app.conf.update(
    broker_transport_options={
        'consumer_timeout': 3600*2,
        'consumer_cancel_on_timeout': False,
        'socket_timeout': 3600*2,
        'connection_max_retries': 3,
        'connection_retry_on_startup': True,
    },
    broker_connection_retry=True,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=3,
    broker_connection_timeout=30,
    broker_heartbeat=60,
    broker_pool_limit=10,  # Limit connection pool size
    task_acks_late=True,
    task_reject_on_worker_lost=True,  # Requeue task if worker dies
)
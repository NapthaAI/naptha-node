import os
import subprocess
from dotenv import load_dotenv
from node.utils import get_logger
import time

load_dotenv()
logger = get_logger(__name__)

file_path = os.path.dirname(os.path.realpath(__file__))
surql_path = os.path.join(file_path, "data_structures")


def import_surql():
    """Import SURQL files to the database"""
    logger.info("Importing SURQL files")
    import_files = [
        f"{surql_path}/user.surql",
        f"{surql_path}/module.surql",
        f"{surql_path}/auth.surql",
        f"{surql_path}/node.surql",
        f"{surql_path}/auction.surql",
        f"{surql_path}/testdata.surql",
    ]

    for file in import_files:
        command = f"""surreal import \
                      --conn http://localhost:{os.getenv('HUB_DB_PORT')} \
                      --user {os.getenv('HUB_ROOT_USER')} \
                      --pass {os.getenv('HUB_ROOT_PASS')} \
                      --ns {os.getenv('HUB_NS')} \
                      --db {os.getenv('HUB_DB')} \
                    {file}"""

        try:
            logger.info(f"Importing {file.rsplit('/', 1)[-1]}")
            process = subprocess.Popen(
                command,
                shell=True,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            out, err = process.communicate()
            logger.info(out)
            logger.info(err)
        except Exception as e:
            logger.error("Error creating scope")
            logger.error(str(e))
            raise


def init_hub():
    """Initialize the database"""
    logger.info("Initializing database")

    # use memory storage
    # command = f"""surreal start memory -A --auth \
    #               --user {os.getenv('HUB_ROOT_USER')} \
    #               --bind 0.0.0.0:{os.getenv('HUB_DB_PORT')} \
    #               --pass {os.getenv('HUB_ROOT_PASS')}"""

    # use file storage
    command = f"""surreal start -A --auth \
                  --user {os.getenv('HUB_ROOT_USER')} \
                  --bind 0.0.0.0:{os.getenv('HUB_DB_PORT')} \
                  --pass {os.getenv('HUB_ROOT_PASS')} \
                  file:./node/storage/hub/hub.db"""

    try:
        # Start the command in a new process and detach it
        _ = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            preexec_fn=os.setsid,
        )
        logger.info("Database initialization command executed")
    except Exception as e:
        logger.error("Error initializing database")
        logger.error(str(e))
        raise

    time.sleep(5)
    logger.info("Database initialized")
    import_surql()


if __name__ == "__main__":
    init_hub()

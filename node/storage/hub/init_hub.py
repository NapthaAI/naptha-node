import asyncio
from dotenv import load_dotenv, find_dotenv
import os
from pathlib import Path
import subprocess
import time
import getpass

from node.storage.hub.hub import HubDBSurreal
from node.user import get_public_key_from_pem
from node.utils import add_credentials_to_env, get_logger, get_node_config

load_dotenv(find_dotenv(), override=True)
logger = get_logger(__name__)



file_path = os.path.dirname(os.path.realpath(__file__))
surql_path = os.path.join(file_path, "data_structures")
root_dir = Path(file_path).parent.parent
LOCAL_HUB = os.getenv("LOCAL_HUB").lower() == "true"
LAUNCH_DOCKER = os.getenv("LAUNCH_DOCKER").lower() == "true"

if LAUNCH_DOCKER:
    HUB_URL = "http://surrealdb:8000"
else:
    HUB_URL = "http://localhost:3001"


def import_surql():
    """Import SURQL files to the database"""
    logger.info("Importing SURQL files")
    import_files = [
        f"{surql_path}/user.surql",
        f"{surql_path}/agent.surql",
        f"{surql_path}/orchestrator.surql",
        f"{surql_path}/environment.surql",
        f"{surql_path}/persona.surql",
        f"{surql_path}/auth.surql",
        f"{surql_path}/node.surql",
        f"{surql_path}/kb.surql",
        f"{surql_path}/memory.surql",
        f"{surql_path}/tool.surql",
        f"{surql_path}/testdata.surql",
        f"{surql_path}/api_secrets.surql",
    ]

    for file in import_files:
        command = f"""surreal import \
                      --conn {HUB_URL} \
                      --user {os.getenv('HUB_DB_SURREAL_ROOT_USER')} \
                      --pass {os.getenv('HUB_DB_SURREAL_ROOT_PASS')} \
                      --ns {os.getenv('HUB_DB_SURREAL_NS')} \
                      --db {os.getenv('HUB_DB_SURREAL_NAME')} \
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


async def init_hub():
    """Initialize the database"""
    if not LOCAL_HUB:
        logger.info("Local hub disabled; skipping importing surql files")
        return
    else:
        if LAUNCH_DOCKER:
            # NOTE: surrealdb is running in docker
            time.sleep(5)
            import_surql()
        else:
            logger.info("Initializing database")
            # use file storage
            command = f"""surreal start -A \
                        --user {os.getenv('HUB_DB_SURREAL_ROOT_USER')} \
                        --bind 0.0.0.0:{os.getenv('HUB_DB_SURREAL_PORT')} \
                        --pass {os.getenv('HUB_DB_SURREAL_ROOT_PASS')} \
                        rocksdb://./node/storage/hub/hub.db"""

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


async def register_node():
    node_config = get_node_config()
    async with HubDBSurreal() as hub:
        success, user, user_id = await hub.signin(
            os.getenv("HUB_USERNAME"), os.getenv("HUB_PASSWORD")
        )
        node_config = await hub.create_node(node_config)


async def user_setup_flow():
    async with HubDBSurreal() as hub:
        username, password = os.getenv("HUB_USERNAME"), os.getenv("HUB_PASSWORD")
        username_exists, password_exists = len(username) > 1, len(password) > 1
        public_key = get_public_key_from_pem(os.getenv("PRIVATE_KEY"))
        logger.info(f"Public key: {public_key}")
        logger.info(f"Checking if user exists... User: {username}")
        user = await hub.get_user_by_username(username)
        user_public_key = await hub.get_user_by_public_key(public_key)
        existing_public_key_user = (
            user_public_key is not None and user_public_key.get("username") != username
        )

        match user, username_exists, password_exists, existing_public_key_user:
            case _, True, _, True:
                # Public key exists and doesn't match the provided username and password
                raise Exception(
                    f"User with public key {public_key} already exists but doesn't match the provided username and password. Please use a different private key (or set blank in the .env file to randomly generate with launch.sh)."
                )

            case _, False, False, True:
                # Public key exists and no username/password provided
                raise Exception(
                    f"User with public key {public_key} already exists. Cannot create new user. Please use a different private key (or set blank in the .env file to randomly generate with launch.sh)."
                )

            case None, False, _, False:
                # User doesn't exist and credentials are missing
                logger.info("User does not exist...")
                create_new = input(
                    "Would you like to create a new user? (yes/no): "
                ).lower()
                if create_new != "yes":
                    raise Exception(
                        "User does not exist and new user creation was declined."
                    )

                logger.info("Creating new user...")
                while True:
                    username = input("Enter username: ")
                    password = getpass.getpass("Enter password: ") 
                    print(f"Signing up user: {username} with public key: {public_key}")
                    success, token, user_id = await hub.signup(
                        username, password, public_key
                    )
                    if success:
                        add_credentials_to_env(username, password)
                        logger.info("Sign up successful!")
                        return token, user_id
                    else:
                        logger.error("Sign up failed. Please try again.")

            case None, True, True, False:
                # User doesn't exist but credentials are provided
                print(f"Signing up user: {username} with public key: {public_key}")
                success, token, user_id = await hub.signup(
                    username, password, public_key
                )
                if success:
                    logger.info("Sign up successful!")
                    return token, user_id
                else:
                    logger.error("Sign up failed.")
                    raise Exception("Sign up failed.")

            case dict(), True, True, False:
                # User exists, attempt to sign in
                logger.info("User exists. Attempting to sign in...")
                success, token, user_id = await hub.signin(username, password)
                if success:
                    logger.info("Sign in successful!")
                    return token, user_id
                else:
                    logger.error(
                        "Sign in failed. Please check your credentials in the .env file."
                    )
                    raise Exception(
                        "Sign in failed. Please check your credentials in the .env file."
                    )

            case _:
                logger.error("Unexpected case encountered in user setup flow.")
                raise Exception(
                    "Unexpected error in user setup. Please check your configuration and try again."
                )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Initialize Hub DB (SurrealDB) or run user setup flow"
    )
    parser.add_argument("--user", action="store_true", help="Run user setup flow")
    args = parser.parse_args()

    if args.user:

        async def run_user_setup():
            async with HubDBSurreal() as hub:
                await user_setup_flow()

        asyncio.run(run_user_setup())
    else:
        asyncio.run(init_hub())
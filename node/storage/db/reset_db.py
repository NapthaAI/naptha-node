from dotenv import load_dotenv
import os
import platform
import subprocess
import sys
import logging

load_dotenv()
logger = logging.getLogger(__name__)

LOCAL_DB_POSTGRES_USERNAME = os.getenv("LOCAL_DB_POSTGRES_USERNAME")
LOCAL_DB_POSTGRES_PASSWORD = os.getenv("LOCAL_DB_POSTGRES_PASSWORD")
LOCAL_DB_POSTGRES_NAME = os.getenv("LOCAL_DB_POSTGRES_NAME")
LOCAL_DB_POSTGRES_PORT = os.getenv("LOCAL_DB_POSTGRES_PORT")

def reset_db():
    logger.info("Starting database reset...")
    
    is_macos = platform.system() == 'Darwin'
    
    if is_macos:
        commands = [
            "rm -rf node/storage/db/alembic/versions/*",
            f"psql -p {LOCAL_DB_POSTGRES_PORT} postgres -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{LOCAL_DB_POSTGRES_NAME}' AND pid <> pg_backend_pid();\"",
            f"dropdb -p {LOCAL_DB_POSTGRES_PORT} --if-exists {LOCAL_DB_POSTGRES_NAME}",
            f"dropuser -p {LOCAL_DB_POSTGRES_PORT} --if-exists {LOCAL_DB_POSTGRES_USERNAME}",
            f"createuser -p {LOCAL_DB_POSTGRES_PORT} {LOCAL_DB_POSTGRES_USERNAME}",
            f"psql -p {LOCAL_DB_POSTGRES_PORT} postgres -c \"ALTER USER {LOCAL_DB_POSTGRES_USERNAME} WITH PASSWORD '{LOCAL_DB_POSTGRES_PASSWORD}';\"",
            f"createdb -p {LOCAL_DB_POSTGRES_PORT} --owner={LOCAL_DB_POSTGRES_USERNAME} {LOCAL_DB_POSTGRES_NAME}",
            f"psql -p {LOCAL_DB_POSTGRES_PORT} postgres -c \"ALTER USER {LOCAL_DB_POSTGRES_USERNAME} CREATEDB;\""
        ]
    else:
        commands = [
            "rm -rf node/storage/db/alembic/versions/*",
            f"sudo -u postgres psql -d template1 -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{LOCAL_DB_POSTGRES_NAME}' AND pid <> pg_backend_pid();\"",
            f"sudo -u postgres psql -d template1 -c \"DROP DATABASE IF EXISTS {LOCAL_DB_POSTGRES_NAME};\"",
            f"sudo -u postgres psql -d template1 -c \"DROP USER IF EXISTS {LOCAL_DB_POSTGRES_USERNAME};\"",
            f"sudo -u postgres psql -d template1 -c \"CREATE USER {LOCAL_DB_POSTGRES_USERNAME} WITH PASSWORD '{LOCAL_DB_POSTGRES_PASSWORD}';\"",
            f"sudo -u postgres psql -d template1 -c \"CREATE DATABASE {LOCAL_DB_POSTGRES_NAME} WITH OWNER {LOCAL_DB_POSTGRES_USERNAME};\"",
            f"sudo -u postgres psql -d template1 -c \"ALTER USER {LOCAL_DB_POSTGRES_USERNAME} CREATEDB;\""
        ]

    logger.info("Executing database commands...")
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            logger.debug(f"✓ {cmd}")
        except subprocess.CalledProcessError as e:
            logger.error(f"\nError executing: {cmd}")
            logger.error(f"Exit code: {e.returncode}")
            if e.stdout:
                logger.error(f"stdout: {e.stdout}")
            if e.stderr:
                logger.error(f"stderr: {e.stderr}")
            sys.exit(1)

    logger.info("Database reset complete!")

if __name__ == "__main__":
    reset_db()
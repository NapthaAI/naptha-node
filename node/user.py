import logging
from ecdsa import SigningKey, SECP256k1, VerifyingKey
from node.storage.db.db import LocalDBPostgres
from typing import Dict, Tuple
from pathlib import Path

file_path = Path(__file__).resolve()
root_path = file_path.parent.parent
from eth_hash.auto import keccak

logger = logging.getLogger(__name__)

async def register_user(user_input: Dict) -> Tuple[bool, Dict]:
    logger.info("Registering user.")
    input_ = {
        "public_key": user_input["public_key"],
        "id": "user:" + user_input["public_key"],
    }
    async with LocalDBPostgres() as db:
        user = await db.create_user(input_)

    if user:
        user_data = user.copy()
        user_data.pop("_sa_instance_state", None)
        logger.info(f"Created user: {user_data}")
        return True, user_data
    else:
        return False, {}


async def check_user(user_input: Dict) -> Tuple[bool, Dict]:
    logger.info("Checking user.")
    async with LocalDBPostgres() as db:
        user = await db.get_user(user_input=user_input)

    if user:
        logger.info(f"Found user: {user}")
        user_data = user.copy()
        user_data.pop("_sa_instance_state", None)
        user_data["is_registered"] = True
        return True, user_data
    else:
        logger.error("No user found.")
        user_data = user_input.copy()
        user_data["is_registered"] = False
        return False, user_data
    
async def get_user_public_key(user_id: str) -> str | None:
    async with LocalDBPostgres() as db:
        public_key = await db.get_public_key_by_id(user_id)

    if public_key:
        return public_key
    else:
        logger.error("No user found.")
        return None

def get_public_key(private_key_hex):
    private_key = SigningKey.from_string(
        bytes.fromhex(private_key_hex), curve=SECP256k1
    )
    public_key = private_key.get_verifying_key()
    return public_key.to_string().hex()


def generate_user(username: str):
    pem_path = root_path / f"{username}.pem"
    logger.info(f"Generating user at {pem_path}")
    if pem_path.exists():
        with open(pem_path, "r") as f:
            private_key = f.read().strip()
        public_key = get_public_key(private_key)
    else:
        private_key = SigningKey.generate(curve=SECP256k1).to_string().hex()
        with open(pem_path, "w") as f:
            f.write(private_key)
        public_key = get_public_key(private_key)
    return public_key, pem_path

def get_public_key_from_pem(private_key_path: str) -> str:
    pem_path = root_path / private_key_path
    logger.info(f"Getting public key from {pem_path}")
    if not pem_path.exists():
        raise FileNotFoundError(f"User private key file not found at {pem_path}")
    with open(pem_path, "r") as f:
        private_key = f.read().strip()
    public_key = get_public_key(private_key)
    return public_key

def verify_signature(consumer_id, signature_hex, public_key_hex):
    public_key = VerifyingKey.from_string(bytes.fromhex(public_key_hex), curve=SECP256k1)
    consumer_id_bytes = consumer_id.encode('utf-8')
    signature = bytes.fromhex(signature_hex)
    try:
        if public_key.verify(signature, consumer_id_bytes):
            return True
    except:
        return False
    
def generate_address(public_key: bytes) -> str:
    if len(public_key) not in [64, 33]:
        print(public_key)
        raise ValueError("Public key must be either 33 or 64 bytes long.")
        
    hash = keccak(public_key)
    address = hash[-20:]
    return "0x" + address.hex()

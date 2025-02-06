import os
import base64
import logging
from cryptography.hazmat.primitives.asymmetric import rsa, padding as asymmetric_padding
from cryptography.hazmat.primitives import serialization, hashes, padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)

class Secret:
    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, 'instance'):
            cls.instance = super(Secret, cls).__new__(cls)
        return cls.instance

    def __init__(self, private_key_path="private_key.pem", public_key_path="public_key.pem", env_file=".env"):
        if hasattr(self, 'initialized'):
            return

        self.private_key_path = private_key_path
        self.public_key_path = public_key_path
        self.env_file = env_file

        # Initialize the keys and secrets
        self.check_and_generate_keys()
        self.check_and_generate_aes_secret()

        self.initialized = True

    def check_and_generate_keys(self):
        if not os.path.exists(self.private_key_path) or not os.path.exists(self.public_key_path):
            logger.info("RSA keys not found. Generating new keys...")
            self.generate_keys()
        else:
            logger.info("RSA keys already exist. Loading keys...")
            self.load_keys()

    def generate_keys(self):
        self.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )

        self.public_key = self.private_key.public_key()

        with open(self.private_key_path, "wb") as private_file:
            private_pem = self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            )
            private_file.write(private_pem)

        with open(self.public_key_path, "wb") as public_file:
            public_pem = self.public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            public_file.write(public_pem)

        logger.info("RSA keys generated and saved to files.")

    def load_keys(self):
        with open(self.private_key_path, "rb") as private_file:
            private_pem = private_file.read()
            self.private_key = serialization.load_pem_private_key(
                private_pem,
                password=None,
                backend=default_backend()
            )

        with open(self.public_key_path, "rb") as public_file:
            public_pem = public_file.read()
            self.public_key = serialization.load_pem_public_key(
                public_pem,
                backend=default_backend()
            )

        logger.info("RSA keys loaded from files.")

    def get_public_key(self):
        public_numbers = self.public_key.public_numbers()

        # Using a fixed `kid` that stays the same for this key
        jwk = {
            "kty": "RSA",
            "kid": "server-key",
            "use": "enc",
            "n": self._encode_base64_url(public_numbers.n),
            "e": self._encode_base64_url(public_numbers.e),
        }

        return jwk

    def check_and_generate_aes_secret(self):
        if not self._aes_secret_exists():
            logger.info("AES secret not found. Generating new AES secret...")
            self.generate_aes_secret()
        else:
            logger.info("AES secret already exists in .env.")

    def _aes_secret_exists(self):
        if not os.path.exists(self.env_file):
            return False
        
        with open(self.env_file, "r") as f:
            for line in f:
                if line.startswith("AES_SECRET="):
                    return True
        return False

    def generate_aes_secret(self):
        aes_key = os.urandom(32)
        
        self.save_to_env("AES_SECRET", base64.b64encode(aes_key).decode())
        logger.info("AES secret generated and saved to .env.")

    def decrypt_rsa(self, base64_message):
        encrypted_message = base64.b64decode(base64_message)

        decrypted_message = self.private_key.decrypt(
            encrypted_message,
            asymmetric_padding.OAEP(
                mgf=asymmetric_padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        return decrypted_message.decode('utf-8')

    def encrypt_with_aes(self, data: str, aes_key: bytes):
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()  # 128 bits = 16 bytes
        padded_data = padder.update(data.encode()) + padder.finalize()

        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

        return base64.b64encode(iv + encrypted_data).decode()

    def decrypt_with_aes(self, encrypted_data: str, aes_key: bytes):
        encrypted_data = base64.b64decode(encrypted_data)
        iv = encrypted_data[:16]
        encrypted_message = encrypted_data[16:]
        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())

        decryptor = cipher.decryptor()
        decrypted_data = decryptor.update(encrypted_message) + decryptor.finalize()
        
        unpadder = padding.PKCS7(128).unpadder()
        original_data = unpadder.update(decrypted_data) + unpadder.finalize()

        return original_data.decode() 

    def save_to_env(self, key, value):
        with open(self.env_file, "a") as f:
            f.write(f"{key}={value}\n")

    def _encode_base64_url(self, value: int) -> str:
        encoded = base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, byteorder='big'))
        return encoded.decode('utf-8').rstrip("=")

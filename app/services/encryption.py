"""
Encryption Service
Provides at-rest encryption for sensitive data like TOTP secrets
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def get_encryption_key() -> bytes:
    """
    Get or derive the encryption key from environment variable.

    Uses ENCRYPTION_KEY env var if set (should be a valid Fernet key).
    Otherwise derives a key from SECRET_KEY using PBKDF2.
    """
    encryption_key = os.environ.get('ENCRYPTION_KEY')

    if encryption_key:
        # Use provided Fernet key directly
        return encryption_key.encode()

    # Derive key from SECRET_KEY using PBKDF2
    secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Use a fixed salt for deterministic key derivation
    # In production, ENCRYPTION_KEY should be set explicitly
    salt = b'cryptolens-totp-encryption-salt'

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return key


def encrypt_value(plaintext: str) -> str:
    """
    Encrypt a plaintext string.
    Returns base64-encoded ciphertext.
    """
    if not plaintext:
        return ''

    key = get_encryption_key()
    f = Fernet(key)
    encrypted = f.encrypt(plaintext.encode())
    return encrypted.decode()


def decrypt_value(ciphertext: str) -> str:
    """
    Decrypt a ciphertext string.
    Returns the original plaintext.
    """
    if not ciphertext:
        return ''

    key = get_encryption_key()
    f = Fernet(key)
    decrypted = f.decrypt(ciphertext.encode())
    return decrypted.decode()


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.
    Use this to generate ENCRYPTION_KEY for production.
    """
    return Fernet.generate_key().decode()

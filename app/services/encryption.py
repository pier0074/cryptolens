"""
Encryption Service
Provides at-rest encryption for sensitive data like TOTP secrets

Environment Variables:
    ENCRYPTION_KEY: A valid Fernet key (recommended for production)
    SECRET_KEY: Flask secret key (used for key derivation if ENCRYPTION_KEY not set)
    ENCRYPTION_SALT: Salt for PBKDF2 key derivation (required in production if using SECRET_KEY)

Generate a new encryption key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Generate a salt:
    python -c "import secrets; print(secrets.token_hex(16))"
"""
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class EncryptionConfigError(Exception):
    """Raised when encryption is not properly configured"""
    pass


def _is_production() -> bool:
    """Check if running in production mode"""
    flask_env = os.environ.get('FLASK_ENV', 'production')
    flask_debug = os.environ.get('FLASK_DEBUG', '0')
    return flask_env == 'production' and flask_debug != '1'


def get_encryption_key() -> bytes:
    """
    Get or derive the encryption key from environment variable.

    Uses ENCRYPTION_KEY env var if set (should be a valid Fernet key).
    Otherwise derives a key from SECRET_KEY using PBKDF2 with ENCRYPTION_SALT.

    Raises:
        EncryptionConfigError: If required environment variables are not set in production
    """
    encryption_key = os.environ.get('ENCRYPTION_KEY')

    if encryption_key:
        # Use provided Fernet key directly
        return encryption_key.encode()

    # Get SECRET_KEY - required
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if _is_production():
            raise EncryptionConfigError(
                "SECRET_KEY environment variable is required in production. "
                "Set SECRET_KEY or ENCRYPTION_KEY in your .env file."
            )
        # Development fallback only
        secret_key = 'dev-secret-key-do-not-use-in-production'

    # Get salt - required in production for security
    salt_hex = os.environ.get('ENCRYPTION_SALT')
    if salt_hex:
        salt = bytes.fromhex(salt_hex)
    else:
        if _is_production():
            raise EncryptionConfigError(
                "ENCRYPTION_SALT environment variable is required in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(16))\""
            )
        # Development fallback only - deterministic for testing
        salt = b'dev-salt-do-not-use-in-prod'

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

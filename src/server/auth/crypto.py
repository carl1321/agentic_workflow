# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
RSA encryption/decryption utilities for password transmission security.

This module provides RSA public key encryption for passwords before transmission,
and private key decryption on the server side.
"""

import base64
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from Crypto.Cipher import PKCS1_OAEP
    from Crypto.PublicKey import RSA
    from Crypto.Hash import SHA256
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger.warning(
        "pycryptodome not installed. Password encryption features will not be available. "
        "Please install: pip install pycryptodome"
    )

# Default key storage location
KEYS_DIR = Path(__file__).parent.parent.parent.parent / ".keys"
PRIVATE_KEY_PATH = KEYS_DIR / "rsa_private_key.pem"
PUBLIC_KEY_PATH = KEYS_DIR / "rsa_public_key.pem"

# RSA key size (2048 bits is secure and widely supported)
RSA_KEY_SIZE = 2048


def ensure_keys_dir():
    """Ensure the keys directory exists."""
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    # Set restrictive permissions (owner read/write only)
    if os.name != "nt":  # Windows doesn't support chmod the same way
        os.chmod(KEYS_DIR, 0o700)


def generate_key_pair() -> tuple[str, str]:
    """
    Generate a new RSA key pair.
    
    Raises:
        RuntimeError: If pycryptodome is not installed
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError(
            "pycryptodome is not installed. Please install it: pip install pycryptodome"
        )
    """
    Generate a new RSA key pair.
    
    Returns:
        tuple: (private_key_pem, public_key_pem) as strings
        public_key_pem is in SPKI format (PKCS#8) for Web Crypto API compatibility
    """
    logger.info("Generating new RSA key pair...")
    key = RSA.generate(RSA_KEY_SIZE)
    
    # Export private key in PKCS#1 format
    private_key_pem = key.export_key("PEM").decode("utf-8")
    
    # Export public key in SPKI format (PKCS#8) for Web Crypto API
    # This format is required by Web Crypto API's importKey with "spki" format
    public_key_pem = key.publickey().export_key("PEM", pkcs=8).decode("utf-8")
    
    return private_key_pem, public_key_pem


def save_key_pair(private_key_pem: str, public_key_pem: str):
    """Save RSA key pair to files."""
    ensure_keys_dir()
    
    # Write private key
    PRIVATE_KEY_PATH.write_text(private_key_pem, encoding="utf-8")
    if os.name != "nt":
        os.chmod(PRIVATE_KEY_PATH, 0o600)  # Owner read/write only
    
    # Write public key
    PUBLIC_KEY_PATH.write_text(public_key_pem, encoding="utf-8")
    if os.name != "nt":
        os.chmod(PUBLIC_KEY_PATH, 0o644)  # Owner read/write, others read
    
    logger.info(f"RSA keys saved to {KEYS_DIR}")


def load_or_generate_key_pair() -> tuple[str, str]:
    """
    Load existing RSA key pair or generate new one if not found.
    
    Returns:
        tuple: (private_key_pem, public_key_pem) as strings
    """
    if PRIVATE_KEY_PATH.exists() and PUBLIC_KEY_PATH.exists():
        try:
            private_key_pem = PRIVATE_KEY_PATH.read_text(encoding="utf-8")
            public_key_pem = PUBLIC_KEY_PATH.read_text(encoding="utf-8")
            logger.info("Loaded existing RSA key pair")
            return private_key_pem, public_key_pem
        except Exception as e:
            logger.warning(f"Failed to load existing keys: {e}. Generating new pair...")
    
    # Generate and save new key pair
    private_key_pem, public_key_pem = generate_key_pair()
    save_key_pair(private_key_pem, public_key_pem)
    return private_key_pem, public_key_pem


def get_public_key() -> str:
    """
    Get the RSA public key (for client-side encryption).
    
    Returns:
        str: Public key in PEM format
        
    Raises:
        RuntimeError: If pycryptodome is not installed
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError(
            "pycryptodome is not installed. Please install it: pip install pycryptodome"
        )
    _, public_key_pem = load_or_generate_key_pair()
    return public_key_pem


def decrypt_password(encrypted_password_b64: str) -> Optional[str]:
    """
    Decrypt a password that was encrypted with the public key using RSA-OAEP.
    
    Args:
        encrypted_password_b64: Base64-encoded encrypted password (encrypted with RSA-OAEP)
        
    Returns:
        Decrypted password string, or None if decryption fails
        
    Raises:
        RuntimeError: If pycryptodome is not installed
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError(
            "pycryptodome is not installed. Please install it: pip install pycryptodome"
        )
    try:
        private_key_pem, _ = load_or_generate_key_pair()
        private_key = RSA.import_key(private_key_pem)
        # Use PKCS1_OAEP (RSA-OAEP) to match Web Crypto API
        cipher = PKCS1_OAEP.new(private_key, hashAlgo=SHA256)
        
        # Decode from base64
        encrypted_bytes = base64.b64decode(encrypted_password_b64)
        
        # Decrypt
        decrypted_bytes = cipher.decrypt(encrypted_bytes)
        
        return decrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Error decrypting password: {e}")
        return None


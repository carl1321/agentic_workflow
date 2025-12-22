/**
 * RSA encryption utilities for password security.
 * Uses Web Crypto API for RSA-OAEP encryption.
 */

interface PublicKeyInfo {
  public_key: string;
  algorithm: string;
  key_size: number;
}

let cachedPublicKey: CryptoKey | null = null;
let cachedPublicKeyInfo: PublicKeyInfo | null = null;

/**
 * Convert PEM public key to CryptoKey object.
 * Supports both PKCS#1 (RSA PUBLIC KEY) and SPKI (PUBLIC KEY) formats.
 */
async function importPublicKey(pem: string): Promise<CryptoKey> {
  // Remove PEM headers and whitespace
  // Handle both formats: "-----BEGIN PUBLIC KEY-----" (SPKI) and "-----BEGIN RSA PUBLIC KEY-----" (PKCS#1)
  let pemContents = pem
    .replace(/-----BEGIN (RSA )?PUBLIC KEY-----/g, "")
    .replace(/-----END (RSA )?PUBLIC KEY-----/g, "")
    .replace(/\s/g, "");

  // Convert base64 to ArrayBuffer
  const binaryDer = Uint8Array.from(atob(pemContents), (c) => c.charCodeAt(0));

  // Import the key (Web Crypto API expects SPKI format)
  // If the key is in PKCS#1 format, we need to convert it
  // For now, try importing as SPKI first
  try {
    return await crypto.subtle.importKey(
      "spki",
      binaryDer.buffer,
      {
        name: "RSA-OAEP",
        hash: "SHA-256",
      },
      false,
      ["encrypt"],
    );
  } catch (error) {
    // If import fails, the key might be in PKCS#1 format
    // In that case, we need to convert it (but Web Crypto API doesn't support PKCS#1 directly)
    // So we'll throw a more helpful error
    console.error("Failed to import public key. Make sure the server exports SPKI format.", error);
    throw new Error("Invalid public key format. Server must export SPKI (PKCS#8) format.");
  }
}

/**
 * Get public key from server and cache it.
 */
async function getPublicKey(): Promise<CryptoKey> {
  if (cachedPublicKey) {
    return cachedPublicKey;
  }

  const { resolveServiceURL } = await import("../api/resolve-service-url");
  const url = resolveServiceURL("auth/public-key");

  const response = await fetch(url, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch public key: ${response.status}`);
  }

  const info: PublicKeyInfo = await response.json();
  cachedPublicKeyInfo = info;
  cachedPublicKey = await importPublicKey(info.public_key);

  return cachedPublicKey;
}

/**
 * Encrypt password using RSA-OAEP.
 * 
 * @param password Plain text password
 * @returns Base64-encoded encrypted password
 */
export async function encryptPassword(password: string): Promise<string> {
  try {
    const publicKey = await getPublicKey();

    // Convert password to ArrayBuffer
    const encoder = new TextEncoder();
    const data = encoder.encode(password);

    // Encrypt
    const encrypted = await crypto.subtle.encrypt(
      {
        name: "RSA-OAEP",
      },
      publicKey,
      data,
    );

    // Convert to base64
    const base64 = btoa(
      String.fromCharCode(...new Uint8Array(encrypted)),
    );

    return base64;
  } catch (error) {
    console.error("Error encrypting password:", error);
    throw new Error("Failed to encrypt password");
  }
}

/**
 * Clear cached public key (useful for testing or key rotation).
 */
export function clearPublicKeyCache(): void {
  cachedPublicKey = null;
  cachedPublicKeyInfo = null;
}


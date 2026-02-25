/**
 * RSA encryption utilities for password security.
 * Prefers Web Crypto API (RSA-OAEP); when unavailable (e.g. HTTP non-localhost),
 * falls back to node-forge so password is still encrypted before sending.
 */

interface PublicKeyInfo {
  public_key: string;
  algorithm: string;
  key_size: number;
}

let cachedPublicKey: CryptoKey | null = null;
let cachedPublicKeyPem: string | null = null;

function isSubtleAvailable(): boolean {
  return (
    typeof globalThis !== "undefined" &&
    !!globalThis.crypto &&
    !!(globalThis.crypto as Crypto).subtle
  );
}

/**
 * Convert PEM public key to CryptoKey (Web Crypto).
 */
async function importPublicKey(pem: string): Promise<CryptoKey> {
  if (!isSubtleAvailable()) {
    throw new Error("Web Crypto is not available");
  }
  const subtle = (globalThis.crypto as Crypto).subtle;
  const pemContents = pem
    .replace(/-----BEGIN (RSA )?PUBLIC KEY-----/g, "")
    .replace(/-----END (RSA )?PUBLIC KEY-----/g, "")
    .replace(/\s/g, "");

  const binaryDer = Uint8Array.from(atob(pemContents), (c) => c.charCodeAt(0));

  return subtle.importKey(
    "spki",
    binaryDer.buffer,
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["encrypt"],
  );
}

/**
 * Fetch public key PEM from server (cached).
 */
async function fetchPublicKeyPem(): Promise<string> {
  if (cachedPublicKeyPem) {
    return cachedPublicKeyPem;
  }
  const { resolveServiceURL } = await import("../api/resolve-service-url");
  const url = resolveServiceURL("auth/public-key");
  const response = await fetch(url, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch public key: ${response.status}`);
  }
  const info: PublicKeyInfo = await response.json();
  cachedPublicKeyPem = info.public_key;
  return cachedPublicKeyPem;
}

/**
 * Get public key for Web Crypto path.
 */
async function getPublicKey(): Promise<CryptoKey> {
  if (cachedPublicKey) return cachedPublicKey;
  const pem = await fetchPublicKeyPem();
  cachedPublicKey = await importPublicKey(pem);
  return cachedPublicKey;
}

/**
 * Encrypt password using node-forge (RSA-OAEP/SHA-256). Used when crypto.subtle is unavailable.
 */
async function encryptWithForge(password: string): Promise<string> {
  const forge = await import("node-forge");
  const pem = await fetchPublicKeyPem();
  const publicKey = forge.pki.publicKeyFromPem(pem);
  const bytes = forge.util.encodeUtf8(password);
  const encrypted = publicKey.encrypt(bytes, "RSA-OAEP", {
    md: forge.md.sha256.create(),
    mgf1: { md: forge.md.sha256.create() },
  });
  return forge.util.encode64(encrypted);
}

/**
 * Encrypt password using RSA-OAEP. Uses Web Crypto when available, else node-forge.
 *
 * @param password Plain text password
 * @returns Base64-encoded encrypted password
 */
export async function encryptPassword(password: string): Promise<string> {
  try {
    if (isSubtleAvailable()) {
      const publicKey = await getPublicKey();
      const subtle = (globalThis.crypto as Crypto).subtle;
      const data = new TextEncoder().encode(password);
      const encrypted = await subtle.encrypt(
        { name: "RSA-OAEP" },
        publicKey,
        data,
      );
      return btoa(
        String.fromCharCode(...new Uint8Array(encrypted)),
      );
    }
    return await encryptWithForge(password);
  } catch (error) {
    console.error("Error encrypting password:", error);
    throw new Error("Failed to encrypt password");
  }
}

/**
 * Clear cached public key (e.g. after key rotation).
 */
export function clearPublicKeyCache(): void {
  cachedPublicKey = null;
  cachedPublicKeyPem = null;
}

/**
 * Compute SHA-256 hash of a string and return hex.
 * Uses Web Crypto when available, else node-forge (for HTTP non-localhost).
 */
export async function sha256Hex(data: string): Promise<string> {
  if (isSubtleAvailable()) {
    const subtle = (globalThis.crypto as Crypto).subtle;
    const buffer = await subtle.digest(
      "SHA-256",
      new TextEncoder().encode(data)
    );
    return Array.from(new Uint8Array(buffer))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }
  const forge = await import("node-forge");
  const md = forge.md.sha256.create();
  md.update(data, "utf8");
  return md.digest().toHex();
}

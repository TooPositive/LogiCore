"""PII Vault -- GDPR-safe encrypted storage for query text.

Resolves the GDPR vs EU AI Act tension:
  - Article 12 mandates audit trail for high-risk AI decisions
  - GDPR Article 17 mandates right to erasure
  - Solution: audit_log stores only query_hash, raw PII goes here
    with AES-256-GCM encryption, separate retention, and soft delete

Security model:
  1. Parameterized queries only ($1, $2, ...) -- no string interpolation
  2. Encryption is injectable (encrypt_fn/decrypt_fn) for key management
     flexibility (test mock, Azure Key Vault, AWS KMS in production)
  3. Soft delete (set deleted_at) preserves audit log structure while
     removing PII on GDPR erasure request
  4. PII detection is heuristic -- flags queries containing names near
     PII keywords (salary, contract, employment, health, medical)
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

# --- SQL (parameterized) ---

_INSERT_SQL = """
INSERT INTO audit_pii_vault (
    audit_entry_id, query_text_encrypted, encryption_key_id,
    retention_until
) VALUES (
    $1, $2, $3, $4
) RETURNING
    id, audit_entry_id, query_text_encrypted, encryption_key_id,
    retention_until, created_at, deleted_at
"""

_SELECT_BY_AUDIT_ENTRY_SQL = """
SELECT
    id, audit_entry_id, query_text_encrypted, encryption_key_id,
    retention_until, created_at, deleted_at
FROM audit_pii_vault
WHERE audit_entry_id = $1
"""

_SOFT_DELETE_SQL = """
UPDATE audit_pii_vault
SET deleted_at = NOW()
WHERE audit_entry_id = $1 AND deleted_at IS NULL
"""

_IS_DELETED_SQL = """
SELECT deleted_at
FROM audit_pii_vault
WHERE audit_entry_id = $1
"""


# --- PII Detection (heuristic) ---

# PII keywords: if a query contains one of these AND a proper name pattern,
# it's likely PII and should be encrypted in the vault.
_PII_KEYWORDS = re.compile(
    r"\b(salary|contract|employment|health|medical|personal|"
    r"address|phone|pesel|nip|email|sick\s+leave|"
    r"termination|dismissal|discipline|"
    # Polish equivalents
    r"pensj[aęy]|umow[aęy]|zatrudnien|zdrow|medyczn|osobow|"
    r"adres|telefon|zwolnien|dyscyplin|wynagrodzeni)\b",
    re.IGNORECASE,
)

# Proper name: two+ capitalized words including Polish diacritics
# (ą, ć, ę, ł, ń, ó, ś, ź, ż and their uppercase equivalents)
_UPPER = r"A-ZĄĆĘŁŃÓŚŹŻ"
_LOWER = r"a-ząćęłńóśźż"
_NAME_PATTERN = re.compile(rf"[{_UPPER}][{_LOWER}]+\s+[{_UPPER}][{_LOWER}]+")

# Email pattern
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Phone number pattern (international or Polish: +48 123 456 789)
_PHONE_PATTERN = re.compile(r"\+\d{1,3}[\s-]?\d[\d\s-]{7,}")

# PESEL pattern (11 digits, Polish national ID)
_PESEL_PATTERN = re.compile(r"\b\d{11}\b")


def detect_pii(query_text: str) -> bool:
    """Heuristic PII detection in query text.

    Returns True if the query likely contains personally identifiable
    information. Checks for:
      - Name + PII keyword (e.g., "Jan Kowalski salary")
      - Email addresses
      - Phone numbers
      - PESEL numbers (Polish national ID)

    This is a conservative heuristic -- it may flag some false positives.
    Better to encrypt a non-PII query than to miss a PII query.
    """
    # Direct PII patterns (no keyword match needed)
    if _EMAIL_PATTERN.search(query_text):
        return True
    if _PHONE_PATTERN.search(query_text):
        return True
    if _PESEL_PATTERN.search(query_text):
        return True

    # Keyword + name pattern
    has_keyword = _PII_KEYWORDS.search(query_text)
    has_name = _NAME_PATTERN.search(query_text)
    if has_keyword and has_name:
        return True

    # Keyword alone near PESEL/NIP reference
    if has_keyword and re.search(r"\bPESEL\b", query_text, re.IGNORECASE):
        return True

    return False


class PIIVault:
    """GDPR-safe PII storage with encryption and soft delete.

    All methods accept an asyncpg connection (not pool) so callers
    can wrap operations in the same transaction as audit writes.
    """

    async def store(
        self,
        conn,
        audit_entry_id: UUID,
        query_text: str,
        encryption_key_id: str,
        encrypt_fn: Callable[[str], bytes],
        retention_years: int = 10,
    ) -> dict:
        """Encrypt and store query text in the PII vault.

        Args:
            conn: asyncpg connection
            audit_entry_id: FK to audit_log entry
            query_text: raw query text to encrypt
            encryption_key_id: identifier for the encryption key used
            encrypt_fn: callable that encrypts str -> bytes
            retention_years: how long to retain (default 10 for Article 12)

        Returns:
            Dict with vault entry fields.
        """
        encrypted = encrypt_fn(query_text)
        retention_until = datetime(
            datetime.now(UTC).year + retention_years,
            datetime.now(UTC).month,
            datetime.now(UTC).day,
            tzinfo=UTC,
        )

        row = await conn.fetchrow(
            _INSERT_SQL,
            audit_entry_id,       # $1
            encrypted,            # $2 (BYTEA)
            encryption_key_id,    # $3
            retention_until,      # $4
        )

        return dict(row)

    async def retrieve(
        self,
        conn,
        audit_entry_id: UUID,
        decrypt_fn: Callable[[bytes], str],
    ) -> str | None:
        """Retrieve and decrypt PII from the vault.

        Returns None if:
          - No entry exists for this audit_entry_id
          - Entry has been soft-deleted (GDPR erasure)

        Args:
            conn: asyncpg connection
            audit_entry_id: FK to audit_log entry
            decrypt_fn: callable that decrypts bytes -> str
        """
        row = await conn.fetchrow(_SELECT_BY_AUDIT_ENTRY_SQL, audit_entry_id)

        if row is None:
            return None

        if row["deleted_at"] is not None:
            return None

        return decrypt_fn(row["query_text_encrypted"])

    async def delete(self, conn, audit_entry_id: UUID) -> None:
        """Soft-delete PII vault entry (GDPR erasure).

        Sets deleted_at timestamp. The audit_log entry remains intact
        (with query_hash) for Article 12 compliance.
        """
        await conn.execute(_SOFT_DELETE_SQL, audit_entry_id)

    async def is_deleted(self, conn, audit_entry_id: UUID) -> bool:
        """Check if a PII vault entry has been soft-deleted.

        Returns False if entry doesn't exist or hasn't been deleted.
        """
        deleted_at = await conn.fetchval(_IS_DELETED_SQL, audit_entry_id)
        return deleted_at is not None

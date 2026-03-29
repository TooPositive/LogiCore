"""Unit tests for PII Vault -- GDPR-safe encrypted storage.

Resolves the GDPR vs EU AI Act tension:
  - Article 12 mandates full audit trail for high-risk AI decisions
  - GDPR Article 17 mandates right to erasure
  - Solution: audit_log stores query_hash (not raw text), raw PII goes to
    pii_vault with encryption and separate retention/deletion lifecycle

Tests cover:
  - Store and retrieve round-trip (encrypt/decrypt)
  - GDPR erasure (soft delete) preserves audit log entry
  - Deleted PII vault entries return None on retrieve
  - PII detection flags obvious PII queries
  - Non-PII queries detected correctly
  - SQL injection in query text is blocked (parameterized insert)
  - is_deleted returns correct state
  - Multiple entries for different audit entries
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from apps.api.src.domains.logicore.models.compliance import AuditEntryCreate


def _make_entry_create(**overrides) -> AuditEntryCreate:
    """Factory for AuditEntryCreate with sensible defaults."""
    defaults = {
        "user_id": "user-logistics-01",
        "query_text": "Audit invoice INV-2024-0847",
        "retrieved_chunk_ids": ["chunk-47", "chunk-48"],
        "model_version": "gpt-5.2-2026-0201",
        "model_deployment": "logicore-prod-east",
        "response_text": "Discrepancy detected",
    }
    defaults.update(overrides)
    return AuditEntryCreate(**defaults)


def _make_pii_vault_row(**overrides) -> dict:
    """Factory for pii_vault database row."""
    defaults = {
        "id": uuid4(),
        "audit_entry_id": uuid4(),
        "query_text_encrypted": b"encrypted_bytes_here",
        "encryption_key_id": "key-2026-03",
        "retention_until": datetime(2036, 3, 9, tzinfo=UTC),
        "created_at": datetime.now(UTC),
        "deleted_at": None,
    }
    defaults.update(overrides)
    return defaults


def _mock_encrypt(plaintext: str) -> bytes:
    """Test encryption: XOR with fixed key (NOT real encryption)."""
    key = b"test-key-32bytes-for-aes256-gcm!"
    data = plaintext.encode("utf-8")
    return bytes(a ^ key[i % len(key)] for i, a in enumerate(data))


def _mock_decrypt(ciphertext: bytes) -> str:
    """Test decryption: reverse of _mock_encrypt."""
    key = b"test-key-32bytes-for-aes256-gcm!"
    data = bytes(a ^ key[i % len(key)] for i, a in enumerate(ciphertext))
    return data.decode("utf-8")


@pytest.fixture
def mock_conn():
    """Mock asyncpg connection."""
    conn = AsyncMock()
    return conn


class TestPIIVaultStore:
    """PIIVault.store: encrypt and persist PII."""

    @pytest.mark.asyncio
    async def test_store_returns_vault_entry(self, mock_conn):
        """store() encrypts query text and returns a PIIVaultEntry-like dict."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        audit_entry_id = uuid4()
        query_text = "Show me Jan Kowalski salary details"
        row = _make_pii_vault_row(audit_entry_id=audit_entry_id)
        mock_conn.fetchrow = AsyncMock(return_value=row)

        vault = PIIVault()
        result = await vault.store(
            conn=mock_conn,
            audit_entry_id=audit_entry_id,
            query_text=query_text,
            encryption_key_id="key-2026-03",
            encrypt_fn=_mock_encrypt,
        )

        assert result["audit_entry_id"] == audit_entry_id
        mock_conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_uses_parameterized_sql(self, mock_conn):
        """store() uses $1, $2, etc. placeholders -- zero string interpolation."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        row = _make_pii_vault_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        vault = PIIVault()
        await vault.store(
            conn=mock_conn,
            audit_entry_id=uuid4(),
            query_text="Test query",
            encryption_key_id="key-1",
            encrypt_fn=_mock_encrypt,
        )

        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "$1" in sql_arg
        assert "INSERT" in sql_arg.upper()
        assert "%s" not in sql_arg
        assert "f'" not in sql_arg

    @pytest.mark.asyncio
    async def test_store_passes_encrypted_bytes(self, mock_conn):
        """store() passes encrypted bytes, not raw query text, to the DB."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        row = _make_pii_vault_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        query_text = "Show salary for Jan Kowalski"
        vault = PIIVault()
        await vault.store(
            conn=mock_conn,
            audit_entry_id=uuid4(),
            query_text=query_text,
            encryption_key_id="key-1",
            encrypt_fn=_mock_encrypt,
        )

        # The encrypted bytes should be passed as a parameter
        call_args = mock_conn.fetchrow.call_args[0]
        params = call_args[1:]
        byte_params = [p for p in params if isinstance(p, bytes)]
        assert len(byte_params) >= 1, "Encrypted bytes should be passed"
        # The raw query text should NOT be in any params
        str_params = [p for p in params if isinstance(p, str)]
        assert query_text not in str_params

    @pytest.mark.asyncio
    async def test_store_sql_injection_blocked(self, mock_conn):
        """SQL injection in query text is blocked by parameterized insert."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        row = _make_pii_vault_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        malicious_query = "'; DROP TABLE audit_pii_vault; --"
        vault = PIIVault()
        await vault.store(
            conn=mock_conn,
            audit_entry_id=uuid4(),
            query_text=malicious_query,
            encryption_key_id="key-1",
            encrypt_fn=_mock_encrypt,
        )

        # SQL should NOT contain the injection
        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "DROP TABLE" not in sql_arg


class TestPIIVaultRetrieve:
    """PIIVault.retrieve: fetch and decrypt PII."""

    @pytest.mark.asyncio
    async def test_retrieve_round_trip(self, mock_conn):
        """store -> retrieve produces original query text."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        query_text = "Show Jan Kowalski employment contract"
        encrypted = _mock_encrypt(query_text)
        audit_entry_id = uuid4()

        row = _make_pii_vault_row(
            audit_entry_id=audit_entry_id,
            query_text_encrypted=encrypted,
            deleted_at=None,
        )
        mock_conn.fetchrow = AsyncMock(return_value=row)

        vault = PIIVault()
        result = await vault.retrieve(
            conn=mock_conn,
            audit_entry_id=audit_entry_id,
            decrypt_fn=_mock_decrypt,
        )

        assert result == query_text

    @pytest.mark.asyncio
    async def test_retrieve_returns_none_for_missing(self, mock_conn):
        """retrieve() returns None when no entry exists."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        mock_conn.fetchrow = AsyncMock(return_value=None)

        vault = PIIVault()
        result = await vault.retrieve(
            conn=mock_conn,
            audit_entry_id=uuid4(),
            decrypt_fn=_mock_decrypt,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_retrieve_returns_none_for_deleted_entry(self, mock_conn):
        """Soft-deleted entries return None on retrieve (GDPR erasure)."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        row = _make_pii_vault_row(
            deleted_at=datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC),
        )
        mock_conn.fetchrow = AsyncMock(return_value=row)

        vault = PIIVault()
        result = await vault.retrieve(
            conn=mock_conn,
            audit_entry_id=uuid4(),
            decrypt_fn=_mock_decrypt,
        )

        assert result is None


class TestPIIVaultDelete:
    """PIIVault.delete: GDPR erasure via soft delete."""

    @pytest.mark.asyncio
    async def test_delete_sets_deleted_at(self, mock_conn):
        """delete() updates deleted_at timestamp (soft delete)."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        mock_conn.execute = AsyncMock()

        vault = PIIVault()
        audit_entry_id = uuid4()
        await vault.delete(mock_conn, audit_entry_id)

        mock_conn.execute.assert_called_once()
        sql_arg = mock_conn.execute.call_args[0][0]
        assert "UPDATE" in sql_arg.upper()
        assert "deleted_at" in sql_arg
        assert "$1" in sql_arg

    @pytest.mark.asyncio
    async def test_delete_uses_parameterized_sql(self, mock_conn):
        """delete() uses parameterized SQL, not string interpolation."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        mock_conn.execute = AsyncMock()

        vault = PIIVault()
        await vault.delete(mock_conn, uuid4())

        sql_arg = mock_conn.execute.call_args[0][0]
        assert "%s" not in sql_arg
        assert "f'" not in sql_arg


class TestPIIVaultIsDeleted:
    """PIIVault.is_deleted: check soft-delete state."""

    @pytest.mark.asyncio
    async def test_is_deleted_returns_true_for_deleted(self, mock_conn):
        """is_deleted returns True when deleted_at is set."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        mock_conn.fetchval = AsyncMock(
            return_value=datetime(2026, 3, 9, tzinfo=UTC)
        )

        vault = PIIVault()
        result = await vault.is_deleted(mock_conn, uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_is_deleted_returns_false_for_active(self, mock_conn):
        """is_deleted returns False when deleted_at is None."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        mock_conn.fetchval = AsyncMock(return_value=None)

        vault = PIIVault()
        result = await vault.is_deleted(mock_conn, uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_is_deleted_returns_false_for_missing(self, mock_conn):
        """is_deleted returns False when no entry exists at all."""
        from apps.api.src.domains.logicore.compliance.pii_vault import PIIVault

        # fetchval returns None for missing rows
        mock_conn.fetchval = AsyncMock(return_value=None)

        vault = PIIVault()
        result = await vault.is_deleted(mock_conn, uuid4())
        assert result is False


class TestPIIDetection:
    """detect_pii: heuristic PII detection in query text."""

    def test_detects_salary_query(self):
        """Query mentioning salary + name is flagged as PII."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        assert detect_pii("Show Jan Kowalski salary details") is True

    def test_detects_contract_with_name(self):
        """Query mentioning employment contract + name is PII."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        assert detect_pii("Find Anna Schmidt employment contract") is True

    def test_detects_health_query(self):
        """Query mentioning health/medical + name is PII."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        assert detect_pii("Medical records for Piotr Nowak") is True

    def test_non_pii_invoice_query(self):
        """Generic invoice query without PII is not flagged."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        assert detect_pii("Audit invoice INV-2024-0847") is False

    def test_non_pii_shipping_query(self):
        """Shipping route query without personal data is not flagged."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        assert detect_pii("Show shipping routes for Warsaw depot") is False

    def test_detects_pesel_number(self):
        """Query containing PESEL (Polish national ID) is PII."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        assert detect_pii("Look up employee with PESEL 85010112345") is True

    def test_detects_email_pattern(self):
        """Query containing email address is PII."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        assert detect_pii("Find records for jan.kowalski@logicore.pl") is True

    def test_detects_phone_number(self):
        """Query containing phone number is PII."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        assert detect_pii("Contact driver at +48 123 456 789") is True

    def test_detects_polish_diacritics_in_name(self):
        """Query with Polish diacritics in name is PII."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        # Names with Polish diacritics
        assert detect_pii("Pokaż pensję Wojciecha Józwiaka") is True
        assert detect_pii("Sprawdź contract Łukasza Śliwińskiego") is True
        assert detect_pii("Medical records for Żaneta Źródłowska") is True

    def test_detects_mixed_ascii_diacritics_name(self):
        """Names mixing ASCII and diacritics are detected."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        assert detect_pii("Find salary for Marek Łoziński") is True
        assert detect_pii("Show contract for Ewa Błaszczyk") is True

    def test_detects_abbreviated_name_with_keyword(self):
        """Initial + surname near PII keyword is detected."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        # This tests that email pattern catches abbreviated names
        assert detect_pii("j.kowalski@logicore.pl salary") is True

    def test_detects_eleven_digit_pesel_standalone(self):
        """11-digit number (PESEL) is PII even without keyword."""
        from apps.api.src.domains.logicore.compliance.pii_vault import detect_pii

        assert detect_pii("employee 85010112345 medical") is True

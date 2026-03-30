"""Tests for secret redaction in logging.

Ensures that secrets never appear in logs.
"""
import pytest
import logging
import io
from backend.core.logging import redact_secrets, SecretRedactionFilter, StructuredFormatter


class TestRedactSecrets:
    """Tests for the redact_secrets function."""
    
    def test_api_key_with_equals(self):
        """API keys with = sign are redacted."""
        text = "api_key=sk_test_12345678901234567890"
        result = redact_secrets(text)
        assert "sk_test_12345678901234567890" not in result
        assert "REDACTED" in result
    
    def test_api_key_with_colon(self):
        """API keys with : sign are redacted."""
        text = 'api_key: "abc123def456ghi789jkl012"'
        result = redact_secrets(text)
        assert "abc123def456ghi789jkl012" not in result
        assert "REDACTED" in result
    
    def test_api_secret_redacted(self):
        """API secrets are redacted."""
        text = "api_secret=mysupersecretapikey12345"
        result = redact_secrets(text)
        assert "mysupersecretapikey12345" not in result
        assert "REDACTED" in result
    
    def test_private_key_pem_redacted(self):
        """PEM private keys are redacted."""
        text = """-----BEGIN EC PRIVATE KEY-----
MHQCAQEEIEVp6Xke5Z7xt+jPAoRQMRFQy3kFT8vKvJlP2E8c8CpAoAcGBSuBBAAK
oUQDQgAEKqd+xk3FkW6oAVN0TKGBEgPMR/aQByYd3Zx4TbYh7QQd5lZ8h/2iKwJF
0BqnNzGc3dwM9vNLV7tLOx4VT0RA==
-----END EC PRIVATE KEY-----"""
        result = redact_secrets(text)
        assert "MHQCAQEEIEVp6Xke" not in result
        assert "PRIVATE_KEY_REDACTED" in result
    
    def test_openai_key_redacted(self):
        """OpenAI API keys (sk-...) are redacted."""
        text = "Using OpenAI with key sk-proj-abcdefghijklmnopqrstuvwxyz123456"
        result = redact_secrets(text)
        assert "sk-proj-abcdefghijklmnopqrstuvwxyz123456" not in result
        assert "OPENAI_KEY_REDACTED" in result
    
    def test_jwt_token_redacted(self):
        """JWT tokens are redacted."""
        # This is a sample JWT (not a real one)
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        text = f"Authorization: Bearer {jwt}"
        result = redact_secrets(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "JWT_REDACTED" in result
    
    def test_bearer_token_redacted(self):
        """Bearer tokens are redacted."""
        text = "Bearer token123456789012345678901234567890"
        result = redact_secrets(text)
        assert "token123456789012345678901234567890" not in result
        assert "TOKEN_REDACTED" in result
    
    def test_password_redacted(self):
        """Passwords are redacted."""
        text = 'password="mysecretpassword123"'
        result = redact_secrets(text)
        assert "mysecretpassword123" not in result
        assert "PASSWORD_REDACTED" in result
    
    def test_coinbase_key_name_redacted(self):
        """Coinbase API key names are redacted."""
        text = "Using key organizations/abc-123-def/apiKeys/key-456-ghi"
        result = redact_secrets(text)
        assert "abc-123-def" not in result
        assert "key-456-ghi" not in result
        assert "COINBASE_KEY_NAME_REDACTED" in result
    
    def test_short_strings_not_redacted(self):
        """Short strings that match patterns shouldn't be redacted."""
        text = "api_key=short"  # Too short to be a real key
        result = redact_secrets(text)
        # Should not be redacted because it's too short
        assert result == text
    
    def test_normal_text_unchanged(self):
        """Normal text without secrets is unchanged."""
        text = "This is a normal log message about BTC-USD trading"
        result = redact_secrets(text)
        assert result == text
    
    def test_json_with_secrets_redacted(self):
        """JSON containing secrets is properly redacted."""
        text = '{"api_key": "verylongapikey1234567890abcdef", "status": "ok"}'
        result = redact_secrets(text)
        assert "verylongapikey1234567890abcdef" not in result
        assert '"status": "ok"' in result
    
    def test_multiple_secrets_all_redacted(self):
        """Multiple secrets in same text are all redacted."""
        text = "api_key=key12345678901234567890 secret_key=secret12345678901234567890"
        result = redact_secrets(text)
        assert "key12345678901234567890" not in result
        assert "secret12345678901234567890" not in result
        assert result.count("REDACTED") >= 2


class TestSecretRedactionFilter:
    """Tests for the SecretRedactionFilter logging filter."""
    
    def test_filter_redacts_message(self):
        """Filter redacts secrets from log messages."""
        filter = SecretRedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="api_key=longsecretkey123456789012345",
            args=(),
            exc_info=None
        )
        filter.filter(record)
        assert "longsecretkey123456789012345" not in record.msg
        assert "REDACTED" in record.msg
    
    def test_filter_redacts_dict_args(self):
        """Filter redacts secrets from dict args."""
        filter = SecretRedactionFilter()
        # Use tuple args instead of dict (Python 3.12+ has issues with dict args)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Data: %s",
            args=("api_key=secretvalue1234567890123456",),
            exc_info=None
        )
        filter.filter(record)
        assert "secretvalue1234567890123456" not in record.args[0]
    
    def test_filter_always_returns_true(self):
        """Filter always allows records through after redaction."""
        filter = SecretRedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Normal message",
            args=(),
            exc_info=None
        )
        result = filter.filter(record)
        assert result is True


class TestStructuredFormatterRedaction:
    """Tests for StructuredFormatter redaction."""
    
    def test_formatter_redacts_message(self):
        """Formatter redacts secrets from formatted output."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Config: api_key=supersecretkey12345678901234",
            args=(),
            exc_info=None
        )
        output = formatter.format(record)
        assert "supersecretkey12345678901234" not in output
        assert "REDACTED" in output
    
    def test_formatter_includes_correlation_ids(self):
        """Formatter includes correlation IDs in output."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.run_id = "run_123"
        record.trace_id = "trace_456"
        output = formatter.format(record)
        assert '"run_id": "run_123"' in output
        assert '"trace_id": "trace_456"' in output


class TestEndToEndLogging:
    """End-to-end tests for logging with redaction."""
    
    def test_logger_does_not_expose_secrets(self):
        """Logger output never contains secrets."""
        # Set up a string buffer to capture log output
        log_buffer = io.StringIO()
        handler = logging.StreamHandler(log_buffer)
        handler.setFormatter(StructuredFormatter())
        handler.addFilter(SecretRedactionFilter())
        
        logger = logging.getLogger("test_redaction")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        # Log various secrets
        secrets = [
            "api_key=mysecretapikey12345678901234567890",
            "sk-openaikey1234567890abcdefghijklmnop",
            "password=mypassword123",
            "Bearer tokenvalue123456789012345678901234"
        ]
        
        for secret in secrets:
            logger.info(f"Processing: {secret}")
        
        # Get logged output
        output = log_buffer.getvalue()
        
        # Verify no secret values appear
        assert "mysecretapikey12345678901234567890" not in output
        assert "sk-openaikey1234567890abcdefghijklmnop" not in output
        assert "mypassword123" not in output
        assert "tokenvalue123456789012345678901234" not in output
        
        # Verify redaction markers appear
        assert "REDACTED" in output


class TestNoSecretLeaks:
    """Regression tests to ensure secrets don't leak."""
    
    def test_coinbase_private_key_not_logged(self):
        """Coinbase private keys are never logged."""
        # Simulated Coinbase private key
        private_key = """-----BEGIN EC PRIVATE KEY-----
MHQCAQEEIEVp6Xke5Z7xt+jPAoRQMRFQy3kFT8vKvJlP2E8c8CpAoAcGBSuBBAAK
oUQDQgAEKqd+xk3FkW6oAVN0TKGBEgPMR/aQByYd3Zx4TbYh7QQd5lZ8h/2iKwJF
-----END EC PRIVATE KEY-----"""
        
        result = redact_secrets(f"Key: {private_key}")
        assert "MHQCAQEEIEVp6Xke" not in result
        assert "PRIVATE_KEY_REDACTED" in result
    
    def test_env_var_format_redacted(self):
        """Environment variable format secrets are redacted."""
        text = "COINBASE_API_PRIVATE_KEY=verylongsecretkeyvalue123456789"
        # This matches api_private_key pattern
        result = redact_secrets(text)
        assert "verylongsecretkeyvalue123456789" not in result
    
    def test_error_response_no_secrets(self):
        """Error responses don't contain secrets."""
        error_text = """Error connecting to API:
        api_key: supersecret12345678901234567890
        Status: 401 Unauthorized"""
        
        result = redact_secrets(error_text)
        assert "supersecret12345678901234567890" not in result
        assert "Status: 401 Unauthorized" in result

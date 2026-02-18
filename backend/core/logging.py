"""Structured logging with secret redaction.

Provides JSON-formatted logs with:
- Correlation IDs (run_id, trace_id, request_id, tenant_id)
- Automatic secret redaction for API keys, private keys, tokens
"""
import logging
import sys
import json
import re
from datetime import datetime
from typing import Optional

# === SECRET REDACTION PATTERNS ===
# These patterns match common secret formats and redact them from logs

SECRET_PATTERNS = [
    # Private keys (PEM format) - check first for multi-line patterns
    (
        r'-----BEGIN[A-Z ]+PRIVATE KEY-----[\s\S]*?-----END[A-Z ]+PRIVATE KEY-----',
        '***PRIVATE_KEY_REDACTED***'
    ),
    # OpenAI API keys (sk-... including sk-proj-...)
    (
        r'\bsk-[a-zA-Z0-9_-]{20,}\b',
        '***OPENAI_KEY_REDACTED***'
    ),
    # JWT tokens (eyJ...)
    (
        r'\beyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b',
        '***JWT_REDACTED***'
    ),
    # Generic tokens: token=value, bearer token, etc.
    (
        r'(?i)(bearer\s+|token["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-\.\/+]{20,})["\']?',
        r'\1***TOKEN_REDACTED***'
    ),
    # Password patterns
    (
        r'(?i)(password|passwd|pwd)["\']?\s*[:=]\s*["\']?([^\s"\']+)["\']?',
        r'\1=***PASSWORD_REDACTED***'
    ),
    # Coinbase API key names (organizations/xxx/apiKeys/xxx)
    (
        r'organizations/[a-zA-Z0-9-]+/apiKeys/[a-zA-Z0-9-]+',
        '***COINBASE_KEY_NAME_REDACTED***'
    ),
    # Environment variable format (COINBASE_API_KEY=value, API_PRIVATE_KEY=value, etc.)
    (
        r'(?i)(COINBASE_[A-Z_]*KEY|API_[A-Z_]*KEY|[A-Z_]*SECRET|[A-Z_]*PRIVATE_KEY)\s*=\s*([a-zA-Z0-9_\-\.\/+]{16,})',
        r'\1=***REDACTED***'
    ),
    # API keys: api_key=value, apiKey=value, api-key: value, etc.
    (
        r'(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?key)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-\.\/+]{16,})["\']?',
        r'\1=***REDACTED***'
    ),
]

# Compiled patterns for performance
_COMPILED_PATTERNS = [(re.compile(pattern), replacement) for pattern, replacement in SECRET_PATTERNS]


def redact_secrets(text: str) -> str:
    """Redact secrets from text using pattern matching.
    
    Args:
        text: Input text that may contain secrets
        
    Returns:
        Text with secrets replaced by redaction markers
    """
    if not text:
        return text
    
    result = str(text)
    for pattern, replacement in _COMPILED_PATTERNS:
        result = pattern.sub(replacement, result)
    
    return result


class SecretRedactionFilter(logging.Filter):
    """Logging filter that redacts secrets from log messages.
    
    Applies redaction patterns to the log message before it's formatted.
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter and redact the log record.
        
        Args:
            record: The log record to filter
            
        Returns:
            True (always allows the record through after redaction)
        """
        # Redact the message
        if record.msg:
            record.msg = redact_secrets(str(record.msg))
        
        # Redact args if they exist, but preserve types for format specifiers
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: redact_secrets(str(v)) if isinstance(v, str) else v 
                              for k, v in record.args.items()}
            elif isinstance(record.args, (tuple, list)):
                # Only convert strings to redact - preserve int/float for %d/%f formats
                record.args = tuple(
                    redact_secrets(str(arg)) if isinstance(arg, str) else arg 
                    for arg in record.args
                )
        
        return True


class StructuredFormatter(logging.Formatter):
    """JSON formatter with correlation IDs and elapsed time tracking."""
    
    def format(self, record):
        # Redact secrets from the message first
        message = redact_secrets(record.getMessage())
        
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": message,
            "module": record.module,
            "function": record.funcName,
        }
        
        # Add correlation IDs if present
        if hasattr(record, "run_id"):
            log_data["run_id"] = record.run_id
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "tenant_id"):
            log_data["tenant_id"] = record.tenant_id
        
        # Add node name if present
        if hasattr(record, "node"):
            log_data["node"] = record.node
        
        # Add event type if present
        if hasattr(record, "event"):
            log_data["event"] = record.event
        
        # Add elapsed time if present
        if hasattr(record, "elapsed_ms"):
            log_data["elapsed_ms"] = record.elapsed_ms
        
        # Add error class if present
        if hasattr(record, "error_class"):
            log_data["error_class"] = record.error_class
        
        if record.exc_info:
            # Redact secrets from exception info
            exception_text = self.formatException(record.exc_info)
            log_data["exception"] = redact_secrets(exception_text)
            
        return json.dumps(log_data)


def setup_logging(level: str = "INFO"):
    """Setup logging with secret redaction.
    
    Configures structured JSON logging with:
    - Secret redaction filter
    - Correlation ID support
    - Elapsed time tracking
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    
    # Add secret redaction filter
    handler.addFilter(SecretRedactionFilter())
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with secret redaction enabled.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Logger instance with secret redaction
    """
    return logging.getLogger(name)


def test_redaction(sample_text: str) -> str:
    """Test secret redaction (for debugging/testing).
    
    Args:
        sample_text: Text that may contain secrets
        
    Returns:
        Redacted text
    """
    return redact_secrets(sample_text)

"""Environment variable utilities with secret handling and PEM normalization."""
import os
from typing import Optional
from pathlib import Path


def get_env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Safely get environment variable as string.
    
    Args:
        name: Environment variable name
        default: Default value if not set
        
    Returns:
        Environment variable value or default
    """
    return os.getenv(name, default)


def load_pem_from_path(path: str) -> str:
    """
    Load PEM key from file path.
    
    Args:
        path: Path to PEM file
        
    Returns:
        Normalized PEM content
        
    Raises:
        ValueError: If file doesn't exist or is invalid (message never includes PEM content)
    """
    pem_path = Path(path)
    
    if not pem_path.exists():
        raise ValueError(f"PEM file not found at path: {path}")
    
    if not pem_path.is_file():
        raise ValueError(f"PEM path is not a file: {path}")
    
    try:
        # Read file, handle BOM, normalize newlines
        with open(pem_path, 'r', encoding='utf-8-sig') as f:
            pem_content = f.read()
        
        # Normalize line endings to \n
        pem_content = pem_content.replace('\r\n', '\n').replace('\r', '\n')
        
        return normalize_pem(pem_content)
    except Exception as e:
        raise ValueError(f"Failed to read PEM file at {path}: {type(e).__name__}") from e


def normalize_pem(pem: str) -> str:
    """
    Normalize PEM key format.
    
    Converts literal "\\n" strings to actual newlines, strips quotes,
    and ensures proper formatting.
    
    Args:
        pem: Raw PEM string (may have escaped newlines or literal newlines)
        
    Returns:
        Normalized PEM with actual newlines
        
    Raises:
        ValueError: If PEM is invalid (message never includes PEM content)
    """
    if not pem:
        raise ValueError("PEM content is empty")
    
    # Strip surrounding quotes if present
    pem = pem.strip()
    if (pem.startswith('"') and pem.endswith('"')) or (pem.startswith("'") and pem.endswith("'")):
        pem = pem[1:-1]
    
    # Convert literal \n to actual newlines
    if '\\n' in pem:
        pem = pem.replace('\\n', '\n')
    
    # Ensure trailing newline
    if not pem.endswith('\n'):
        pem += '\n'
    
    # Validate PEM markers present
    if 'BEGIN' not in pem or 'END' not in pem:
        raise ValueError("Invalid PEM format: missing BEGIN/END markers")
    
    return pem


def get_coinbase_private_key() -> str:
    """
    Get Coinbase private key from environment with fallback logic.
    
    Priority:
    1. COINBASE_API_PRIVATE_KEY_PATH (file-based, recommended)
    2. COINBASE_API_PRIVATE_KEY (environment variable)
    
    Returns:
        Normalized PEM private key
        
    Raises:
        ValueError: If key is missing or invalid (message never includes key content)
    """
    # Try file-based path first (recommended)
    key_path = get_env_str("COINBASE_API_PRIVATE_KEY_PATH")
    if key_path:
        try:
            return load_pem_from_path(key_path)
        except ValueError as e:
            raise ValueError(f"Failed to load Coinbase private key from path: {e}") from e
    
    # Fallback to environment variable
    key_env = get_env_str("COINBASE_API_PRIVATE_KEY")
    if key_env:
        try:
            return normalize_pem(key_env)
        except ValueError as e:
            raise ValueError(f"Failed to normalize Coinbase private key from environment: {e}") from e
    
    # Neither source available
    raise ValueError(
        "Coinbase private key not configured. "
        "Set COINBASE_API_PRIVATE_KEY_PATH (recommended) or COINBASE_API_PRIVATE_KEY"
    )


def detect_real_keys() -> dict:
    """
    Detect if real API keys appear to be present in environment.
    
    Returns:
        Dict with detection results (never includes actual key values):
        {
            "openai_key_present": bool,
            "coinbase_key_present": bool,
            "any_real_keys": bool
        }
    """
    openai_key = get_env_str("OPENAI_API_KEY", "")
    coinbase_key = get_env_str("COINBASE_API_PRIVATE_KEY", "")
    coinbase_path = get_env_str("COINBASE_API_PRIVATE_KEY_PATH", "")
    
    # Detect OpenAI key (starts with sk-)
    openai_looks_real = openai_key.startswith("sk-")
    
    # Detect Coinbase key (contains BEGIN marker or path is set)
    coinbase_looks_real = "BEGIN" in coinbase_key or bool(coinbase_path)
    
    return {
        "openai_key_present": openai_looks_real,
        "coinbase_key_present": coinbase_looks_real,
        "any_real_keys": openai_looks_real or coinbase_looks_real
    }

"""ID generation utilities."""
import uuid


def new_id(prefix: str) -> str:
    """Generate a UUID4-based ID with prefix."""
    return f"{prefix}{uuid.uuid4().hex}"

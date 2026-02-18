"""Structured error codes for trade execution failures.

Provides semantic error codes that can be used for:
- User-facing error messages with remediation
- Monitoring and alerting
- Error categorization and analysis
"""
from enum import Enum


class TradeErrorCode(str, Enum):
    """Error codes for trade execution failures."""
    
    # Product metadata errors
    PRODUCT_DETAILS_UNAVAILABLE = "PRODUCT_DETAILS_UNAVAILABLE"
    PRODUCT_API_TIMEOUT = "PRODUCT_API_TIMEOUT"
    PRODUCT_API_RATE_LIMITED = "PRODUCT_API_RATE_LIMITED"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    
    # Balance and validation errors
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    BELOW_MINIMUM_SIZE = "BELOW_MINIMUM_SIZE"
    INVALID_PRECISION = "INVALID_PRECISION"
    
    # Order placement errors
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_TIMEOUT = "ORDER_TIMEOUT"
    BROKER_API_ERROR = "BROKER_API_ERROR"
    
    # Execution errors
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    
    # Configuration errors
    CREDENTIALS_MISSING = "CREDENTIALS_MISSING"
    LIVE_TRADING_DISABLED = "LIVE_TRADING_DISABLED"
    
    # Generic errors
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class TradeErrorException(Exception):
    """Exception with structured error code and message."""
    
    def __init__(
        self,
        error_code: TradeErrorCode,
        message: str,
        remediation: str = None,
        details: dict = None
    ):
        """Initialize trade error exception.
        
        Args:
            error_code: Structured error code
            message: Human-readable error message
            remediation: Optional remediation steps
            details: Optional additional error details
        """
        self.error_code = error_code
        self.message = message
        self.remediation = remediation
        self.details = details or {}
        super().__init__(message)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "code": self.error_code.value,
            "message": self.message,
            "remediation": self.remediation,
            "details": self.details
        }


# Error code to user-friendly message mapping
ERROR_CODE_MESSAGES = {
    TradeErrorCode.PRODUCT_DETAILS_UNAVAILABLE: {
        "message": "Unable to fetch product metadata required for order precision",
        "remediation": "Check Coinbase API connectivity and credentials. The system will retry automatically."
    },
    TradeErrorCode.PRODUCT_API_TIMEOUT: {
        "message": "Coinbase API request timed out while fetching product details",
        "remediation": "Check network connectivity. The system will retry with exponential backoff."
    },
    TradeErrorCode.PRODUCT_API_RATE_LIMITED: {
        "message": "Rate limited by Coinbase API",
        "remediation": "Wait a few seconds and try again. The system will retry automatically."
    },
    TradeErrorCode.PRODUCT_NOT_FOUND: {
        "message": "Product not found on Coinbase",
        "remediation": "Verify the symbol is correct and supported by Coinbase Advanced Trade."
    },
    TradeErrorCode.INSUFFICIENT_BALANCE: {
        "message": "Insufficient balance to place order",
        "remediation": "Deposit funds or reduce order size."
    },
    TradeErrorCode.BELOW_MINIMUM_SIZE: {
        "message": "Order size below exchange minimum",
        "remediation": "Increase order size to meet minimum requirements."
    },
    TradeErrorCode.INVALID_PRECISION: {
        "message": "Order size does not match required precision",
        "remediation": "Adjust order size to match exchange precision requirements."
    },
    TradeErrorCode.ORDER_REJECTED: {
        "message": "Order rejected by exchange",
        "remediation": "Check order parameters and account status."
    },
    TradeErrorCode.ORDER_TIMEOUT: {
        "message": "Order placement timed out",
        "remediation": "Check network connectivity and try again."
    },
    TradeErrorCode.BROKER_API_ERROR: {
        "message": "Broker API error",
        "remediation": "Check broker status and API credentials."
    },
    TradeErrorCode.EXECUTION_TIMEOUT: {
        "message": "Trade execution timed out",
        "remediation": "Check system status and try again."
    },
    TradeErrorCode.EXECUTION_FAILED: {
        "message": "Trade execution failed",
        "remediation": "Check error details and system logs."
    },
    TradeErrorCode.CREDENTIALS_MISSING: {
        "message": "API credentials not configured",
        "remediation": "Set COINBASE_API_KEY_NAME and COINBASE_API_PRIVATE_KEY environment variables."
    },
    TradeErrorCode.LIVE_TRADING_DISABLED: {
        "message": "LIVE trading is disabled",
        "remediation": "Set TRADING_DISABLE_LIVE=false and ENABLE_LIVE_TRADING=true, then restart."
    },
    TradeErrorCode.VALIDATION_ERROR: {
        "message": "Order validation failed",
        "remediation": "Check order parameters and try again."
    },
    TradeErrorCode.UNKNOWN_ERROR: {
        "message": "An unexpected error occurred",
        "remediation": "Check system logs for details."
    }
}


def get_error_message(error_code: TradeErrorCode) -> dict:
    """Get user-friendly message and remediation for error code.
    
    Args:
        error_code: Trade error code
        
    Returns:
        Dictionary with message and remediation
    """
    return ERROR_CODE_MESSAGES.get(
        error_code,
        {
            "message": "An error occurred",
            "remediation": "Contact support if the issue persists."
        }
    )

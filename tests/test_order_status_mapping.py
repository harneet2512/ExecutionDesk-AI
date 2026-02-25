"""Unit tests for canonical order status mapping."""

from backend.orchestrator.state_machine import (
    OrderStatus,
    TERMINAL_ORDER_STATUSES,
    FILL_CONFIRMED_STATUSES,
)


def test_order_status_enum_contains_required_states():
    required = {
        "SUBMITTED",
        "PENDING_FILL",
        "OPEN",
        "PARTIALLY_FILLED",
        "FILLED",
        "FAILED",
        "REJECTED",
        "CANCELED",
        "EXPIRED",
        "TIMEOUT",
    }
    actual = {s.value for s in OrderStatus}
    assert required.issubset(actual)


def test_pending_statuses_are_not_fill_confirmed():
    assert OrderStatus.SUBMITTED not in FILL_CONFIRMED_STATUSES
    assert OrderStatus.PENDING_FILL not in FILL_CONFIRMED_STATUSES
    assert OrderStatus.OPEN not in FILL_CONFIRMED_STATUSES
    assert OrderStatus.PARTIALLY_FILLED not in FILL_CONFIRMED_STATUSES


def test_only_filled_is_fill_confirmed():
    assert OrderStatus.FILLED in FILL_CONFIRMED_STATUSES
    assert len(FILL_CONFIRMED_STATUSES) == 1


def test_terminal_statuses_include_expected_end_states():
    assert OrderStatus.FILLED in TERMINAL_ORDER_STATUSES
    assert OrderStatus.REJECTED in TERMINAL_ORDER_STATUSES
    assert OrderStatus.FAILED in TERMINAL_ORDER_STATUSES
    assert OrderStatus.CANCELED in TERMINAL_ORDER_STATUSES
    assert OrderStatus.EXPIRED in TERMINAL_ORDER_STATUSES

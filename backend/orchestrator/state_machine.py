"""Run and confirmation state machines.

Defines the canonical lifecycle states for runs and trade confirmations,
along with validated transitions. All status updates MUST go through
these enums and guards.
"""
from enum import Enum


class RunStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ConfirmationStatus(str, Enum):
    """Canonical confirmation lifecycle states."""
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class NodeStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ---- Transition tables ----

_RUN_TRANSITIONS: dict[RunStatus, list[RunStatus]] = {
    RunStatus.CREATED: [RunStatus.RUNNING, RunStatus.FAILED],
    RunStatus.RUNNING: [RunStatus.PAUSED, RunStatus.COMPLETED, RunStatus.FAILED],
    RunStatus.PAUSED: [RunStatus.RUNNING, RunStatus.FAILED],
    RunStatus.COMPLETED: [],
    RunStatus.FAILED: [],
}

_CONFIRMATION_TRANSITIONS: dict[ConfirmationStatus, list[ConfirmationStatus]] = {
    ConfirmationStatus.PENDING: [
        ConfirmationStatus.CONFIRMED,
        ConfirmationStatus.CANCELLED,
        ConfirmationStatus.EXPIRED,
    ],
    ConfirmationStatus.CONFIRMED: [],   # terminal
    ConfirmationStatus.CANCELLED: [],   # terminal
    ConfirmationStatus.EXPIRED: [],     # terminal
}

TERMINAL_RUN_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED})
TERMINAL_CONFIRMATION_STATUSES = frozenset({
    ConfirmationStatus.CONFIRMED,
    ConfirmationStatus.CANCELLED,
    ConfirmationStatus.EXPIRED,
})


def can_transition(current: RunStatus, next_status: RunStatus) -> bool:
    """Check if a run transition is valid."""
    return next_status in _RUN_TRANSITIONS.get(current, [])


def can_transition_confirmation(
    current: ConfirmationStatus, next_status: ConfirmationStatus
) -> bool:
    """Check if a confirmation transition is valid."""
    return next_status in _CONFIRMATION_TRANSITIONS.get(current, [])


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    def __init__(self, entity_id: str, current: str, attempted: str):
        self.entity_id = entity_id
        self.current = current
        self.attempted = attempted
        super().__init__(
            f"Invalid transition for {entity_id}: {current} -> {attempted}"
        )


def assert_run_transition(run_id: str, current: RunStatus, next_status: RunStatus) -> None:
    """Assert that a run transition is valid, raising InvalidTransitionError otherwise."""
    if not can_transition(current, next_status):
        raise InvalidTransitionError(run_id, current.value, next_status.value)

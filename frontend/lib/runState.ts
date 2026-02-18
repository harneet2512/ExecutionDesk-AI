/**
 * Run state management utilities.
 * Fixes Bug 3: Duplicate/contradictory states (RUNNING + FAILED)
 */

export type RunStatus = 'CREATED' | 'RUNNING' | 'PAUSED' | 'COMPLETED' | 'FAILED';

// Terminal states that cannot transition to any other state
const TERMINAL_STATES: RunStatus[] = ['COMPLETED', 'FAILED'];

// Valid state transitions
const VALID_TRANSITIONS: Record<RunStatus, RunStatus[]> = {
  'CREATED': ['RUNNING', 'FAILED'],
  'RUNNING': ['PAUSED', 'COMPLETED', 'FAILED'],
  'PAUSED': ['RUNNING', 'COMPLETED', 'FAILED'],
  'COMPLETED': [], // Terminal - no transitions allowed
  'FAILED': [],    // Terminal - no transitions allowed
};

/**
 * Check if a run status is terminal (COMPLETED or FAILED).
 */
export function isTerminalStatus(status: string | undefined | null): boolean {
  if (!status) return false;
  return TERMINAL_STATES.includes(status.toUpperCase() as RunStatus);
}

/**
 * Validate if a state transition is allowed.
 * Returns true if the transition is valid, false otherwise.
 */
export function validateRunTransition(from: RunStatus | string, to: RunStatus | string): boolean {
  const fromNorm = from.toUpperCase() as RunStatus;
  const toNorm = to.toUpperCase() as RunStatus;
  
  // Terminal states cannot transition
  if (TERMINAL_STATES.includes(fromNorm)) {
    return false;
  }
  
  const allowed = VALID_TRANSITIONS[fromNorm];
  if (!allowed) return false;
  
  return allowed.includes(toNorm);
}

/**
 * Merge run state ensuring terminal states always win.
 * This prevents contradictory states like "RUNNING + FAILED".
 */
export function mergeRunState(
  prev: Record<string, string>,
  incoming: Record<string, string>
): Record<string, string> {
  const result = { ...prev };
  
  for (const [runId, newStatus] of Object.entries(incoming)) {
    const existingStatus = result[runId];
    
    // If no existing status, accept new status
    if (!existingStatus) {
      result[runId] = newStatus;
      continue;
    }
    
    // If existing is terminal, keep it (terminal states are final)
    if (isTerminalStatus(existingStatus)) {
      continue;
    }
    
    // If new status is terminal, it wins
    if (isTerminalStatus(newStatus)) {
      result[runId] = newStatus;
      continue;
    }
    
    // Neither is terminal, validate the transition
    if (validateRunTransition(existingStatus, newStatus)) {
      result[runId] = newStatus;
    }
    // Otherwise keep existing status
  }
  
  return result;
}

/**
 * Step status type for DAG steps
 */
export type StepStatus = 'pending' | 'running' | 'done' | 'failed';

/**
 * Flush all steps to terminal state when run completes.
 * This prevents "running" steps while the overall run is "FAILED".
 */
export function flushStepsToTerminal<T extends { status: StepStatus }>(
  steps: T[],
  runStatus: string
): T[] {
  const isCompleted = runStatus.toUpperCase() === 'COMPLETED';
  const isFailed = runStatus.toUpperCase() === 'FAILED';
  
  if (!isCompleted && !isFailed) {
    return steps; // Not terminal, don't change
  }
  
  return steps.map(step => {
    // Already in terminal state, keep it
    if (step.status === 'done' || step.status === 'failed') {
      return step;
    }
    
    // Flush to appropriate terminal state
    return {
      ...step,
      status: isCompleted ? 'done' as const : 'failed' as const
    };
  });
}

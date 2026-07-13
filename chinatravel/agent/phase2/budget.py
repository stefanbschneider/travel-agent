"""Per-query time budgeting for the Phase 2 orchestrator.

Splits the total per-query timeout across the four stages and always reserves a hard finalization
buffer so the harness returns a result before the timeout.
"""

from __future__ import annotations

from dataclasses import dataclass

# Default fractions (parse / solve / improve / finalize). Solve gets the largest share.
PARSE_FRAC = 0.25
SOLVE_FRAC = 0.55
IMPROVE_FRAC = 0.10
FINALIZE_FRAC = 0.10

# Absolute hard buffer (seconds) reserved for finalization on comfortably large budgets.
MIN_FINALIZE_BUFFER_SEC = 2.0


@dataclass
class Budget:
    total_sec: float
    parse_sec: float
    solve_sec: float
    improve_sec: float
    finalize_sec: float


def split_budget(total_sec: float) -> Budget:
    """Split ``total_sec`` into stage slices, reserving a hard finalization buffer.

    On large budgets, ``finalize_sec`` is at least ``MIN_FINALIZE_BUFFER_SEC``. On tiny budgets it
    is capped so the slices still sum exactly to ``total_sec``.
    """
    total = max(float(total_sec), 0.0)

    # Reserve finalization first: the larger of the fractional share and the hard buffer, but never
    # more than half the total (so the other stages keep some time on tiny budgets).
    finalize = max(total * FINALIZE_FRAC, min(MIN_FINALIZE_BUFFER_SEC, total * 0.5))
    remaining = max(total - finalize, 0.0)

    denom = PARSE_FRAC + SOLVE_FRAC + IMPROVE_FRAC
    parse = remaining * (PARSE_FRAC / denom)
    solve = remaining * (SOLVE_FRAC / denom)
    improve = remaining * (IMPROVE_FRAC / denom)

    return Budget(
        total_sec=total,
        parse_sec=parse,
        solve_sec=solve,
        improve_sec=improve,
        finalize_sec=finalize,
    )


def dynamic_solve_sec(b: Budget, elapsed_sec: float, *, improve_reserved: bool) -> float:
    """Recompute the solve slice from actual elapsed time instead of the static split.

    Stage 1 (parse) typically finishes in a fraction of its static slice, and the improve slice
    is unused whenever Stage 3 (``llm_refine``) is off -- both flow to the solver instead of being
    thrown away. ``elapsed_sec`` is the wall-clock time actually spent before Stage 2 starts (i.e.
    Stage 1's duration). The finalize reserve is always withheld. Never returns less than the
    static ``b.solve_sec`` would have given (a floor, not just a reallocation).
    """
    improve_reserve = b.improve_sec if improve_reserved else 0.0
    dynamic = b.total_sec - max(elapsed_sec, 0.0) - b.finalize_sec - improve_reserve
    return max(dynamic, b.solve_sec)

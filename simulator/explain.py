"""Explain one placement decision from the allocator's own state.

The engine decides; this module only describes. For ARBF every score comes from
the live allocator itself (``ARBF.cost`` and its history count), read *before* the
decision is made, and the chosen block is always the engine's. The candidate rows
are checked against the engine's choice so a description can never silently
disagree with what the allocator actually did.
"""
from typing import List, Optional, Sequence

from engine.algorithms import ARBF, NextFit
from engine.memory import Block

MAX_ROWS = 8                # candidate rows sent to the UI
EXTRA_OUTSIDE_WINDOW = 2    # ARBF: rows shown beyond the search window, for context

RULES = {
    "first_fit": "Takes the lowest-address free block that fits.",
    "best_fit": "Takes the smallest free block that fits (lowest address among equal sizes).",
    "worst_fit": "Takes the largest free block, if it fits.",
    "next_fit": "First Fit that starts searching at a roving pointer (the end of the previous placement).",
    "arbf": "Scores the leftover r of each candidate by K(r) = r · (2(n+1) − c(r)) and takes the lowest score.",
}


def _row(b: Block, size: int) -> dict:
    return {"addr": b.addr, "size": b.size, "residual": b.size - size}


def candidate_order(allocator, fitting: List[Block], rover: Optional[int] = None) -> List[Block]:
    """Fitting blocks in the order the policy's rule ranks them (display only).
    Next Fit needs the rover as it was before the decision (ALLOC moves it)."""
    name = allocator.name
    if name == "first_fit":
        return sorted(fitting, key=lambda b: b.addr)
    if name == "best_fit":
        return sorted(fitting, key=lambda b: (b.size, b.addr))
    if name == "worst_fit":
        return sorted(fitting, key=lambda b: (-b.size, b.addr))
    if isinstance(allocator, NextFit):
        ordered = sorted(fitting, key=lambda b: b.addr)
        return [b for b in ordered if b.end > rover] + [b for b in ordered if b.end <= rover]
    return fitting


class PreDecision:
    """Allocator state captured immediately before ALLOC(size)."""

    def __init__(self, allocator, free_blocks: Sequence[Block], size: int):
        self.allocator = allocator
        self.size = size
        self.fitting = [b for b in free_blocks if b.size >= size]
        self.rover = allocator.rover if isinstance(allocator, NextFit) else None
        self.arbf = _arbf_scores(allocator, self.fitting, size) if isinstance(allocator, ARBF) else None

    def describe(self, chosen: Optional[Block]) -> dict:
        """Decision record for the UI, given the block the engine actually chose."""
        out = {"rule": RULES.get(self.allocator.name, ""), "fitting_count": len(self.fitting),
               "chosen": None if chosen is None else _row(chosen, self.size)}
        if self.rover is not None:
            out["rover"] = self.rover
        if self.arbf is not None:
            out["arbf"] = _arbf_decision(self.arbf, self.allocator.last_decision, chosen, self.size)
            return out
        ordered = candidate_order(self.allocator, self.fitting, self.rover)
        rows = [_row(b, self.size) for b in ordered[:MAX_ROWS]]
        if chosen is not None and all(r["addr"] != chosen.addr for r in rows):
            rows.append(_row(chosen, self.size))
        for r in rows:
            r["chosen"] = chosen is not None and r["addr"] == chosen.addr
        out["candidates"] = rows
        return out


# --------------------------------------------------------------------- ARBF

def _arbf_scores(allocator: ARBF, fitting: List[Block], size: int) -> dict:
    """One row per distinct fitting size (its lowest-address block — the block ARBF's
    size-ordered scan visits), scored with the allocator's own cost function."""
    n = len(allocator.history)
    reps = {}
    for b in sorted(fitting, key=lambda b: (b.size, b.addr)):
        reps.setdefault(b.size, b)
    rows = []
    for b in reps.values():
        r = b.size - size
        c = allocator._count_le(r)        # c(r): remembered requests that fit in r (read-only)
        rows.append({"addr": b.addr, "size": b.size, "residual": r, "fits": c,
                     "g": c / (n + 1), "weight": 2 - c / (n + 1), "cost": allocator.cost(r)})
    return {"n": n, "rows": rows, "rbf": rows[0]["residual"] if rows else None}


def _arbf_decision(scores: dict, decision, chosen: Optional[Block], size: int) -> dict:
    rows, rbf, path = scores["rows"], scores["rbf"], decision.path
    for row in rows:
        if path == "scan":
            row["evaluated"] = row["residual"] <= 2 * rbf - 1      # P4: the scan stops at r >= 2·r_BF
        else:
            row["evaluated"] = row is rows[0] and path in ("exact", "shortcut")
        row["chosen"] = chosen is not None and row["addr"] == chosen.addr
    evaluated = [r for r in rows if r["evaluated"]]
    expected = min(evaluated, key=lambda r: (r["cost"], r["size"], r["addr"])) if evaluated else None
    consistent = (expected is None and chosen is None) or (
        expected is not None and chosen is not None and expected["addr"] == chosen.addr)

    shown = evaluated[:MAX_ROWS]
    if chosen is not None and not any(r["chosen"] for r in shown):
        shown.append(next(r for r in rows if r["chosen"]))
    outside = [r for r in rows if not r["evaluated"]][:EXTRA_OUTSIDE_WINDOW]
    return {
        "path": path, "n": scores["n"], "rbf": rbf, "window": None if not rbf else 2 * rbf - 1,
        "distinct_sizes": len(rows), "evaluated_count": len(evaluated),
        "count_queries": decision.count_queries,
        "best_fit": None if decision.best_fit is None else _row(decision.best_fit, size),
        "deviated": chosen is not None and decision.best_fit is not None and chosen != decision.best_fit,
        "rows": shown + outside, "consistent": consistent,
        "reason": _reason(path, scores, rows, chosen, size),
    }


def _fits(row: dict, n: int) -> str:
    return f"{row['fits']:,} of the {n:,} remembered request{'s' if n != 1 else ''} (Ĝ = {row['g']:.2f})"


def _reason(path: str, scores: dict, rows: List[dict], chosen: Optional[Block], size: int) -> str:
    """Plain-English account of the decision, assembled only from the scored rows."""
    n = scores["n"]
    if path == "none":
        return f"No free block can hold {size:,} units, so the request fails."
    b0 = rows[0]
    if path == "exact":
        return (f"A free block of exactly {size:,} units exists. It leaves no leftover at all, "
                f"so ARBF takes it — the same block Best Fit takes.")
    if n == 0:
        return ("ARBF has no request history yet, so every leftover is priced by its size alone. "
                f"It takes the tightest block (leftover {b0['residual']:,}) — the same block Best Fit takes.")
    history = f"ARBF remembers {n:,} earlier request{'s' if n != 1 else ''}"
    if path == "shortcut" and b0["residual"] == 1:
        return ("The tightest block leaves a 1-unit leftover. ARBF only considers leftovers below twice that, "
                "so no other block can compete; it takes the Best Fit block.")
    if path == "shortcut":
        r = b0["residual"]
        return (f"{history}. None of them is between {r + 1:,} and {2 * r - 1:,} units, so no block whose leftover "
                f"is below {2 * r:,} can fit more of them than the tightest block's leftover of {r:,}, and a leftover "
                f"of {2 * r:,} or more can never score lower. ARBF takes the Best Fit block without scanning further.")
    chosen_row = next(r for r in rows if chosen is not None and r["addr"] == chosen.addr)
    scanned = sum(1 for r in rows if r["evaluated"]) - 1
    if chosen_row is b0 and scanned == 0:
        return (f"{history}, so it searched for a block whose leftover is below {2 * b0['residual']:,} "
                f"(twice the tightest block's leftover of {b0['residual']:,}). No other free block size falls in "
                f"that window, so it takes the tightest block — the same choice as Best Fit.")
    if chosen_row is b0:
        return (f"{history}. It compared the tightest block — leftover {b0['residual']:,}, which fits {_fits(b0, n)} — with "
                f"{scanned} larger block size{'s' if scanned != 1 else ''} whose leftovers are below "
                f"{2 * b0['residual']:,}. None of those leftovers fits enough recent requests to justify the extra "
                f"size, so the tightest block keeps the lowest score (K = {b0['cost']:,}) — the same choice as "
                f"Best Fit.")
    return (f"{history}. Best Fit would take the {b0['size']:,}-unit block, leaving {b0['residual']:,} units, which fits "
            f"{_fits(b0, n)}. ARBF instead took the {chosen_row['size']:,}-unit block: its leftover of "
            f"{chosen_row['residual']:,} units fits {_fits(chosen_row, n)}. That lowers the learned weight "
            f"(2 − Ĝ) from {b0['weight']:.2f} to {chosen_row['weight']:.2f}, enough to outweigh the larger "
            f"leftover (K = {chosen_row['cost']:,} vs {b0['cost']:,}). ARBF accepted a larger leftover because, "
            f"by its recent history, that leftover is more likely to be reused.")

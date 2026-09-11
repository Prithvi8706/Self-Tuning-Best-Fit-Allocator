"""Experiments: generate one trace, replay it against every requested allocator,
emit one machine-readable record per allocator."""
import json
import math
import platform
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Iterable, List, Optional, Tuple

from engine.algorithms import ALGORITHMS
from engine.memory import Mode, is_int
from framework.generator import GeneratedTrace, generate_trace
from framework.laws import parse_law
from framework.replay import replay
from framework.workloads import Family, custom_family, get_family

SCHEMA = "arbf-bench/1"
ALGORITHMS_BY_NAME = {cls.name: cls for cls in ALGORITHMS}
FIXED_MARGINS = (0.10, 0.25, 0.50)     # preregistered heap margins (frozen spec §19)


@dataclass(frozen=True)
class ExperimentConfig:
    workload: str                       # family name, or "custom" with size_law + lifetime_law
    seed: int
    n_events: int = 400_000
    alloc_prob: float = 1.0
    mode: str = "fixed"                 # "fixed" | "unbounded"
    margin: Optional[float] = None      # FIXED: H = ceil((1 + margin) · trace peak live)
    memory: Optional[int] = None        # FIXED: explicit arena size in units (instead of margin)
    algorithms: Tuple[str, ...] = field(default_factory=lambda: tuple(ALGORITHMS_BY_NAME))
    size_law: Optional[str] = None
    lifetime_law: Optional[str] = None
    check_invariants: bool = False


def resolve_family(cfg: ExperimentConfig) -> Family:
    if cfg.workload == "custom":
        if not (cfg.size_law and cfg.lifetime_law):
            raise ValueError("custom workload needs size_law and lifetime_law")
        return custom_family(parse_law(cfg.size_law), parse_law(cfg.lifetime_law))
    if cfg.size_law or cfg.lifetime_law:
        raise ValueError("size_law / lifetime_law apply only to the custom workload")
    return get_family(cfg.workload)


def resolve_memory(cfg: ExperimentConfig, gt: GeneratedTrace) -> Optional[int]:
    """Arena size H in units for FIXED mode; None for UNBOUNDED."""
    if cfg.mode == "unbounded":
        if cfg.margin is not None or cfg.memory is not None:
            raise ValueError("UNBOUNDED mode takes neither margin nor memory")
        return None
    if cfg.mode != "fixed":
        raise ValueError(f"unknown mode {cfg.mode!r}")
    if (cfg.margin is None) == (cfg.memory is None):
        raise ValueError("FIXED mode needs exactly one of margin or memory")
    if cfg.memory is not None:
        if not is_int(cfg.memory) or cfg.memory < 1:
            raise ValueError(f"memory must be an integer >= 1, got {cfg.memory!r}")
        return cfg.memory
    if not cfg.margin >= 0:
        raise ValueError(f"margin must be >= 0, got {cfg.margin!r}")
    return max(1, math.ceil((1 + Fraction(str(cfg.margin))) * gt.peak_live))   # exact decimal margin


def run_experiment(cfg: ExperimentConfig) -> List[dict]:
    family = resolve_family(cfg)
    unknown = [a for a in cfg.algorithms if a not in ALGORITHMS_BY_NAME]
    if unknown:
        raise ValueError(f"unknown algorithms {unknown}; known: {list(ALGORITHMS_BY_NAME)}")
    gt = generate_trace(family, cfg.seed, cfg.n_events, cfg.alloc_prob)   # once, before any replay
    capacity = resolve_memory(cfg, gt)
    mode = Mode(cfg.mode)
    records = []
    for name in cfg.algorithms:
        measured = replay(ALGORITHMS_BY_NAME[name], gt.events, mode, capacity, cfg.check_invariants)
        records.append({
            "schema": SCHEMA,
            "algorithm": name,
            "workload": family.name,
            "workload_role": family.role,
            "workload_desc": family.description,
            "seed": cfg.seed,
            "mode": cfg.mode,
            "margin": cfg.margin,
            "memory_size": capacity,
            "alloc_prob": gt.alloc_prob,
            "trace_sha256": gt.sha256,
            "trace_peak_live": gt.peak_live,
            "python": platform.python_version(),
            **measured,
        })
    return records


def write_jsonl(records: Iterable[dict], path: str, append: bool = False) -> None:
    with open(path, "a" if append else "w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record, sort_keys=True) + "\n")


def strip_timing(record: dict) -> dict:
    """The record without its wall-clock fields (the only non-deterministic part)."""
    return {k: v for k, v in record.items() if k != "timing"}

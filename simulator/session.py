"""Step-by-step replay of one workload through one engine allocator.

A ``Stepper`` applies events to a fresh engine heap one at a time and reports what
happened (the placed block, the split leftover, the coalesced block, the metrics
after the event). ``Session`` wraps it for the UI: a full timeline computed once,
and per-event frames (heap snapshot + decision) recomputed on demand by replaying
from the start — the engine is deterministic, so seeking backwards is a re-run.

Measurement uses the framework's ``CountingHeap`` and the engine's metric functions,
exactly as ``framework.replay.replay`` does; that function's own record is included
as the authoritative summary of the run.
"""
import itertools
import threading
from collections import OrderedDict
from typing import Dict, List, Optional

from engine.memory import Block, Mode
from engine.metrics import external_fragmentation, is_fragmentation_failure
from engine.trace import Op
from framework.experiment import ALGORITHMS_BY_NAME
from framework.replay import CountingHeap, replay
from simulator.explain import PreDecision
from simulator.workload import Workload

MAX_FRAMES_PER_REQUEST = 200
MAX_SESSIONS = 12


def algorithm_class(name: str):
    try:
        return ALGORITHMS_BY_NAME[name]
    except KeyError:
        raise ValueError(f"unknown algorithm {name!r}; known: {', '.join(ALGORITHMS_BY_NAME)}") from None


def _block(b: Optional[Block]) -> Optional[dict]:
    return None if b is None else {"addr": b.addr, "size": b.size}


class Stepper:
    def __init__(self, workload: Workload, algorithm: str):
        self.workload = workload
        self.heap = CountingHeap(Mode.FIXED, workload.capacity)
        self.allocator = algorithm_class(algorithm)(self.heap)
        self.index = -1                      # last applied event; -1 = initial empty heap
        self.allocs = self.ok = 0

    def metrics(self) -> dict:
        heap = self.heap
        return {"ef": external_fragmentation(heap), "util": heap.live_size / heap.end,
                "largest": heap.largest_free, "free_blocks": heap.free_count,
                "allocated_blocks": heap.allocated_count, "live": heap.live_size,
                "total_free": heap.total_free, "allocs": self.allocs, "ok": self.ok}

    def step(self, detail: bool = False) -> dict:
        """Apply the next event. With detail, include the decision description."""
        self.index += 1
        event = self.workload.events[self.index]
        heap, out = self.heap, {"index": self.index}
        if event.op is Op.ALLOC:
            pre = PreDecision(self.allocator, heap.free_blocks(), event.size) if detail else None
            before = heap.inspections
            placed = self.allocator.alloc(event.alloc_id, event.size)
            out["inspected"] = heap.inspections - before
            self.allocs += 1
            if placed is None:
                out["status"] = "fail-frag" if is_fragmentation_failure(heap, event.size) else "fail-cap"
            else:
                self.ok += 1
                out["status"] = "ok"
                out["placed"] = _block(placed)
            if detail:
                chosen = self._chosen(pre, placed)
                if chosen is not None and chosen.size > event.size:
                    out["residual"] = {"addr": placed.end, "size": chosen.size - event.size}
                out["decision"] = pre.describe(chosen)
        else:
            freed = heap.allocation(event.alloc_id)          # None if this id's ALLOC failed
            merged = self.allocator.free(event.alloc_id)
            if freed is None:
                out["status"] = "free-noop"
            else:
                out["status"] = "free"
                out["freed"] = _block(freed)
                out["merged"] = _block(merged)
                out["merged_left"] = merged.addr < freed.addr
                out["merged_right"] = merged.end > freed.end
        out["metrics"] = self.metrics()
        return out

    @staticmethod
    def _chosen(pre: PreDecision, placed: Optional[Block]) -> Optional[Block]:
        """The free block the engine cut the request from (before the split)."""
        if placed is None:
            return None
        return next(b for b in pre.fitting if b.addr == placed.addr)

    def snapshot(self) -> List[int]:
        """Every block in address order, flattened to [addr, size, id (-1 = free), ...]."""
        return [x for v in self.heap.snapshot() for x in (v.addr, v.size, -1 if v.free else v.alloc_id)]


class Session:
    def __init__(self, workload: Workload, algorithm: str):
        algorithm_class(algorithm)
        self.workload, self.algorithm = workload, algorithm
        self.lock = threading.Lock()
        self.timeline = self._timeline()
        self.summary = replay(algorithm_class(algorithm), workload.events, Mode.FIXED, workload.capacity)
        self._stepper = Stepper(workload, algorithm)

    def _timeline(self) -> dict:
        """Per-event status and metrics for the whole run, column-oriented. ef and status drive
        the UI; inspected, util, ok and allocs let tests cross-check against framework.replay."""
        stepper = Stepper(self.workload, self.algorithm)
        initial = stepper.metrics()
        cols: Dict[str, list] = {k: [] for k in ("status", "inspected", "ef", "util", "ok", "allocs")}
        max_blocks = initial["free_blocks"]
        for _ in range(len(self.workload.events)):
            rec = stepper.step()
            m = rec["metrics"]
            cols["status"].append(rec["status"])
            cols["inspected"].append(rec.get("inspected"))
            for k in ("ef", "util", "ok", "allocs"):
                cols[k].append(m[k])
            max_blocks = max(max_blocks, m["free_blocks"] + m["allocated_blocks"])
        return {"initial": initial, "max_blocks": max_blocks, **cols}

    def payload(self) -> dict:
        tl = self.timeline
        ui_timeline = {k: tl[k] for k in ("initial", "max_blocks", "status", "ef")}
        return {"algorithm": self.algorithm, "workload": self.workload.info(),
                "events": self.workload.event_list(), "timeline": ui_timeline, "summary": self.summary}

    def frames(self, start: int, count: int) -> List[dict]:
        """Frames for events start .. start+count-1 (index -1 is the initial heap)."""
        n = len(self.workload.events)
        if not -1 <= start < n:
            raise ValueError(f"frame index must be in [-1, {n - 1}], got {start}")
        count = max(1, min(count, MAX_FRAMES_PER_REQUEST, n - start))
        with self.lock:
            if self._stepper.index >= start:
                self._stepper = Stepper(self.workload, self.algorithm)
            while self._stepper.index < start - 1:
                self._stepper.step()
            out = []
            if start == -1:
                out.append({"index": -1, "status": "initial", "metrics": self._stepper.metrics(),
                            "blocks": self._stepper.snapshot()})
                count -= 1
            for _ in range(count):
                frame = self._stepper.step(detail=True)
                frame["blocks"] = self._stepper.snapshot()
                out.append(frame)
            return out


class SessionStore:
    def __init__(self, limit: int = MAX_SESSIONS):
        self.limit = limit
        self._sessions: "OrderedDict[str, Session]" = OrderedDict()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def add(self, session: Session) -> str:
        with self._lock:
            sid = f"s{next(self._ids)}"
            self._sessions[sid] = session
            while len(self._sessions) > self.limit:
                self._sessions.popitem(last=False)
            return sid

    def get(self, sid: str) -> Session:
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                raise KeyError(f"unknown or expired session {sid!r}")
            self._sessions.move_to_end(sid)
            return session

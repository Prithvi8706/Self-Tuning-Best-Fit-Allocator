from engine.algorithms.arbf import ARBF
from engine.algorithms.best_fit import BestFit
from engine.algorithms.first_fit import FirstFit
from engine.algorithms.next_fit import NextFit
from engine.algorithms.worst_fit import WorstFit

ALGORITHMS = (FirstFit, BestFit, WorstFit, NextFit, ARBF)

__all__ = ["ALGORITHMS", "ARBF", "BestFit", "FirstFit", "NextFit", "WorstFit"]

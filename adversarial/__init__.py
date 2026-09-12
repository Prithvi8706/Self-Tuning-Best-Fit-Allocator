"""Adversarial stress study of the frozen ARBF Version 1.

Everything here is measurement and analysis. Nothing in this package changes the
algorithm (engine/algorithms/arbf.py), the heap mechanism, the frozen workload
registry or the replay/metric code; it only builds new traces and replays them
through the unmodified engine and framework.
"""

"""The simulator UI backend only observes the engine: its numbers must equal the
benchmark's, and every decision it explains must be the engine's own decision."""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

from engine.algorithms import ALGORITHMS
from simulator import analysis
from simulator.server import Handler
from simulator.session import Session
from simulator.workload import WorkloadError, build_workload, parse_trace_text

ALG_NAMES = [cls.name for cls in ALGORITHMS]
WORKLOADS = [
    {"kind": "family", "family": "F12", "seed": 3, "n_events": 1500, "margin": 0.1},
    {"kind": "family", "family": "F5", "seed": 2, "n_events": 1500, "margin": 0.1},
    {"kind": "corpus", "name": "minimal-counterexample"},
    {"kind": "corpus", "name": "rare-large-trap"},
    {"kind": "trace", "text": "ALLOC A1 100\nALLOC A2 200\nFREE A1\nALLOC A3 80\nALLOC A4 150\nFREE A2",
     "memory": 1024},
]


def _all_frames(session: Session):
    frames, start = [], -1
    while start < len(session.workload.events):
        batch = session.frames(start, 200)
        frames += batch
        start = batch[-1]["index"] + 1
    return frames


@pytest.mark.parametrize("spec", WORKLOADS, ids=lambda s: s.get("family") or s.get("name") or "trace")
@pytest.mark.parametrize("algorithm", ALG_NAMES)
def test_timeline_matches_benchmark_replay(spec, algorithm):
    session = Session(build_workload(spec), algorithm)
    tl, summary = session.timeline, session.summary
    assert tl["allocs"][-1] - tl["ok"][-1] == summary["failed_allocations"]
    ef = [x for x in tl["ef"] if x is not None]
    assert (sum(ef) / len(ef) if ef else None) == pytest.approx(summary["ef_mean"])
    assert sum(x or 0 for x in tl["inspected"]) == summary["blocks_inspected_total"]
    assert sum(tl["util"]) / len(tl["util"]) == pytest.approx(summary["utilization_mean"])


@pytest.mark.parametrize("spec", WORKLOADS, ids=lambda s: s.get("family") or s.get("name") or "trace")
def test_arbf_explanations_agree_with_engine(spec):
    session = Session(build_workload(spec), "arbf")
    frames = _all_frames(session)
    assert [f["index"] for f in frames] == list(range(-1, len(session.workload.events)))
    for f in frames:
        decision = f.get("decision")
        if decision is None:
            continue
        a = decision["arbf"]
        assert a["consistent"], f"frame {f['index']}"
        chosen = [r for r in a["rows"] if r["chosen"]]
        if f["status"] == "ok":
            assert len(chosen) == 1 and chosen[0]["addr"] == f["placed"]["addr"]
            # K is the engine's integer cost: r · (2(n+1) − c(r))
            for r in a["rows"]:
                assert r["cost"] == r["residual"] * (2 * (a["n"] + 1) - r["fits"])
        else:
            assert not chosen and a["path"] == "none"


def test_minimal_counterexample_is_explained_as_a_deviation():
    frames = Session(build_workload({"kind": "corpus", "name": "minimal-counterexample"}), "arbf").frames(-1, 6)
    a = frames[4]["decision"]["arbf"]
    assert a["deviated"] and a["path"] == "scan"
    assert a["best_fit"]["size"] == 135 and frames[4]["decision"]["chosen"]["size"] == 140
    assert "135-unit block" in a["reason"] and "140-unit block" in a["reason"]
    assert frames[5]["status"] == "fail-frag"


def test_seeking_backwards_replays_identically():
    session = Session(build_workload(WORKLOADS[0]), "arbf")
    forward = session.frames(100, 5)
    session.frames(400, 3)
    assert session.frames(100, 5) == forward


def test_compare_uses_one_trace_for_every_algorithm():
    workload = build_workload({"kind": "corpus", "name": "reverse-trap"})
    result = analysis.compare(workload, None)
    assert [r["algorithm"] for r in result["results"]] == ALG_NAMES
    failed = {r["algorithm"]: r["record"]["failed_allocations"] for r in result["results"]}
    assert failed["best_fit"] == 200 and failed["arbf"] == 0      # the recorded study outcome


def test_experiment_statistics():
    spec = {"family": "F12", "first_seed": 1, "seed_count": 3, "n_events": 800, "margin": 0.1,
            "algorithms": ["best_fit", "arbf"]}
    result = analysis.experiment(spec)
    ef = result["stats"]["ef_mean"]
    assert ef["arbf"]["n"] == 3 and ef["arbf"]["ci_low"] <= ef["arbf"]["mean"] <= ef["arbf"]["ci_high"]
    paired = ef["arbf"]["paired"]
    diffs = [a - b for a, b in zip(ef["arbf"]["values"], ef["best_fit"]["values"])]
    assert paired["mean_diff"] == pytest.approx(sum(diffs) / 3)
    assert paired["better"] + paired["worse"] + paired["ties"] == 3
    assert len({s["trace_sha256"] for s in result["per_seed"]}) == 3


@pytest.mark.parametrize("text, line, fragment", [
    ("ALLOC A1 abc", 1, "whole number"),
    ("ALLOC A1 10\nFREE A2", 2, "not currently allocated"),
    ("ALLOC A1 10\nALLOC A1 5", 2, "already allocated"),
    ("MALLOC A1 10", 1, "unknown operation"),
    ("ALLOC A1", 1, "expected"),
    ("# only a comment", 0, "empty"),
])
def test_trace_parser_reports_line_errors(text, line, fragment):
    trace, _, issues = parse_trace_text(text)
    assert trace is None and issues[0].line == line and fragment in issues[0].message


def test_trace_parser_allows_label_reuse_after_free():
    trace, labels, issues = parse_trace_text("alloc x 5  # comment\nfree x\nALLOC x 7\n")
    assert not issues and len(trace) == 3
    assert trace[0].alloc_id != trace[2].alloc_id and labels[trace[2].alloc_id] == "x"


def test_workload_validation():
    with pytest.raises(WorkloadError):
        build_workload({"kind": "trace", "text": "ALLOC A 1", "memory": 0})
    with pytest.raises(WorkloadError):
        build_workload({"kind": "family", "family": "F5", "seed": 1, "n_events": 10})   # no memory sizing
    with pytest.raises(ValueError):
        Session(build_workload(WORKLOADS[-1]), "no_such_policy")


def test_http_api_round_trip():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None):
        req = Request(base + path, data=None if body is None else json.dumps(body).encode(),
                      headers={"Content-Type": "application/json"})
        with urlopen(req) as res:
            return json.load(res)

    try:
        meta = call("/api/meta")
        assert [a["name"] for a in meta["algorithms"]] == ALG_NAMES
        sim = call("/api/sim", {"workload": WORKLOADS[-1], "algorithm": "best_fit"})
        frames = call(f"/api/sim/{sim['id']}/frames?start=-1&count=10")["frames"]
        assert len(frames) == 7 and frames[-1]["metrics"]["live"] == 230
        assert call("/api/trace/validate", {"text": "FREE nope"})["ok"] is False
    finally:
        httpd.shutdown()


# ------------------------------------------------------- regression tests (health scan)

def test_next_fit_candidates_are_ranked_from_the_rover_before_the_decision():
    trace = "ALLOC A 10\nALLOC B 10\nALLOC C 10\nALLOC E 10\nFREE A\nFREE C\nALLOC D 10"
    for spec in ({"kind": "trace", "text": trace, "memory": 40}, WORKLOADS[1]):
        for f in _all_frames(Session(build_workload(spec), "next_fit")):
            if f["status"] == "ok":
                assert f["decision"]["candidates"][0]["chosen"], f"frame {f['index']}"


def test_shortcut_explanation_only_claims_what_p5_guarantees():
    trace = "ALLOC X1 15\nALLOC G1 1\nALLOC X2 20\nALLOC G2 1\nALLOC H 10\nFREE X1\nFREE X2\nALLOC R 10"
    a = Session(build_workload({"kind": "trace", "text": trace, "memory": 47}), "arbf").frames(7, 1)[0]["decision"]["arbf"]
    assert a["path"] == "shortcut" and a["rbf"] == 5
    assert any(r["fits"] > a["rows"][0]["fits"] for r in a["rows"])    # a larger leftover does fit more...
    assert "or more can never score lower" in a["reason"]              # ...and the text says why it still loses


def test_explicit_empty_selection_and_null_fields_are_rejected():
    with pytest.raises(WorkloadError, match="at least one"):
        analysis.compare(build_workload(WORKLOADS[-1]), [])
    base = {"family": "F5", "first_seed": 1, "seed_count": 2, "n_events": 200}
    with pytest.raises(WorkloadError, match="memory must be an integer"):
        analysis.experiment({**base, "memory": None})
    with pytest.raises(WorkloadError, match="margin"):
        analysis.experiment({**base, "margin": "x"})
    with pytest.raises(WorkloadError, match="memory must be an integer"):
        build_workload({"kind": "family", "family": "F5", "seed": 1, "n_events": 10, "memory": None})


def test_sim_payload_ships_only_what_the_ui_draws():
    payload = Session(build_workload(WORKLOADS[-1]), "arbf").payload()
    assert set(payload["timeline"]) == {"initial", "max_blocks", "status", "ef"}


def test_negative_content_length_is_rejected_not_blocking():
    import http.client
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        conn.putrequest("POST", "/api/trace/validate")
        conn.putheader("Content-Length", "-1")
        conn.endheaders()
        assert conn.getresponse().status == 400
    finally:
        httpd.shutdown()


def test_deviation_reason_never_prints_unequal_weights_as_equal():
    session = Session(build_workload({"kind": "corpus", "name": "outlier-F4-s0.10-0.05"}), "arbf")
    a = session.frames(13054, 1)[0]["decision"]["arbf"]          # leftovers 383 vs 384 at n = 738
    assert a["deviated"]
    assert "from 1.371 to 1.367" in a["reason"] and "Ĝ = 0.629" in a["reason"] and "Ĝ = 0.633" in a["reason"]

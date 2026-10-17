"""
Equivalence tests: the optimised code must produce exactly the same output
as the baseline (commit 943cb99) for the same input.

The baseline modules are loaded straight from git, so the reference is the
real original code, not a copy. Redis tests use DB 15 and are skipped if
Redis isn't reachable.

    python -m pytest tests -v
"""
import json
import os
import subprocess
import sys
import types
from unittest import mock

import numpy as np
import pytest
import redis

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bench"))

from benchmark import synthetic_matrix  # noqa: E402

BASELINE_COMMIT = "943cb99"
TEST_DB = 15


class _FakeKafkaConsumer:
    """Stands in for KafkaConsumer so importing consumer.py needs no broker."""
    def __init__(self, *a, **k):
        pass


def load_baseline(module_name):
    src = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:{module_name}.py"],
        cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    mod = types.ModuleType(f"baseline_{module_name}")
    with mock.patch("kafka.KafkaConsumer", _FakeKafkaConsumer):
        exec(compile(src, f"baseline/{module_name}.py", "exec"), mod.__dict__)
    mod.print = lambda *a, **k: None
    return mod


def load_current(module_name):
    with mock.patch("kafka.KafkaConsumer", _FakeKafkaConsumer):
        mod = __import__(module_name)
    mod.print = lambda *a, **k: None
    return mod


@pytest.fixture(scope="module")
def rdb():
    r = redis.Redis(host="localhost", port=6379, db=TEST_DB,
                    decode_responses=True)
    try:
        r.ping()
    except redis.ConnectionError:
        pytest.skip("Redis not reachable on localhost:6379")
    r.flushdb()
    yield r
    r.flushdb()


# ── recommend() ───────────────────────────────────────────────
MATRIX_CASES = [  # (users, items, clicks/user, seed)
    (10, 45, 10, 1),
    (10, 45, 3, 2),        # sparse → many zero-similarity users and ties
    (100, 45, 10, 3),
    (300, 499, 20, 4),
    (1_000, 45, 10, 42),
]


@pytest.mark.parametrize("n_users,n_items,cpu,seed", MATRIX_CASES)
def test_recommend_identical(n_users, n_items, cpu, seed):
    base, cur = load_baseline("recommender"), load_current("recommender")
    matrix, all_items = synthetic_matrix(
        n_users, n_items, cpu, np.random.default_rng(seed))
    base.load_click_matrix = lambda: (matrix, all_items)
    cur_loader = cur.load_click_matrix
    cur.load_click_matrix = lambda: (matrix, all_items)
    try:
        users = list(matrix) + ["no_such_user"]
        for u in users:
            for top_n in (5, 20):
                expected = base.recommend(u, top_n)
                got = cur.recommend(u, top_n)
                assert got == expected, (
                    f"{u} top_n={top_n}: differs from baseline\n"
                    f"  baseline: {expected}\n  current:  {got}")
    finally:
        cur.load_click_matrix = cur_loader


# ── load_click_matrix() ───────────────────────────────────────
@pytest.mark.parametrize("n_users", [0, 10, 1_000, 2_500])
def test_load_click_matrix_identical(rdb, n_users):
    base, cur = load_baseline("recommender"), load_current("recommender")
    rdb.flushdb()
    matrix, _ = synthetic_matrix(n_users, 45, 10, np.random.default_rng(7))
    pipe = rdb.pipeline()
    for u, row in matrix.items():
        pipe.hset(f"clicks:{u}", mapping=row)
    pipe.set("recs:user_0", "[]")          # non-click key must be ignored
    pipe.execute()

    base.cache = rdb
    real_cache = cur.cache
    cur.cache = rdb
    try:
        b_matrix, b_items = base.load_click_matrix()
        c_matrix, c_items = cur.load_click_matrix()
    finally:
        cur.cache = real_cache
    assert c_items == b_items
    assert c_matrix == b_matrix
    for u in b_matrix:                      # per-user item order too
        assert list(c_matrix[u].items()) == list(b_matrix[u].items())


# ── consumer ──────────────────────────────────────────────────
class _Stop(Exception):
    pass


class _Msg:
    def __init__(self, value):
        self.value = value


class _ScriptedConsumer:
    """
    Feeds a fixed list of events, either by iteration (baseline) or by
    poll() in uneven batches (batched consumer), then raises _Stop.
    """
    def __init__(self, events, batch_sizes=(1, 7, 64, 3, 500)):
        self.msgs = [_Msg(e) for e in events]
        self.batch_sizes = batch_sizes

    def __iter__(self):
        yield from self.msgs
        raise _Stop

    def poll(self, timeout_ms=0, max_records=None, **_):
        if not self.msgs:
            raise _Stop
        size = self.batch_sizes[len(self.msgs) % len(self.batch_sizes)]
        if max_records:
            size = min(size, max_records)
        batch, self.msgs = self.msgs[:size], self.msgs[size:]
        return {"tp": batch} if batch else {}


def _events(n, seed):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        out.append({"user_id": f"user_{rng.integers(10)}",
                    "item_id": f"item_{rng.integers(45)}",
                    "timestamp": i, "action": "click"})
    out[5]["action"] = "hover"             # ignored action
    out[9] = {"user_id": "user_1"}          # malformed: no item_id
    out[13] = {"item_id": "item_1", "action": "click"}  # malformed: no user
    return out


def _run_consumer(mod, events, rdb):
    rdb.flushdb()
    mod.consumer = _ScriptedConsumer(events)
    mod.cache = rdb
    mod.click_matrix.clear()
    with pytest.raises(_Stop):
        mod.consume()
    redis_state = {k: rdb.hgetall(k) for k in rdb.keys("clicks:*")}
    memory_state = {u: dict(v) for u, v in mod.click_matrix.items()}
    return redis_state, memory_state


@pytest.mark.parametrize("n_events", [20, 2_000])
def test_consumer_identical(rdb, n_events):
    base, cur = load_baseline("consumer"), load_current("consumer")
    real = (cur.consumer, cur.cache)
    events = _events(n_events, seed=n_events)
    try:
        b_redis, b_mem = _run_consumer(base, events, rdb)
        c_redis, c_mem = _run_consumer(cur, events, rdb)
    finally:
        cur.consumer, cur.cache = real
    assert c_redis == b_redis
    assert c_mem == b_mem

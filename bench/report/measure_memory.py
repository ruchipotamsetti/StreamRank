"""
Peak Python/numpy memory (tracemalloc) of baseline (943cb99) vs current code
for recommend() and load_click_matrix(), on the benchmark's synthetic data.

    python bench/report/measure_memory.py      # needs Redis for the load test
"""
import os
import sys
import tracemalloc

import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, ROOT)

from test_equivalence import load_baseline, load_current, synthetic_matrix  # noqa: E402


def peak_mb(fn):
    tracemalloc.start()
    tracemalloc.reset_peak()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 2**20


if __name__ == "__main__":
    base, cur = load_baseline("recommender"), load_current("recommender")

    print("recommend() peak memory (click matrix served from memory)")
    for n_users, n_items, cpu in [(1_000, 499, 20), (5_000, 500, 20), (10_000, 500, 20)]:
        m, a = synthetic_matrix(n_users, n_items, cpu, np.random.default_rng(42))
        base.load_click_matrix = cur.load_click_matrix = (lambda m=m, a=a: (m, a))
        b = peak_mb(lambda: base.recommend("user_0"))
        c = peak_mb(lambda: cur.recommend("user_0"))
        print(f"  {n_users:>6} users x {len(a):>4} items: baseline {b:8.1f} MB  "
              f"current {c:8.1f} MB")

    import redis
    r = redis.Redis(db=15, decode_responses=True)
    r.flushdb()
    m, _ = synthetic_matrix(5_000, 45, 10, np.random.default_rng(42))
    pipe = r.pipeline()
    for u, row in m.items():
        pipe.hset(f"clicks:{u}", mapping=row)
    pipe.execute()
    import importlib
    base = load_baseline("recommender")
    cur = importlib.reload(load_current("recommender"))   # undo the patch above
    base.cache = cur.cache = r
    b = peak_mb(base.load_click_matrix)
    c = peak_mb(cur.load_click_matrix)
    print(f"load_click_matrix() peak memory, 5,000 users in Redis: "
          f"baseline {b:.1f} MB  current {c:.1f} MB")
    r.flushdb()

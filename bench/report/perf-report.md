# StreamRank `perf-improvements`: performance report

The `perf-improvements` commits (now merged into `main`), compared with baseline `943cb99`.

| Commit | What it does |
|---|---|
| `a03a4a8` | Adds an equivalence test that compares the new code with the original code from `943cb99` (no change to app code) |
| `0fe4a4d` | **1.** `load_click_matrix`: `SCAN` plus one pipelined `HGETALL` instead of `KEYS` plus one `HGETALL` per user |
| `43b472a` | **2.** `recommend()`: cosine similarity for the requesting user's row only, not the full users×users matrix |
| `3345d8c` | **3.** Consumer: poll Kafka in batches of up to 500 and write each batch to Redis in one pipeline |

`bench/benchmark.py` is unchanged between `943cb99` and `perf-improvements` (`git diff --stat 943cb99 perf-improvements -- bench/` prints nothing).

**Summary.** With warm services on both sides, cache misses are **8–13× faster** at 100 users or more. `recommend()` is **2.6× faster** at 10,000 users and needs about **10× less memory** there. End-to-end throughput rose from **2,130–3,337 to 4,745–4,957 events/s**, which is now limited by how fast the benchmark sends events. Recommended titles and their order are identical to the baseline. Scores differ only in the last bit or so of floating-point precision (explained in section 1). The headline numbers in my earlier message, such as "19×", are **too high**, because that baseline ran with cold services (section 3).

---

## 1. Correctness

Command (needs Redis on `localhost:6379`; uses DB 15; takes about 40 s):

```bash
python -m pytest tests -v -s
```

Output:

```
tests/test_equivalence.py::test_recommend_identical[10-45-10-1]
  [10x45] 18/22 lists differ from baseline only in score rounding (rel_tol 1e-12)
PASSED
tests/test_equivalence.py::test_recommend_identical[10-45-3-2]
  [10x45] 2/22 lists differ from baseline only in score rounding (rel_tol 1e-12)
PASSED
tests/test_equivalence.py::test_recommend_identical[100-45-10-3]
  [100x45] 139/202 lists differ from baseline only in score rounding (rel_tol 1e-12)
PASSED
tests/test_equivalence.py::test_recommend_identical[300-499-20-4]
  [300x499] 468/602 lists differ from baseline only in score rounding (rel_tol 1e-12)
PASSED
tests/test_equivalence.py::test_recommend_identical[1000-45-10-42]
  [1000x45] 1366/2002 lists differ from baseline only in score rounding (rel_tol 1e-12)
PASSED
tests/test_equivalence.py::test_load_click_matrix_identical[0] PASSED
tests/test_equivalence.py::test_load_click_matrix_identical[10] PASSED
tests/test_equivalence.py::test_load_click_matrix_identical[1000] PASSED
tests/test_equivalence.py::test_load_click_matrix_identical[2500] PASSED
tests/test_equivalence.py::test_consumer_identical[20] PASSED
tests/test_equivalence.py::test_consumer_identical[2000] PASSED
============================= 11 passed in 40.77s =============================
```

**How the test works.** It runs `git show 943cb99:<file>` to load the original `recommender.py` and `consumer.py`, so the reference is the actual old code, not a hand-made copy. Each test feeds the same input to the old and new code and compares the results.

| What is compared | Result |
|---|---|
| `recommend()`: titles and order, every user, top 5 and top 20, 5 data shapes, plus an unknown user | **Exact match in every case** |
| `recommend()`: scores | Equal within 1e-12 relative. **Not bit-identical**: 1,993 of 2,850 lists differ in the last bits |
| `load_click_matrix()` at 0, 10, 1,000 and 2,500 users, with a non-click key present | **Exact match**: same data, same item order per user, same item list |
| Consumer: Redis counts and in-memory counts, with malformed events, non-click events and uneven batch sizes | **Exact match** |

**What differs and why.** Only commit 2 changes any numbers. The old code built the full users×users similarity matrix in one big matrix multiplication. The new code computes a single row with a smaller one. NumPy hands these to different BLAS routines, which add the floating-point terms in a different order, so the results can differ in the last bits. The largest difference I saw was 7.3×10⁻¹⁶ relative.

A separate check of 7,840 lists, including 2,000- and 500-user cases, found **0** changes to titles or order. The UI shows scores to 2 decimals and confidence as an integer percentage, so nothing visible changes. Bit-for-bit identical scores would require computing the full matrix again. You chose to accept rounding-level differences, so the test checks titles and order exactly and scores to 1e-12.

---

## 2. Before vs after

All values are milliseconds, shown as p50 / p95, except throughput and stale reads. Each column is one run, and each run adds one commit on top of the previous column. The raw JSON for each column was kept on the benchmark machine and isn't in the repo.

| Metric | Baseline `943cb99` | + commit 1: SCAN/pipeline | + commit 2: single-row cosine | + commit 3: batched consumer (= after) |
|---|---|---|---|---|
| Cache miss, 10 users | 3.97 / 5.70 | 2.41 / 3.97 | 1.63 / 2.99 | 1.71 / 3.28 |
| Cache miss, 100 users | 68.24 / 88.68 | 7.42 / 11.17 | 3.71 / 5.40 | 3.59 / 5.28 |
| Cache miss, 1,000 users | 343.04 / 438.27 | 32.39 / 77.91 | 23.79 / 26.28 | 24.13 / 25.25 |
| Cache miss, 5,000 users | 1,974.19 / 3,010.83 | 239.68 / 301.76 | 109.97 / 148.67 | 114.23 / 152.66 |
| `recommend()`, 1,000×499 | 39.92 / 156.04 | 42.02 / 164.34 | 33.65 / 36.03 | 33.61 / 36.01 |
| `recommend()`, 10,000×500 | 1,021.64 / 1,118.04 | 1,049.97 / 1,121.46 | 358.39 / 394.94 | 365.52 / 382.75 |
| `recommend()`, 10×25 (demo size) | 0.17 / 0.45 | 0.19 / 0.48 | 0.24 / 0.69 | 0.25 / 0.51 |
| Cache hit, 10 users | 0.23 / 0.41 | 0.27 / 0.53 | 0.23 / 0.39 | 0.23 / 0.40 |
| Cache hit, 100 users | 0.27 / 0.46 | 0.21 / 0.38 | 0.22 / 0.39 | 0.21 / 0.35 |
| Cache hit, 1,000 users | 0.31 / 0.46 | 0.27 / 0.63 | 0.27 / 0.51 | 0.27 / 0.41 |
| Cache hit, 5,000 users | 0.55 / 1.06 | 0.25 / 0.49 | 0.24 / 0.41 | 0.26 / 0.48 |
| Click → visible in Redis | 4.23 / 5.73 | 4.92 / 7.89 | 4.11 / 6.90 | 2.94 / 6.65 |
| End-to-end throughput (events/s) | 2,185 | 1,137 | 2,938 | 4,321 |
| Stale reads (of 200) | 0 | 1 | 0 | 1 |

**What each commit changed.** The table above has one run per column, so read it together with the noise ranges in section 4.

- **Commit 1** only changes how click data is loaded from Redis. It produced the biggest drop in cache-miss time, for example 343 → 32 ms at 1,000 users. It didn't affect `recommend()` compute, because that benchmark serves click data from memory and never touches Redis.
- **Commit 2** cut `recommend()` at 10,000×500 from about 1,050 ms to about 360 ms. Cache misses also improved further, because a miss includes the compute: 32 → 24 ms at 1,000 users and 240 → 110 ms at 5,000. At 1,000×499 the change is within noise: most of that time is spent building the matrix, which commit 2 doesn't touch (section 5).
- **Commit 3** only changes the consumer. Throughput rose to 4,321 events/s. The throughput readings after commits 1 and 2 (1,137 and 2,938) are **noise**, since the consumer code was identical in those runs.
- **Cache hits did not get worse.** The baseline's 0.55 ms at 5,000 users was a slow outlier; warm baseline reruns gave 0.20–0.23.

---

## 3. Test conditions: comparison with the baseline

| Condition | Original baseline | Original after run | Same? |
|---|---|---|---|
| Machine | Intel Core Ultra 9 288V, 8 logical CPUs, 31.6 GB, Windows 11 26200 | same | ✅ |
| Python and libraries | 3.11.9, numpy 2.4.4, scikit-learn 1.8.0, redis-py 8.1.0, kafka-python 3.0.11 (same venv) | same | ✅ |
| Services | Docker 29.8.1, Redis 8.6.1, cp-kafka 7.5.0, 1 partition | same containers | ✅ |
| Data seed | 42 | 42 | ✅ |
| Redis DB / Kafka topic | 15 / `streamrank-bench` | 15 / `streamrank-bench` | ✅ |
| Benchmark code | `bench/benchmark.py` @ `943cb99` | byte-identical | ✅ |
| **Service state** | **Cold**: containers started 9 s before the run (14:51:45 → 14:51:54) | **Warm**: up about 2 h 15 m | ❌ **Different** |
| Other load on the laptop | not controlled | not controlled | ⚠️ unknown |

**What the cold start changed.** I reran the baseline 3 times with warm services (section 4). The cold baseline was much slower: cache miss at 100 users 68 ms cold vs about 29 ms warm, at 5,000 users 1,974 vs about 1,350 ms, and `recommend()` at 10,000×500 1,022 vs about 900 ms. So the before-vs-after ratios in section 2 overstate the gains. **Use section 4 for the speedups you quote.** For those, both sides ran warm, alternating baseline and after runs (20:31–20:45) so that any drift in machine load affected both equally. Every run recorded the same machine, library and service versions as the table above.

---

## 4. Noise: 3 runs each, warm services, alternating

The 3 after runs come from the `perf-improvements` checkout. The 3 baseline runs come from a temporary checkout of `943cb99` running its own copy of `benchmark.py`. Run order: after, baseline, after, baseline, after, baseline. The raw data was kept on the benchmark machine and isn't in the repo.

| Metric | Baseline p50 range | After p50 range | Baseline p95 range | After p95 range | Verdict | Speedup (p50, warm) |
|---|---|---|---|---|---|---|
| Cache miss, 10 users | 3.12–4.06 | 1.46–2.05 | 3.64–5.18 | 1.92–2.81 | **Real** | ~2× |
| Cache miss, 100 users | 29.31–29.61 | 3.46–3.69 | 35.99–36.79 | 3.81–4.70 | **Real** | ~8× |
| Cache miss, 1,000 users | 254.93–264.99 | 21.56–32.72 | 319.53–342.87 | 22.74–57.32 | **Real** | ~8–12× |
| Cache miss, 5,000 users | 1,313.93–1,396.09 | 103.78–113.10 | 1,555.13–1,651.81 | 128.45–141.22 | **Real** | ~12–13× |
| `recommend()`, 1,000×499 | 37.45–39.55 | 31.56–48.28 | 46.75–82.25 | 34.74–51.27 | Within noise | – |
| `recommend()`, 10,000×500 | 892.74–903.18 | 330.05–352.47 | 913.49–928.77 | 359.88–479.31 | **Real** | ~2.6× |
| `recommend()`, 10×25 (demo) | 0.10–0.10 | 0.14–0.26 | 0.12–0.13 | 0.17–0.69 | **Slower** (section 5) | 0.4–0.7× |
| Cache hit, 10 / 100 / 1,000 / 5,000 users | 0.19–0.27 | 0.20–0.31 | 0.27–0.41 | 0.27–0.51 | Within noise | – |
| Click → visible in Redis | 2.37–3.72 | 2.63–2.98 | 2.74–4.98 | 4.00–4.31 | Within noise | – |
| End-to-end throughput (events/s) | 2,130–3,337 | 4,745–4,957 | – | – | **Real** | ~1.4–2.3× |
| Stale reads (of 200) | 0–0 | 0–0 | – | – | Too rare to measure at 200 trials | – |

**How to read the verdicts.**
- **Real** means the after range doesn't overlap the baseline range. With only 3 runs per side that's strong evidence, not proof.
- **The throughput gain is understated.** In the after runs, the consumer finished within about 0.05 s of the producer: the benchmark sent at 4,807–5,023 events/s and the consumer kept up. The consumer's true maximum is higher than this benchmark can measure.
- **Throughput fluctuates a lot without the change.** With the old consumer, the 6 runs ranged from 1,137 to 3,337 events/s, a spread of about 3×. Any single-run throughput number from the old code is unreliable.

---

## 5. Regressions, tradeoffs, and the stale-cache race

### What got worse

- **`recommend()` on the 10-user demo data: 0.10 → 0.14–0.26 ms at p50.** The cause is commit 2: `cosine_similarity(row, X)` checks and normalises its two inputs separately, which costs more fixed overhead than a single `cosine_similarity(X)` call. That only matters when the matrix is tiny. The extra ~0.1 ms is less than one Redis round trip (~0.2 ms), and a cache miss at 10 users still got about 2× faster overall.
- **`load_click_matrix()` peak memory rose slightly**, from 3.9 to 6.1 MB at 5,000 users. The pipeline holds every reply at once instead of one at a time. (`bench/report/measure_memory.py`)

### Memory: a big improvement

Measured with `python bench/report/measure_memory.py` (tracemalloc, which also tracks numpy arrays).:

| `recommend()` peak memory | Baseline | After |
|---|---|---|
| 1,000 users × 497 titles | 15.2 MB | 7.9 MB |
| 5,000 × 500 | 228.9 MB | 39.4 MB |
| 10,000 × 500 | **839.3 MB** | **78.8 MB** |

The full users×users matrix at 10,000 users is 10,000² × 8 bytes = 800 MB. It was allocated on every cache miss. Memory now grows linearly with the number of users instead of with its square.

### Code complexity and behaviour changes

- **Size:** `recommender.py` +15/−9 lines and `consumer.py` +32/−21 (`git diff --stat 943cb99 perf-improvements`). Most of the consumer change is one extra level of indentation.
- **Commit 3 changes when Redis is updated.** Under load, Redis counts lag the consumer's in-memory counts by up to one batch (500 events, a few milliseconds). A crash in the middle of a batch would lose the Redis writes for that batch, though they'd already be counted in memory. The old code had the same risk, but only for one event at a time.
- **`update_redis()` is gone.** Nothing else in the repo called it. The consumer now also wakes up once per second when idle, because `poll` has a 1 s timeout; that costs nothing noticeable.
- **`SCAN` doesn't block Redis the way `KEYS` does.** That's a side benefit. It still takes one round trip per 1,000 keys, so "one round trip" is accurate only up to 1,000 users.

### Is the stale-cache race still there? Yes after these three commits, fixed in the next one

None of the three commits address it. The app sends the click, deletes the cached recommendations, and recomputes right away. Meanwhile the consumer applies the click to Redis about 3 ms later. If the recompute reads Redis first, it misses the click and caches the stale result for 60 s.

- **How often:** 3 stale reads in 1,600 trials across the 8 runs that included commit 1 or later: one each in the after-commit-1 run, the final after run, and one of my two extra end-to-end reruns. The baseline code had 0 in 800 trials over 4 runs.
- **Why it may have become slightly more likely:** faster misses read Redis sooner after the click. At these counts, though, the difference between the two isn't statistically meaningful.
- **Fixed in a later commit.** `61fe0f8` ("Fix stale recommendations after a click", now on `main`) makes the app wait until the consumer has processed the click before it recomputes. It reported 0 of 600 stale reads, but it also edits the benchmark's copy of the click flow. That comparison isn't like-for-like.

---

## 6. Plain-English explanation of each change (for interviews)

**1. Loading click data: N round trips → 1 pipelined batch**
- **What was slow:** to recompute recommendations, the code fetched every user's click counts from Redis. It asked for the list of users, then sent one request per user and waited for each reply before sending the next. With 1,000 users that's 1,000 network round trips of about 0.2–0.3 ms each. Most of the time was spent waiting on the network, not computing.
- **The fix:** list the keys with `SCAN`, then send all the `HGETALL` requests in one **pipeline**: write them all, then read all the replies. Redis does the same work, but the client waits for the network once instead of N times.
- **Bonus:** `KEYS` blocks Redis while it scans every key; `SCAN` walks the keys in small steps, so other clients aren't held up.
- **Result:** cache misses about 8–13× faster at 100 to 5,000 users (warm comparison).

**2. Similarity: the whole users×users matrix → one row**
- **What was slow:** collaborative filtering needs to know how similar the requesting user is to everyone else. The old code computed similarity between **every pair** of users, a 10,000×10,000 matrix (800 MB), then used one row of it.
- **The fix:** compute only that row: this user's vector compared with every other user's.
- **Result:** at 10,000 users, about 2.6× faster and about 10× less memory, and the cost now grows linearly with users instead of with their square. Titles and order are unchanged. Scores can differ in about the 16th significant digit, because a different BLAS routine adds the numbers in a different order.
- **What's still slow:** building the user×title array uses a pure-Python double loop. At 1,000×499 that loop dominates, which is why the gain there is within noise. Vectorising it, or keeping a sparse matrix up to date as clicks arrive, would be the next step.

**3. Consumer: one Redis write per event → one pipelined write per batch**
- **What was slow:** for each Kafka event, the consumer sent `HINCRBY` to Redis and waited for the reply, so throughput was limited to roughly 1 ÷ round-trip time.
- **The fix:** `poll()` Kafka for up to 500 events at once, queue all their `HINCRBY`s in a pipeline, and send them together. `poll()` returns as soon as any event arrives, so a single click is still written right away, with no added delay. The batching only kicks in under load.
- **Result:** throughput went from 2,130–3,337 to 4,745–4,957 events/s, which is as fast as the benchmark can send events. Click-to-Redis latency for a single click didn't change.

---

## How to reproduce

```bash
python -m pytest tests -v -s                     # correctness
python bench/benchmark.py                        # one full benchmark run; writes bench/results.json
python bench/report/measure_memory.py            # memory
```

Each benchmark run logs one known traceback ("KafkaConsumer is closed"), raised when the benchmark closes the consumer at shutdown. It doesn't affect the results.

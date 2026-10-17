"""
StreamRank benchmark suite.

Three benchmarks, each runnable on its own:

  scaling  — pure compute cost of recommend() as users/items grow
             (click matrix served from memory; no Docker needed)
  cache    — get_recommendations() latency on Redis cache HIT vs MISS,
             at several user counts (needs Redis)
  e2e      — click → Kafka → consumer → Redis ingest latency, the app's
             click-then-refresh flow (stale-read rate), and pipeline
             throughput (needs Kafka + Redis)

Isolation: benchmarks use Redis DB 15 and Kafka topic 'streamrank-bench',
so the app's data (DB 0, topic 'user-clicks') is never touched.

Usage:
    python bench/benchmark.py                 # all three
    python bench/benchmark.py scaling cache   # a subset
"""
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import redis

BENCH_DB    = 15
BENCH_TOPIC = "streamrank-bench"
BOOTSTRAP   = "localhost:9092"
SEED        = 42
RESULTS     = {}


def _quiet(*_a, **_k):
    pass


# ── Helpers ───────────────────────────────────────────────────
def stats_ms(samples_ns):
    """Summarise a list of nanosecond timings in milliseconds."""
    ms = sorted(s / 1e6 for s in samples_ns)
    pct = lambda p: ms[min(len(ms) - 1, int(round(p / 100 * (len(ms) - 1))))]
    return {
        "n": len(ms),
        "mean": statistics.fmean(ms),
        "p50": pct(50),
        "p95": pct(95),
        "p99": pct(99),
        "min": ms[0],
        "max": ms[-1],
    }


def fmt(s):
    return (f"n={s['n']:>5}  p50={s['p50']:9.3f}  p95={s['p95']:9.3f}  "
            f"p99={s['p99']:9.3f}  mean={s['mean']:9.3f}  max={s['max']:9.3f} ms")


def synthetic_matrix(n_users, n_items, clicks_per_user, rng):
    """
    Build a { user: { item: count } } matrix with Zipf-skewed item
    popularity — a few titles get most clicks, like a real catalogue.
    """
    items = [f"item_{i}" for i in range(n_items)]
    weights = 1.0 / np.arange(1, n_items + 1) ** 1.1
    weights /= weights.sum()
    matrix = {}
    for u in range(n_users):
        picks = rng.choice(n_items, size=clicks_per_user, p=weights)
        row = {}
        for p in picks:
            row[items[p]] = row.get(items[p], 0) + 1
        matrix[f"user_{u}"] = row
    return matrix, sorted({i for r in matrix.values() for i in r})


def bench_redis():
    return redis.Redis(host="localhost", port=6379, db=BENCH_DB,
                       decode_responses=True)


def patch_recommender(r):
    import recommender
    recommender.cache = r
    recommender.print = _quiet
    return recommender


# ── 1. Compute scaling ────────────────────────────────────────
def run_scaling():
    print("\n== 1. recommend() compute scaling (in-memory, no Redis I/O) ==")
    import recommender
    from sklearn.metrics.pairwise import cosine_similarity
    recommender.print = _quiet
    real_loader = recommender.load_click_matrix
    rng = np.random.default_rng(SEED)

    configs = [  # (users, items, clicks/user, timed calls)
        (10,     45,   10, 500),   # the demo: 10 users, 45-title catalogue
        (100,    45,   10, 300),
        (1_000,  45,   10, 100),
        (1_000,  500,  20, 100),
        (5_000,  500,  20, 30),
        (10_000, 500,  20, 15),
        (10_000, 2000, 30, 10),
    ]
    out = []
    try:
        for n_users, n_items, cpu, reps in configs:
            matrix, all_items = synthetic_matrix(n_users, n_items, cpu, rng)
            recommender.load_click_matrix = lambda m=matrix, a=all_items: (m, a)
            users = list(matrix)

            recommender.recommend(users[0])   # warm-up
            total, t_build, t_sim = [], [], []
            for i in range(reps):
                u = users[i % len(users)]
                t0 = time.perf_counter_ns()
                recommender.recommend(u)
                total.append(time.perf_counter_ns() - t0)

                # Stage breakdown (same work recommend() does internally)
                t0 = time.perf_counter_ns()
                npm, _ = recommender.build_numpy_matrix(matrix, all_items)
                t1 = time.perf_counter_ns()
                cosine_similarity(npm)
                t2 = time.perf_counter_ns()
                t_build.append(t1 - t0)
                t_sim.append(t2 - t1)

            s = stats_ms(total)
            b = statistics.fmean(t_build) / 1e6
            c = statistics.fmean(t_sim) / 1e6
            rest = max(0.0, s["mean"] - b - c)
            print(f"  users={n_users:>6} items={len(all_items):>5}  {fmt(s)}")
            print(f"      breakdown (mean): build_matrix={b:.3f}  "
                  f"cosine_similarity={c:.3f}  scoring+sort≈{rest:.3f} ms")
            out.append({"users": n_users, "items": len(all_items),
                        "clicks_per_user": cpu, "total": s,
                        "build_matrix_ms": b, "cosine_ms": c,
                        "scoring_ms": rest})
    finally:
        recommender.load_click_matrix = real_loader
    RESULTS["scaling"] = out


# ── 2. Cache hit vs miss ──────────────────────────────────────
def run_cache():
    print("\n== 2. get_recommendations(): cache HIT vs MISS (Redis DB 15) ==")
    r = bench_redis()
    rec = patch_recommender(r)
    rng = np.random.default_rng(SEED)

    # Baseline: one Redis round trip
    r.set("bench:ping", "x")
    rtt = []
    for _ in range(2000):
        t0 = time.perf_counter_ns()
        r.get("bench:ping")
        rtt.append(time.perf_counter_ns() - t0)
    rtt_s = stats_ms(rtt)
    print(f"  baseline Redis GET RTT        {fmt(rtt_s)}")

    out = {"redis_get_rtt": rtt_s, "sizes": []}
    for n_users, miss_reps in [(10, 300), (100, 200), (1_000, 40), (5_000, 10)]:
        r.flushdb()
        matrix, _ = synthetic_matrix(n_users, 45, 10, rng)
        pipe = r.pipeline()
        for u, row in matrix.items():
            pipe.hset(f"clicks:{u}", mapping=row)
        pipe.execute()
        users = list(matrix)

        miss = []
        for i in range(miss_reps):
            u = users[i % len(users)]
            r.delete(f"recs:{u}")
            t0 = time.perf_counter_ns()
            rec.get_recommendations(u)
            miss.append(time.perf_counter_ns() - t0)

        hit = []
        u = users[0]
        rec.get_recommendations(u)            # ensure cached
        for _ in range(2000):
            t0 = time.perf_counter_ns()
            rec.get_recommendations(u)
            hit.append(time.perf_counter_ns() - t0)

        # How much of a miss is just loading the matrix from Redis?
        load = []
        for _ in range(min(miss_reps, 50)):
            t0 = time.perf_counter_ns()
            rec.load_click_matrix()
            load.append(time.perf_counter_ns() - t0)

        hs, ms_, ls = stats_ms(hit), stats_ms(miss), stats_ms(load)
        print(f"  users={n_users:>5}  HIT   {fmt(hs)}")
        print(f"  users={n_users:>5}  MISS  {fmt(ms_)}")
        print(f"  users={n_users:>5}   └ load_click_matrix  {fmt(ls)}")
        print(f"  users={n_users:>5}  speed-up (p50 miss / p50 hit): "
              f"{ms_['p50'] / hs['p50']:.0f}x")
        out["sizes"].append({"users": n_users, "hit": hs, "miss": ms_,
                             "load_click_matrix": ls})
    r.flushdb()
    RESULTS["cache"] = out


# ── 3. End-to-end Kafka → Redis ───────────────────────────────
def run_e2e():
    print(f"\n== 3. End-to-end: click → Kafka → consumer → Redis "
          f"(topic '{BENCH_TOPIC}', DB {BENCH_DB}) ==")
    from kafka import KafkaConsumer, TopicPartition
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError

    admin = KafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    try:
        admin.create_topics([NewTopic(BENCH_TOPIC, 1, 1)])
        time.sleep(2)
    except TopicAlreadyExistsError:
        pass

    r = bench_redis()
    r.flushdb()
    rec = patch_recommender(r)

    # Reuse the real producer/consumer code, redirected to bench topic/DB
    import producer
    import consumer
    producer.TOPIC = BENCH_TOPIC
    producer.print = _quiet
    consumer.consumer.close()
    kc = KafkaConsumer(bootstrap_servers=BOOTSTRAP,
                       value_deserializer=lambda v: json.loads(v.decode()))
    tp = TopicPartition(BENCH_TOPIC, 0)
    kc.assign([tp])
    kc.seek_to_end(tp)
    kc.position(tp)                         # resolve offset before producing
    consumer.consumer = kc
    consumer.cache = r
    consumer.print = _quiet
    consumer.start_consumer_thread()

    items = producer.ITEMS
    users = producer.USERS
    rng = random.Random(SEED)

    def wait_for(key, field, target, timeout=10.0):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            v = r.hget(key, field)
            if v is not None and int(v) >= target:
                return True
            time.sleep(0.0002)
        return False

    # Warm-up (first produce does metadata fetch, consumer first fetch)
    producer.send_click("warm", "warm")
    wait_for("clicks:warm", "warm", 1)

    # 3a. Ingest latency: send_click() → HINCRBY visible in Redis
    send_t, ingest_t = [], []
    expected = {}
    for _ in range(300):
        u, it = rng.choice(users), rng.choice(items)
        expected[(u, it)] = expected.get((u, it), 0) + 1
        t0 = time.perf_counter_ns()
        producer.send_click(u, it)
        t1 = time.perf_counter_ns()
        ok = wait_for(f"clicks:{u}", it, expected[(u, it)])
        t2 = time.perf_counter_ns()
        if ok:
            send_t.append(t1 - t0)
            ingest_t.append(t2 - t0)
    ss, is_ = stats_ms(send_t), stats_ms(ingest_t)
    print(f"  send_click() (produce+flush)   {fmt(ss)}")
    print(f"  click → visible in Redis       {fmt(is_)}")

    # 3b. The app's click flow: send_click → delete recs → get_recommendations
    #     immediately. Is the new click in the matrix the model reads?
    real_loader = rec.load_click_matrix
    snapshot = {}

    def recording_loader():
        m, a = real_loader()
        snapshot["m"] = m
        return m, a
    rec.load_click_matrix = recording_loader

    flow_t, stale = [], 0
    trials = 200
    try:
        for _ in range(trials):
            u, it = rng.choice(users), rng.choice(items)
            before = int(r.hget(f"clicks:{u}", it) or 0)
            t0 = time.perf_counter_ns()
            producer.send_click(u, it)
            r.delete(f"recs:{u}")
            rec.get_recommendations(u)
            flow_t.append(time.perf_counter_ns() - t0)
            seen = snapshot["m"].get(u, {}).get(it, 0)
            if seen <= before:
                stale += 1
            wait_for(f"clicks:{u}", it, before + 1)   # settle before next
    finally:
        rec.load_click_matrix = real_loader
    fs = stats_ms(flow_t)
    print(f"  app flow (click → fresh recs)  {fmt(fs)}")
    print(f"  stale reads: {stale}/{trials} ({100 * stale / trials:.1f}%) — "
          f"recs computed before the consumer applied the click "
          f"(and then cached for 60s)")

    # 3c. Throughput: blast N events, measure produce rate + drain time
    N = 20_000
    r.delete("clicks:tp")
    t0 = time.perf_counter()
    for i in range(N):
        producer.producer.send(BENCH_TOPIC, value={
            "user_id": "tp", "item_id": items[i % len(items)],
            "timestamp": time.time(), "action": "click"})
    producer.producer.flush()
    t_prod = time.perf_counter() - t0
    while True:
        done = sum(int(v) for v in r.hvals("clicks:tp"))
        if done >= N or time.perf_counter() - t0 > 300:
            break
        time.sleep(0.05)
    t_all = time.perf_counter() - t0
    print(f"  throughput: produced {N} events in {t_prod:.2f}s "
          f"({N / t_prod:,.0f} ev/s); consumer applied {done} in "
          f"{t_all:.2f}s ({done / t_all:,.0f} ev/s end-to-end)")

    RESULTS["e2e"] = {
        "send_click": ss, "ingest": is_, "app_flow": fs,
        "stale_reads": stale, "stale_trials": trials,
        "throughput": {"events": N, "applied": done,
                       "produce_s": t_prod, "end_to_end_s": t_all},
    }

    kc.close()
    r.flushdb()
    try:
        admin.delete_topics([BENCH_TOPIC])
    except Exception:
        pass
    admin.close()


# ── Test conditions ───────────────────────────────────────────
def environment():
    import sklearn
    env = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "os": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scikit-learn": sklearn.__version__,
        "redis-py": redis.__version__,
        "seed": SEED,
    }
    try:
        import kafka
        env["kafka-python"] = kafka.__version__
    except ImportError:
        pass
    try:
        env["redis_server"] = bench_redis().info("server")["redis_version"]
    except Exception:
        env["redis_server"] = "unavailable"
    try:
        env["docker"] = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        env["docker"] = "unavailable"
    if sys.platform == "win32":
        try:
            ps = ("(Get-CimInstance Win32_Processor).Name;"
                  "[math]::Round((Get-CimInstance Win32_ComputerSystem)"
                  ".TotalPhysicalMemory/1GB,1)")
            lines = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                   capture_output=True, text=True,
                                   timeout=20).stdout.split("\n")
            env["cpu"], env["ram_gb"] = lines[0].strip(), lines[1].strip()
        except Exception:
            pass
    return env


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")   # Windows consoles default to cp1252
    wanted = sys.argv[1:] or ["scaling", "cache", "e2e"]
    RESULTS["environment"] = environment()
    print("Test conditions:")
    for k, v in RESULTS["environment"].items():
        print(f"  {k:<14} {v}")

    runners = {"scaling": run_scaling, "cache": run_cache, "e2e": run_e2e}
    for name in wanted:
        runners[name]()

    out = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out, "w") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nRaw results written to {out}")

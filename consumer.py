from kafka import KafkaConsumer
from collections import defaultdict
import json
import redis
import threading
import time

# ── Connections ───────────────────────────────────────────────
consumer = KafkaConsumer(
    'user-clicks',
    bootstrap_servers='localhost:9092',
    auto_offset_reset='earliest',
    value_deserializer=lambda v: json.loads(v.decode('utf-8'))
)

cache = redis.Redis(host='localhost', port=6379, decode_responses=True)

TOPIC = 'user-clicks'

# ── In-memory click store ─────────────────────────────────────
# Structure: { user_id: { item_id: click_count } }
# Example:   { "user_3": { "Python Tutorial": 4, "Docker Guide": 2 } }
click_matrix = defaultdict(lambda: defaultdict(int))

MAX_BATCH = 500   # max events per poll / Redis pipeline

def applied_key(topic, partition):
    # Last Kafka offset whose click is in Redis. Deliberately outside the
    # clicks:* namespace so the recommender never reads it as a user.
    return f"applied:{topic}:{partition}"

# ── Core consume loop ─────────────────────────────────────────
def consume():
    print("[Consumer] Listening for events on 'user-clicks'...\n")
    while True:
        # poll() returns as soon as any records are available, so a single
        # click is still written right away; under load, events arrive in
        # batches and are synced to Redis in one pipelined round trip.
        batches = consumer.poll(timeout_ms=1000, max_records=MAX_BATCH)
        pipe = cache.pipeline(transaction=False)
        pending = 0
        touched_users = set()

        for tp, records in batches.items():
            for message in records:
                event = message.value

                user_id  = event.get("user_id")
                item_id  = event.get("item_id")
                action   = event.get("action")

                if not user_id or not item_id:
                    print(f"[Consumer] Skipping malformed event: {event}")
                    continue

                if action != "click":
                    continue

                # Update in-memory matrix
                click_matrix[user_id][item_id] += 1

                print(f"[Consumer] Received → user: {user_id} | item: {item_id} | "
                      f"total clicks: {click_matrix[user_id][item_id]}")

                # Queue the Redis update
                pipe.hincrby(f"clicks:{user_id}", item_id, 1)
                touched_users.add(user_id)
                pending += 1

            # Queued after the HINCRBYs, so once a reader sees this offset
            # every click up to it is already applied.
            if records:
                pipe.set(applied_key(tp.topic, tp.partition), records[-1].offset)

        # Invalidate on write: drop cached recs of every user whose clicks
        # changed, after the HINCRBYs, so recs computed from the old counts
        # don't survive for the rest of their 60s TTL.
        for user_id in touched_users:
            pipe.delete(f"recs:{user_id}")

        # Sync the whole batch to Redis
        if len(pipe):
            pipe.execute()
        if pending:
            print(f"[Cache] Updated Redis → {pending} click(s)")

# ── Read-your-writes for the app ─────────────────────────────
def wait_until_applied(record_metadata, timeout=2.0):
    """
    Block until the consumer has written the click sent as
    record_metadata (returned by producer.send_click) to Redis.
    Returns False on timeout, e.g. if the consumer isn't running.
    """
    key = applied_key(record_metadata.topic, record_metadata.partition)
    deadline = time.perf_counter() + timeout
    while True:
        applied = cache.get(key)
        if applied is not None and int(applied) >= record_metadata.offset:
            return True
        if time.perf_counter() >= deadline:
            return False
        time.sleep(0.001)

# ── Run consumer in a background thread ──────────────────────
def start_consumer_thread():
    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    return thread

# ── Run directly to test ──────────────────────────────────────
if __name__ == "__main__":
    consume()
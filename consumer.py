from kafka import KafkaConsumer
from collections import defaultdict
import json
import redis
import threading

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

        for records in batches.values():
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
                pending += 1

        # Sync the whole batch to Redis
        if pending:
            pipe.execute()
            print(f"[Cache] Updated Redis → {pending} click(s)")

# ── Run consumer in a background thread ──────────────────────
def start_consumer_thread():
    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    return thread

# ── Run directly to test ──────────────────────────────────────
if __name__ == "__main__":
    consume()
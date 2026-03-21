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

# ── Helper: push updated counts to Redis ─────────────────────
def update_redis(user_id: str, item_id: str):
    redis_key = f"clicks:{user_id}"
    cache.hincrby(redis_key, item_id, 1)
    print(f"[Cache] Updated Redis → {redis_key} | {item_id}")

# ── Core consume loop ─────────────────────────────────────────
def consume():
    print("[Consumer] Listening for events on 'user-clicks'...\n")
    for message in consumer:
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

        # Sync to Redis
        update_redis(user_id, item_id)

# ── Run consumer in a background thread ──────────────────────
def start_consumer_thread():
    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    return thread

# ── Run directly to test ──────────────────────────────────────
if __name__ == "__main__":
    consume()
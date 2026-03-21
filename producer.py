from kafka import KafkaProducer
import json
import time
import random

# ── Connection ────────────────────────────────────────────────
producer = KafkaProducer(
    bootstrap_servers='localhost:9092',
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

TOPIC = 'user-clicks'

# ── Sample data (simulates a real catalogue) ──────────────────
ITEMS = [
    "Python Tutorial",
    "Machine Learning Basics",
    "Docker for Beginners",
    "Redis Crash Course",
    "Kafka in 10 Minutes",
    "Data Structures in Python",
    "SQL for Data Science",
    "FastAPI Guide",
    "Streamlit Dashboard",
    "Deep Learning with PyTorch",
]

USERS = [f"user_{i}" for i in range(1, 11)]   # user_1 … user_10

# ── Core function (called by Streamlit app later) ─────────────
def send_click(user_id: str, item_id: str):
    event = {
        "user_id": user_id,
        "item_id": item_id,
        "timestamp": time.time(),
        "action": "click"
    }
    producer.send(TOPIC, value=event)
    producer.flush()
    print(f"[Producer] Sent → {event}")

# ── Simulation mode (run this file directly to test) ──────────
if __name__ == "__main__":
    print(f"[Producer] Sending 20 simulated click events to '{TOPIC}'...\n")
    for _ in range(20):
        user = random.choice(USERS)
        item = random.choice(ITEMS)
        send_click(user, item)
        time.sleep(0.5)          # half-second gap between events
    print("\n[Producer] Done.")
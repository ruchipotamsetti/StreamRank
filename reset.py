from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import UnknownTopicOrPartitionError
import redis
import time

TOPIC = 'user-clicks'
BOOTSTRAP = 'localhost:9092'

print("[Reset] Connecting to Kafka...")
admin = KafkaAdminClient(bootstrap_servers=BOOTSTRAP)

# Delete topic if it exists
try:
    admin.delete_topics([TOPIC])
    print(f"[Reset] Deleted Kafka topic '{TOPIC}'")
    time.sleep(2)   # give Kafka a moment to finish deletion
except UnknownTopicOrPartitionError:
    print(f"[Reset] Topic '{TOPIC}' didn't exist, skipping")

# Recreate topic fresh
admin.create_topics([
    NewTopic(name=TOPIC, num_partitions=1, replication_factor=1)
])
print(f"[Reset] Recreated Kafka topic '{TOPIC}'")

# Flush Redis
r = redis.Redis(decode_responses=True)
r.flushall()
print("[Reset] Flushed all Redis data")

print("\n[Reset] Done — clean slate ready.")
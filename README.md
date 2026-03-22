# 🎬 StreamRank

> A real-time movie and series recommendation engine built with Apache Kafka, Redis, and collaborative filtering.

![StreamRank Demo](demo.gif)

---

## What is StreamRank?

StreamRank is a full-stack distributed systems project that simulates how platforms like Netflix and YouTube generate personalized recommendations in real time. Every time a user clicks on a title, that event is streamed through Apache Kafka, processed by a recommendation engine using collaborative filtering, and cached in Redis for instant retrieval — all reflected live in the UI.

---

## Architecture

```
┌─────────────┐     click event      ┌──────────────────┐     stream      ┌─────────────────────┐
│  Streamlit  │ ──────────────────▶  │   Kafka Topic    │ ──────────────▶ │   Python Consumer   │
│  Frontend   │                      │  "user-clicks"   │                 │  + Ranking Model    │
└─────────────┘                      └──────────────────┘                 └─────────┬───────────┘
       ▲                                                                             │
       │                                                                     updates │ click matrix
       │   serve recommendations                                                     ▼
       │                                                                   ┌─────────────────────┐
       └────────────────────────────────────────────────────────────────── │    Redis Cache      │
                                                                           │  recs:{user_id}     │
                                                                           └─────────────────────┘
```

### How it works — step by step

1. **User clicks a title** in the Streamlit UI
2. A **Kafka producer** sends a JSON event to the `user-clicks` topic:
   ```json
   { "user_id": "user_3", "item_id": "Inception", "timestamp": 1710000000, "action": "click" }
   ```
3. A **Kafka consumer** runs in a background thread, reading events in real time and updating an in-memory click matrix — a nested dictionary tracking how many times each user clicked each title
4. The updated click counts are **synced to Redis** using hash increments (`HINCRBY`)
5. When the UI requests recommendations, it checks **Redis first** (cache-aside pattern):
   - **Cache hit** → returns instantly from Redis (~0.1ms)
   - **Cache miss** → runs the collaborative filtering model, stores result in Redis with a 60-second TTL, then returns
6. The **collaborative filtering model** computes cosine similarity between users based on their click vectors, scores unseen titles by how much similar users clicked them, filters out already-watched titles, and returns the top-N ranked results
7. **Recommendations update live** in the UI after every click

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Message broker | Apache Kafka | Stream click events in real time |
| Cache | Redis | Cache hot recommendations, store click counts |
| Recommendation | scikit-learn | Cosine similarity collaborative filtering |
| Frontend | Streamlit | Interactive demo UI |
| Infrastructure | Docker + Docker Compose | Run Kafka and Redis locally |
| Language | Python 3.10 | All application code |

---

## Project Structure

```
streamrank/
├── docker-compose.yml    # Spins up Kafka, Zookeeper, and Redis
├── producer.py           # Sends click events to Kafka, holds catalogue
├── consumer.py           # Reads Kafka events, updates click matrix + Redis
├── recommender.py        # Collaborative filtering + Redis cache-aside logic
├── app.py                # Streamlit UI — genre filter, recommendations, stats
├── reset.py              # Wipes Kafka topic + Redis for a clean slate
└── check_redis.py        # Debug helper to inspect Redis click data
```

---

## Key Concepts Demonstrated

**Apache Kafka** — a distributed message queue used here as a real-time event stream. Click events are produced to a topic and consumed asynchronously, decoupling the UI from the recommendation logic exactly as Netflix and YouTube do at scale.

**Redis cache-aside pattern** — recommendations are never recomputed on every request. The system checks Redis first; only on a cache miss does it run the model, then stores the result with a TTL so stale data auto-expires.

**Collaborative filtering** — users are represented as vectors in item space. Cosine similarity measures the angle between user vectors — a small angle means similar taste. Recommendations are scored by how much similar users clicked each unseen title, weighted by their similarity score.

**Consumer groups** — the Kafka consumer runs in a background daemon thread inside Streamlit, keeping the click matrix continuously updated without blocking the UI.

---

## Prerequisites

- [Miniconda or Anaconda](https://docs.conda.io/en/latest/miniconda.html)
- [Docker Desktop](https://www.docker.com/products/docker-desktop)
- Git

---

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/ruchipotamsetti/StreamRank.git
cd streamrank
```

### 2. Create the conda environment

```bash
conda create -n streamrank python=3.10 -y
conda activate streamrank
pip install kafka-python redis scikit-learn pandas numpy streamlit
```

### 3. Start Kafka and Redis via Docker

```bash
docker-compose up -d
```

Verify all three containers are running:
```bash
docker-compose ps
```

You should see `zookeeper`, `kafka`, and `redis` all with status `Up`.

### 4. Create the Kafka topic

Replace `streamrank-kafka-1` with your actual Kafka container name from `docker-compose ps`:

```bash
docker exec -it streamrank-kafka-1 kafka-topics --create \
  --topic user-clicks \
  --bootstrap-server localhost:9092 \
  --partitions 1 \
  --replication-factor 1
```

### 5. Seed the system with click data (optional)

```bash
python producer.py
```

This sends 30 simulated click events across 10 users so the recommender has data to work with immediately.

### 6. Run the app

Open two terminal windows, both with the `streamrank` conda environment active.

**Terminal 1 — start the Kafka consumer:**
```bash
python consumer.py
```

**Terminal 2 — launch the Streamlit app:**
```bash
streamlit run app.py
```

The app opens automatically at `http://localhost:8501`.

---

## How to Use the App

1. **Select a user** from the dropdown in the top left
2. **Filter the catalogue** by genre using the dropdown
3. **Click any title** to simulate a watch event — this sends a Kafka message in real time
4. Watch the **Recommendations** column update instantly based on what similar users watched
5. Check the **Pipeline Stats** column to see click counts, most watched title, and genre breakdown
6. Switch between users to see how recommendations differ based on individual watch history

---

## Resetting the App

To wipe all Kafka events and Redis data for a clean slate:

```bash
python reset.py
```

---

## Stopping the App

```bash
docker-compose down
```

This stops and removes all Docker containers. Your conda environment stays intact.

---

## Why Python 3.10?

`kafka-python`, `scikit-learn`, and `streamlit` are all stable and well-tested on Python 3.10. Using the latest Python version risks subtle wheel incompatibilities with C-extension packages — particularly on Windows — which can cause difficult-to-debug install failures mid-project.

---

## Future Improvements

- Replace simulated users with real authentication
- Add implicit feedback signals (hover time, scroll depth) alongside clicks
- Upgrade to matrix factorization (SVD) or neural collaborative filtering for better accuracy
- Deploy with Upstash (serverless Kafka + Redis) for a fully live cloud version
- Add A/B testing to compare recommendation strategies

---

## License

MIT
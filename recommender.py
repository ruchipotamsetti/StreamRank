import redis
import json
from collections import defaultdict
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

# ── Connection ────────────────────────────────────────────────
cache = redis.Redis(host='localhost', port=6379, decode_responses=True)

# ── Step 1: Load click matrix from Redis ─────────────────────
def load_click_matrix():
    """
    Reads all clicks:* keys from Redis and builds a
    user-item matrix as a plain Python dict.

    Returns:
        matrix : { user_id: { item_id: click_count } }
        all_items : sorted list of every unique item
    """
    keys = cache.keys('clicks:*')
    matrix = {}

    for key in keys:
        user_id = key.split(':')[1]           # "clicks:user_3" → "user_3"
        clicks  = cache.hgetall(key)          # { "Python Tutorial": "4", ... }
        matrix[user_id] = {
            item: int(count)
            for item, count in clicks.items()
        }

    all_items = sorted({
        item
        for user_clicks in matrix.values()
        for item in user_clicks
    })

    return matrix, all_items


# ── Step 2: Build a numeric matrix numpy can work with ────────
def build_numpy_matrix(matrix, all_items):
    """
    Converts the dict matrix into a 2D numpy array.

    Rows    = users  (one row per user)
    Columns = items  (one column per item)
    Value   = click count (0 if user never clicked that item)

    Example (3 users, 3 items):
        [[ 4,  0,  2 ],   ← user_1
         [ 0,  3,  1 ],   ← user_2
         [ 2,  0,  3 ]]   ← user_3
    """
    users = sorted(matrix.keys())
    vectors = []

    for user in users:
        row = [matrix[user].get(item, 0) for item in all_items]
        vectors.append(row)

    return np.array(vectors, dtype=float), users


# ── Step 3: Recommend items for a given user ─────────────────
def recommend(user_id: str, top_n: int = 5):
    """
    Uses collaborative filtering to recommend items.

    Logic:
      1. Find users most similar to user_id (cosine similarity)
      2. Collect items those similar users clicked
      3. Filter out items user_id already clicked
      4. Rank by weighted score and return top_n

    Returns:
        list of (item_name, score) tuples — highest score first
    """
    matrix, all_items = load_click_matrix()

    if user_id not in matrix:
        print(f"[Recommender] No click history for {user_id}")
        return []

    np_matrix, users = build_numpy_matrix(matrix, all_items)

    # Compute cosine similarity between all users
    # Result is a (num_users x num_users) matrix
    # similarity[i][j] = how similar user i is to user j (0.0 → 1.0)
    similarity_matrix = cosine_similarity(np_matrix)

    user_index = users.index(user_id)
    similarity_scores = similarity_matrix[user_index]   # this user vs all others

    # Score each item based on how much similar users clicked it
    item_scores = defaultdict(float)
    already_clicked = set(matrix[user_id].keys())

    for other_index, similarity in enumerate(similarity_scores):
        if other_index == user_index:
            continue                                     # skip comparing to self
        if similarity <= 0:
            continue                                     # skip dissimilar users

        other_user = users[other_index]
        for item, clicks in matrix[other_user].items():
            if item not in already_clicked:              # only recommend NEW items
                item_scores[item] += similarity * clicks
    
    # Deduplicate items (keep highest score if item appears more than once)
    seen = set()
    deduped = []
    for item, score in sorted(item_scores.items(), key=lambda x: x[1], reverse=True):
        if item not in seen:
            seen.add(item)
            deduped.append((item, score))

    return deduped[:top_n]

    # Sort by score descending, return top_n
    # recommendations = sorted(
    #     item_scores.items(),
    #     key=lambda x: x[1],
    #     reverse=True
    # )[:top_n]

    # return recommendations


# ── Step 4: Cache recommendations in Redis ───────────────────
def get_recommendations(user_id: str, top_n: int = 5):
    """
    Cache-aside pattern:
      - Check Redis first for cached recommendations
      - If found (cache hit)  → return immediately
      - If not found (miss)   → compute, cache, then return
    """
    redis_key = f"recs:{user_id}"

    # Cache hit
    cached = cache.get(redis_key)
    if cached:
        print(f"[Cache] HIT  → {redis_key}")
        return json.loads(cached)

    # Cache miss — compute fresh recommendations
    print(f"[Cache] MISS → {redis_key} — computing...")
    recs = recommend(user_id, top_n)

    # Store in Redis for 60 seconds (TTL)
    # After 60s it expires and gets recomputed fresh next time
    cache.setex(redis_key, 60, json.dumps(recs))
    print(f"[Cache] Stored → {redis_key} (TTL: 60s)")

    return recs


# ── Test it directly ──────────────────────────────────────────
if __name__ == "__main__":
    test_users = ["user_1", "user_4", "user_7"]

    for user in test_users:
        print(f"\n{'─'*50}")
        print(f"Recommendations for {user}:")
        recs = get_recommendations(user)
        if recs:
            for rank, (item, score) in enumerate(recs, start=1):
                print(f"  {rank}. {item}  (score: {score:.3f})")
        else:
            print("  No recommendations found.")
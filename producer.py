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

# ── Catalogue ─────────────────────────────────────────────────
# Each entry: { "title": ..., "genre": ..., "type": "Movies"|"Series" }
CATALOGUE = [
    # Action / Thriller
    {"title": "Inception",                  "genre": "Action / Thriller", "type": "Movies"},
    {"title": "The Dark Knight",            "genre": "Action / Thriller", "type": "Movies"},
    {"title": "Mad Max: Fury Road",         "genre": "Action / Thriller", "type": "Movies"},
    {"title": "John Wick",                  "genre": "Action / Thriller", "type": "Movies"},
    {"title": "Mission: Impossible",        "genre": "Action / Thriller", "type": "Movies"},
    {"title": "Jack Ryan",                  "genre": "Action / Thriller", "type": "Series"},
    {"title": "24",                         "genre": "Action / Thriller", "type": "Series"},
    {"title": "Extraction",                 "genre": "Action / Thriller", "type": "Movies"},
    {"title": "The Gray Man",               "genre": "Action / Thriller", "type": "Movies"},

    # Sci-Fi / Fantasy
    {"title": "Interstellar",               "genre": "Sci-Fi / Fantasy",  "type": "Movies"},
    {"title": "Dune",                       "genre": "Sci-Fi / Fantasy",  "type": "Movies"},
    {"title": "The Matrix",                 "genre": "Sci-Fi / Fantasy",  "type": "Movies"},
    {"title": "Arrival",                    "genre": "Sci-Fi / Fantasy",  "type": "Movies"},
    {"title": "Black Mirror",               "genre": "Sci-Fi / Fantasy",  "type": "Series"},
    {"title": "Severance",                  "genre": "Sci-Fi / Fantasy",  "type": "Series"},
    {"title": "Dark",                       "genre": "Sci-Fi / Fantasy",  "type": "Series"},
    {"title": "Westworld",                  "genre": "Sci-Fi / Fantasy",  "type": "Series"},
    {"title": "Foundation",                 "genre": "Sci-Fi / Fantasy",  "type": "Series"},

    # Drama / Romance
    {"title": "The Shawshank Redemption",   "genre": "Drama / Romance",   "type": "Movies"},
    {"title": "Marriage Story",             "genre": "Drama / Romance",   "type": "Movies"},
    {"title": "Normal People",              "genre": "Drama / Romance",   "type": "Series"},
    {"title": "The Crown",                  "genre": "Drama / Romance",   "type": "Series"},
    {"title": "Before Sunrise",             "genre": "Drama / Romance",   "type": "Movies"},
    {"title": "Fleabag",                    "genre": "Drama / Romance",   "type": "Series"},
    {"title": "Succession",                 "genre": "Drama / Romance",   "type": "Series"},
    {"title": "The Notebook",               "genre": "Drama / Romance",   "type": "Movies"},

    # Comedy
    {"title": "The Office",                 "genre": "Comedy",            "type": "Series"},
    {"title": "Schitt's Creek",             "genre": "Comedy",            "type": "Series"},
    {"title": "Superbad",                   "genre": "Comedy",            "type": "Movies"},
    {"title": "What We Do in the Shadows",  "genre": "Comedy",            "type": "Series"},
    {"title": "The Grand Budapest Hotel",   "genre": "Comedy",            "type": "Movies"},
    {"title": "Abbott Elementary",          "genre": "Comedy",            "type": "Series"},
    {"title": "Game Night",                 "genre": "Comedy",            "type": "Movies"},
    {"title": "Brooklyn Nine-Nine",         "genre": "Comedy",            "type": "Series"},

    # Horror / Mystery
    {"title": "Get Out",                    "genre": "Horror / Mystery",  "type": "Movies"},
    {"title": "Hereditary",                 "genre": "Horror / Mystery",  "type": "Movies"},
    {"title": "The Haunting of Hill House", "genre": "Horror / Mystery",  "type": "Series"},
    {"title": "True Detective",             "genre": "Horror / Mystery",  "type": "Series"},
    {"title": "A Quiet Place",              "genre": "Horror / Mystery",  "type": "Movies"},
    {"title": "Mindhunter",                 "genre": "Horror / Mystery",  "type": "Series"},
    {"title": "The Fall",                   "genre": "Horror / Mystery",  "type": "Series"},
    {"title": "Midsommar",                  "genre": "Horror / Mystery",  "type": "Movies"},

    # Documentary
    {"title": "13th",                       "genre": "Documentary",       "type": "Movies"},
    {"title": "Our Planet",                 "genre": "Documentary",       "type": "Series"},
    {"title": "The Last Dance",             "genre": "Documentary",       "type": "Series"},
    {"title": "Free Solo",                  "genre": "Documentary",       "type": "Movies"},
    {"title": "Making a Murderer",          "genre": "Documentary",       "type": "Series"},
    {"title": "My Octopus Teacher",         "genre": "Documentary",       "type": "Movies"},

    # Crime
    {"title": "Breaking Bad",               "genre": "Crime",             "type": "Series"},
    {"title": "The Wire",                   "genre": "Crime",             "type": "Series"},
    {"title": "Ozark",                      "genre": "Crime",             "type": "Series"},
    {"title": "Goodfellas",                 "genre": "Crime",             "type": "Movies"},
    {"title": "Narcos",                     "genre": "Crime",             "type": "Series"},
    {"title": "The Godfather",              "genre": "Crime",             "type": "Movies"},
    {"title": "Mindhunter",                 "genre": "Crime",             "type": "Series"},
    {"title": "Parasite",                   "genre": "Crime",             "type": "Movies"},
    {"title": "Better Call Saul",           "genre": "Crime",             "type": "Series"},
]

# Flat list of titles (used by recommender + consumer)
ITEMS = [entry["title"] for entry in CATALOGUE]

# Genre lookup: title → genre
GENRE_MAP  = {entry["title"]: entry["genre"] for entry in CATALOGUE}

# Type lookup: title → Movies / Series
TYPE_MAP   = {entry["title"]: entry["type"]  for entry in CATALOGUE}

# All unique genres (for dropdown)
GENRES = ["All"] + sorted({entry["genre"] for entry in CATALOGUE})

USERS = [f"user_{i}" for i in range(1, 11)]

# ── Core send function ────────────────────────────────────────
def send_click(user_id: str, item_id: str):
    event = {
        "user_id":  user_id,
        "item_id":  item_id,
        "timestamp": time.time(),
        "action":   "click"
    }
    producer.send(TOPIC, value=event)
    producer.flush()
    print(f"[Producer] Sent → {event}")

# ── Simulation mode ───────────────────────────────────────────
if __name__ == "__main__":
    print(f"[Producer] Sending 30 simulated click events to '{TOPIC}'...\n")
    for _ in range(30):
        user = random.choice(USERS)
        item = random.choice(ITEMS)
        send_click(user, item)
        time.sleep(0.3)
    print("\n[Producer] Done.")
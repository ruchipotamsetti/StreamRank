import streamlit as st
import threading
import time
import redis as _redis
from producer import send_click, CATALOGUE, ITEMS, USERS, GENRES, GENRE_MAP, TYPE_MAP
from consumer import start_consumer_thread, click_matrix
from recommender import get_recommendations

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="StreamRank",
    page_icon="🎬",
    layout="wide"
)

# ── Start consumer thread once ────────────────────────────────
if "consumer_started" not in st.session_state:
    start_consumer_thread()
    st.session_state.consumer_started = True

# ── Session state defaults ────────────────────────────────────
if "selected_user"   not in st.session_state:
    st.session_state.selected_user  = USERS[0]
if "last_clicked"    not in st.session_state:
    st.session_state.last_clicked   = None
if "activity_log"    not in st.session_state:
    st.session_state.activity_log   = []
if "selected_genre"  not in st.session_state:
    st.session_state.selected_genre = "All"

# ── Header ────────────────────────────────────────────────────
st.title("🎬 StreamRank")
st.caption("Real-time movies & series recommendation engine · Kafka + Redis + Collaborative Filtering")
st.divider()

# ── Layout ────────────────────────────────────────────────────
col1, col2, col3 = st.columns([1, 1.6, 1.4])

# ══════════════════════════════════════════════════════════════
# COLUMN 1 — User selector + catalogue with genre filter
# ══════════════════════════════════════════════════════════════
with col1:
    st.subheader("👤 Select User")
    selected_user = st.selectbox(
        label="Active user",
        options=USERS,
        index=USERS.index(st.session_state.selected_user),
        label_visibility="collapsed"
    )
    st.session_state.selected_user = selected_user

    st.subheader("🎭 Browse Catalogue")

    # Genre filter dropdown
    selected_genre = st.selectbox(
        label="Filter by genre",
        options=GENRES,
        index=GENRES.index(st.session_state.selected_genre)
    )
    st.session_state.selected_genre = selected_genre

    # Filter catalogue by selected genre
    if selected_genre == "All":
        filtered = CATALOGUE
    else:
        filtered = [e for e in CATALOGUE if e["genre"] == selected_genre]

    st.caption(f"{len(filtered)} titles · click any to send event to Kafka")

    # Render buttons grouped by type (Movies first, then Series)
    for content_type in ["Movies", "Series"]:
        type_items = [e for e in filtered if e["type"] == content_type]
        if not type_items:
            continue

        st.markdown(
            f"<p style='font-size:15px; color:gray; margin:8px 0 4px;'>"
            f"{'🎬' if content_type == 'Movies' else '📺'} {content_type}</p>",
            unsafe_allow_html=True
        )

        for entry in type_items:
            title = entry["title"]
            if st.button(title, key=f"btn_{title}", use_container_width=True):
                send_click(selected_user, title)
                st.session_state.last_clicked = title
                log_entry = (
                    f"[{time.strftime('%H:%M:%S')}] "
                    f"{selected_user} → {title}"
                )
                st.session_state.activity_log.insert(0, log_entry)
                # Invalidate cached recs so next render is fresh
                _redis.Redis(decode_responses=True).delete(
                    f"recs:{selected_user}"
                )

# ══════════════════════════════════════════════════════════════
# COLUMN 2 — Live recommendations
# ══════════════════════════════════════════════════════════════
with col2:
    st.subheader("🎯 Recommended For You")
    st.caption(
        f"Personalised for {selected_user} · updates on every watch"
    )

    if st.session_state.last_clicked:
        genre_tag = GENRE_MAP.get(st.session_state.last_clicked, "")
        type_tag  = TYPE_MAP.get(st.session_state.last_clicked, "")
        st.success(
            f"Event sent to Kafka: **{st.session_state.last_clicked}** "
            f"· {type_tag} · {genre_tag}"
        )

    recs = get_recommendations(selected_user, top_n=5)

    if not recs:
        st.info(
            "No recommendations yet."
            "Watch a few titles to get started!"
        )
    else:
        max_score = recs[0][1] if recs else 1

        for rank, (title, score) in enumerate(recs, start=1):
            confidence  = int((score / max_score) * 100)
            genre_label = GENRE_MAP.get(title, "Unknown")
            type_label  = TYPE_MAP.get(title, "")
            type_icon   = "🎬" if type_label == "Movies" else "📺"

            with st.container():
                r1, r2 = st.columns([3, 1])
                with r1:
                    st.markdown(
                        f"**{rank}. {type_icon} {title}**  \n"
                        f"<span style='font-size:12px; color:gray'>"
                        f"{genre_label}</span>",
                        unsafe_allow_html=True
                    )
                    st.progress(confidence)
                with r2:
                    st.metric(label="score", value=f"{score:.2f}")
            st.divider()

# ══════════════════════════════════════════════════════════════
# COLUMN 3 — Pipeline stats + activity log
# ══════════════════════════════════════════════════════════════
with col3:
    st.subheader("📊 Pipeline Stats")

    user_clicks  = click_matrix.get(selected_user, {})
    total_clicks = sum(user_clicks.values())
    unique_items = len(user_clicks)

    m1, m2 = st.columns(2)
    m1.metric("Total watches", total_clicks)
    m2.metric("Unique titles", unique_items)

    if user_clicks:
        top_item      = max(user_clicks, key=user_clicks.get)
        top_genre     = GENRE_MAP.get(top_item, "")
        st.metric("Most watched", top_item)
        st.caption(f"Genre: {top_genre}")

    # Genre breakdown for this user
    if user_clicks:
        st.markdown("**Watch history by genre**")
        genre_counts: dict = {}
        for title, count in user_clicks.items():
            g = GENRE_MAP.get(title, "Unknown")
            genre_counts[g] = genre_counts.get(g, 0) + count

        for genre, count in sorted(
            genre_counts.items(), key=lambda x: x[1], reverse=True
        ):
            st.text(f"{genre}: {count} watch{'es' if count > 1 else ''}")

    st.divider()
    st.subheader("🔁 Activity Log")
    st.caption("Live Kafka events this session")

    if not st.session_state.activity_log:
        st.info("No activity yet.")
    else:
        for entry in st.session_state.activity_log[:8]:
            st.text(entry)

# ── Only rerun when a click just happened ─────────────────────
if st.session_state.last_clicked:
    st.session_state.last_clicked = None
    time.sleep(0.5)
    st.rerun()
import streamlit as st
import threading
import time
from producer import send_click, ITEMS, USERS
from consumer import start_consumer_thread, click_matrix
from recommender import get_recommendations

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="StreamRank",
    page_icon="⚡",
    layout="wide"
)

# ── Start consumer thread once in background ──────────────────
if "consumer_started" not in st.session_state:
    start_consumer_thread()
    st.session_state.consumer_started = True

# ── Session state defaults ────────────────────────────────────
if "selected_user" not in st.session_state:
    st.session_state.selected_user = USERS[0]

if "last_clicked" not in st.session_state:
    st.session_state.last_clicked = None

if "activity_log" not in st.session_state:
    st.session_state.activity_log = []

# ── Header ────────────────────────────────────────────────────
st.title("⚡ StreamRank")
st.caption("Real-time recommendation engine · Kafka + Redis + Collaborative Filtering")
st.divider()

# ── Layout: three columns ─────────────────────────────────────
col1, col2, col3 = st.columns([1, 1.6, 1.4])

# ══════════════════════════════════════════════════════════════
# COLUMN 1 — User selector + content catalogue
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

    st.subheader("📚 Content Catalogue")
    st.caption("Click any item to send an event to Kafka")

    for item in ITEMS:
        if st.button(item, key=f"btn_{item}", use_container_width=True):
            send_click(selected_user, item)
            st.session_state.last_clicked = item
            log_entry = f"[{time.strftime('%H:%M:%S')}] {selected_user} → {item}"
            st.session_state.activity_log.insert(0, log_entry)
            # Invalidate cached recommendations so they refresh
            import redis as _redis
            _redis.Redis(decode_responses=True).delete(f"recs:{selected_user}")

# ══════════════════════════════════════════════════════════════
# COLUMN 2 — Live recommendations
# ══════════════════════════════════════════════════════════════
with col2:
    st.subheader("🎯 Recommendations")
    st.caption(f"Personalised for {selected_user} · updates on every click")

    if st.session_state.last_clicked:
        st.success(f"Event sent to Kafka: **{st.session_state.last_clicked}**")

    recs = get_recommendations(selected_user, top_n=5)

    if not recs:
        st.info("No recommendations yet — click a few items to get started!")
    else:
        for rank, (item, score) in enumerate(recs, start=1):
            # Normalise score to a 0-100 confidence bar
            max_score = recs[0][1] if recs else 1
            confidence = int((score / max_score) * 100)

            with st.container():
                r1, r2 = st.columns([3, 1])
                with r1:
                    st.markdown(f"**{rank}. {item}**")
                    st.progress(confidence)
                with r2:
                    st.metric(label="score", value=f"{score:.2f}")
            st.divider()

# ══════════════════════════════════════════════════════════════
# COLUMN 3 — Pipeline stats + activity log
# ══════════════════════════════════════════════════════════════
with col3:
    st.subheader("📊 Pipeline Stats")

    # Click stats for selected user from in-memory matrix
    user_clicks = click_matrix.get(selected_user, {})
    total_clicks = sum(user_clicks.values())
    unique_items = len(user_clicks)

    m1, m2 = st.columns(2)
    m1.metric("Total clicks", total_clicks)
    m2.metric("Unique items", unique_items)

    # Top clicked item for this user
    if user_clicks:
        top_item = max(user_clicks, key=user_clicks.get)
        st.metric("Most clicked", top_item)

    st.subheader("🔁 Activity Log")
    st.caption("Live Kafka events this session")

    if not st.session_state.activity_log:
        st.info("No activity yet.")
    else:
        for entry in st.session_state.activity_log[:8]:
            st.text(entry)

# ── Auto-refresh every 3 seconds ─────────────────────────────
# time.sleep(3)
# st.rerun()

if st.session_state.last_clicked:
    st.session_state.last_clicked = None
    time.sleep(0.5)    # brief pause so Kafka consumer catches up
    st.rerun()
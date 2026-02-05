"""
Artist Stock App - Track and compare artist performance metrics.
Styled like the Apple Stocks app.
"""

import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, date
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path, override=True)
if not os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH"):
    os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"] = str(Path.home() / ".snowflake" / "rsa_key.p8")

sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.snowflake_client import snowflake_client
from src.spotify_client import spotify_client
from src.storage import load_tracked_artists, add_tracked_artist, remove_tracked_artist
from src.data_cache import data_cache
from src.models import ArtistMetrics, ArtistSummary, TimeSeriesPoint, TikTokSound
from src.deal_analysis import (
    DealAnalyzer, DealAnalysisRequest, DealAnalysisResult,
    get_analyzer, AVAILABLE_GENRES
)
from src.deal_storage import (
    save_deal_analysis, load_all_analyses, get_analyses_for_artist,
    delete_analysis, get_analyses_summary
)
from src.chartex_client import chartex_client
from src.sound_storage import load_tracked_sounds, add_tracked_sound, remove_tracked_sound

st.set_page_config(page_title="Artist Stock App", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")


def refresh_artist_data(artist_id: str, force: bool = False) -> None:
    if not force and not data_cache.needs_refresh(artist_id):
        return
    try:
        streaming = snowflake_client.get_streaming_time_series([artist_id], lookback_months=24)
        data_cache.set_streaming_data(
            artist_id,
            streaming.get("us_streams", []),
            streaming.get("global_streams", []),
            streaming.get("us_video_streams", [])
        )
    except:
        pass
    try:
        social = snowflake_client.get_social_time_series([artist_id], lookback_months=24)
        data_cache.set_social_data(artist_id, social.get("spotify", []), social.get("instagram", []), social.get("tiktok", []))
    except:
        pass


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_metrics_from_snowflake(artist_ids_tuple):
    """Internal function to fetch metrics from Snowflake (cached by Streamlit)."""
    try:
        return snowflake_client.get_artist_metrics(list(artist_ids_tuple), fast=True)
    except:
        return {}


def get_cached_metrics(artist_ids_tuple):
    """Get metrics, using session state cache first to avoid duplicate queries."""
    # Check session state first for individual artist lookups
    if "metrics_cache" not in st.session_state:
        st.session_state.metrics_cache = {}

    # If all requested IDs are in session cache, return from there
    result = {}
    missing_ids = []
    for aid in artist_ids_tuple:
        if aid in st.session_state.metrics_cache:
            result[aid] = st.session_state.metrics_cache[aid]
        else:
            missing_ids.append(aid)

    # Fetch any missing IDs from Snowflake
    if missing_ids:
        fetched = _fetch_metrics_from_snowflake(tuple(missing_ids))
        for aid, metrics in fetched.items():
            st.session_state.metrics_cache[aid] = metrics
            result[aid] = metrics

    return result


@st.cache_data(ttl=600, show_spinner=False)
def get_similar_artists_cached(spotify_id, name):
    if not spotify_id:
        return []
    try:
        return spotify_client.get_similar_artists(ArtistSummary(name=name, spotify_id=spotify_id))
    except:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def lookup_sodatone_ids_cached(spotify_ids_tuple):
    try:
        return snowflake_client.lookup_sodatone_ids(list(spotify_ids_tuple))
    except:
        return {}


def preload_all_data():
    """Preload all tracked artist data on first load."""
    if "data_preloaded" in st.session_state:
        return
    tracked = load_tracked_artists()
    if tracked:
        # Refresh time series data for all artists
        for artist in tracked:
            refresh_artist_data(artist.sodatone_id)
        # Fetch all metrics in one query and store in session cache
        all_ids = tuple(a.sodatone_id for a in tracked)
        metrics = _fetch_metrics_from_snowflake(all_ids)
        if "metrics_cache" not in st.session_state:
            st.session_state.metrics_cache = {}
        st.session_state.metrics_cache.update(metrics)
    st.session_state.data_preloaded = True


# CSS
st.markdown("""
<style>
#MainMenu, footer, header, .stDeployButton {visibility: hidden; display: none;}
.stApp {background-color: #000000;}
.main .block-container {padding-top: 2rem; padding-bottom: 2rem; max-width: 900px;}
.page-title {font-size: 34px; font-weight: 700; color: #ffffff; margin-bottom: 4px;}
.page-subtitle {font-size: 14px; color: #8e8e93; margin-bottom: 20px;}
.metric-large {font-size: 48px; font-weight: 700; color: #ffffff; line-height: 1;}
.metric-row {display: flex; gap: 24px; margin-top: 8px; flex-wrap: wrap;}
.metric-item {font-size: 14px;}
.metric-label {color: #8e8e93; margin-right: 4px;}
.stat-card {background-color: #1c1c1e; border-radius: 12px; padding: 16px; margin-bottom: 12px;}
.stat-label {font-size: 13px; color: #8e8e93; margin-bottom: 8px;}
.stat-value {font-size: 28px; font-weight: 600; color: #ffffff;}
.stat-change-positive {font-size: 13px; color: #34c759; margin-top: 4px;}
.stat-change-negative {font-size: 13px; color: #ff3b30; margin-top: 4px;}
.stat-change-neutral {font-size: 13px; color: #8e8e93; margin-top: 4px;}
.section-header {font-size: 20px; font-weight: 600; color: #ffffff; margin-top: 24px; margin-bottom: 12px;}
.chart-title {font-size: 14px; font-weight: 500; color: #8e8e93; margin-bottom: 8px;}
.compare-card {background-color: #1c1c1e; border-radius: 12px; padding: 12px; margin-bottom: 8px;}
.compare-name {font-size: 15px; font-weight: 500; color: #ffffff;}
.social-positive {color: #34c759;}
.social-negative {color: #ff3b30;}
.social-neutral {color: #8e8e93;}
.stTextInput > div > div > input {background-color: #1c1c1e; border: none; border-radius: 10px; color: #ffffff;}
.stButton > button {background-color: #2c2c2e; color: #ffffff; border: none; border-radius: 8px; font-weight: 500;}
.stButton > button:hover {background-color: #3c3c3e;}
/* Artist card styling */
.artist-card {
    background-color: #1c1c1e;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 0;
    cursor: pointer;
}
/* Button that follows the card - make it overlay using negative margin */
[data-testid="stMarkdown"]:has(.artist-card) + div [data-testid="stButton"] button {
    background: transparent !important;
    border: none !important;
    color: transparent !important;
    min-height: 100px !important;
    height: 100px !important;
    margin-top: -108px !important;
    margin-bottom: 16px !important;
    border-radius: 12px !important;
    cursor: pointer !important;
}
[data-testid="stMarkdown"]:has(.artist-card) + div [data-testid="stButton"] button:hover {
    background: rgba(255, 255, 255, 0.05) !important;
}
[data-testid="stMarkdown"]:has(.artist-card) + div [data-testid="stButton"] button:focus {
    box-shadow: none !important;
    outline: none !important;
}
</style>
""", unsafe_allow_html=True)


def format_number(num):
    if num is None or num == 0:
        return "0"
    if abs(num) >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    if abs(num) >= 1_000:
        return f"{num/1_000:.1f}K"
    return f"{num:,.0f}"


def format_change(change, include_sign=True):
    if change is None or change == 0:
        return "0%", "neutral"
    pct = change * 100 if abs(change) < 1 else change
    sign = "+" if pct > 0 and include_sign else ""
    direction = "positive" if pct > 0 else "negative"
    return f"{sign}{pct:.1f}%", direction


def get_period_days(period: str) -> int:
    return {"1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "2Y": 730}.get(period, 30)


def trim_recent_streaming_data(data_points, days_to_trim=2):
    if not data_points:
        return []
    cutoff = date.today() - timedelta(days=days_to_trim)
    return [p for p in data_points if p.date <= cutoff]


def pad_data_for_period(data_points, period: str, reference_end_date=None):
    """Pad data to fill a complete period.

    Args:
        data_points: List of TimeSeriesPoint
        period: Period string (1W, 1M, etc.)
        reference_end_date: If provided, use this as the end date for alignment.
                           This ensures multiple datasets align properly.
    """
    if not data_points:
        return []
    days = get_period_days(period)
    # Use reference date if provided, otherwise use max date from data
    if reference_end_date:
        end_date = reference_end_date
    else:
        end_date = max(p.date for p in data_points) if data_points else date.today()
    start_date = end_date - timedelta(days=days)
    data_dict = {p.date: p.value for p in data_points}
    padded = []
    current = start_date
    while current <= end_date:
        padded.append(TimeSeriesPoint(date=current, value=data_dict.get(current, 0.0)))
        current += timedelta(days=1)
    return padded


def calculate_period_change(data_points, period: str):
    if not data_points or len(data_points) < 2:
        return 0.0
    days = get_period_days(period)
    end_date = max(p.date for p in data_points) if data_points else date.today()
    cutoff = end_date - timedelta(days=days)
    filtered = sorted([p for p in data_points if p.date >= cutoff], key=lambda x: x.date)
    if len(filtered) < 2 or filtered[0].value == 0:
        return 0.0
    return (filtered[-1].value - filtered[0].value) / filtered[0].value


def create_sparkline_svg(values, is_positive=True, width=80, height=32):
    if not values or len(values) < 2:
        values = [50] * 10
    color = "#34c759" if is_positive else "#ff3b30"
    min_val, max_val = min(values), max(values)
    val_range = max_val - min_val if max_val != min_val else 1
    points = [f"{(i / (len(values) - 1)) * width:.1f},{height - ((v - min_val) / val_range) * (height - 4) - 2:.1f}" for i, v in enumerate(values)]
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"><path d="M {" L ".join(points)}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round"/></svg>'


def create_chart(data_points, height=200, color="#34c759"):
    if not data_points:
        return go.Figure()
    dates = [p.date for p in data_points]
    values = [p.value for p in data_points]
    fill_colors = {"#34c759": "rgba(52, 199, 89, 0.15)", "#007aff": "rgba(0, 122, 255, 0.15)",
                   "#1DB954": "rgba(29, 185, 84, 0.15)", "#E1306C": "rgba(225, 48, 108, 0.15)", "#00f2ea": "rgba(0, 242, 234, 0.15)"}
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=values, mode='lines', line=dict(color=color, width=2), fill='tozeroy', fillcolor=fill_colors.get(color, "rgba(100,100,100,0.15)"), hovertemplate='<b>%{x|%b %d}</b><br>%{y:,.0f}<extra></extra>'))
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=10, b=30), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False,
                     xaxis=dict(showgrid=False, showline=False, tickfont=dict(color='#8e8e93', size=10), tickformat='%b %d'),
                     yaxis=dict(showgrid=False, showline=False, visible=False), hovermode='x unified',
                     hoverlabel=dict(bgcolor='#1c1c1e', font_size=12, font_color='#ffffff'))
    return fig


def create_comparison_chart(datasets, height=300):
    colors = ["#34c759", "#ff9500", "#af52de", "#007aff", "#ff3b30", "#00f2ea"]
    fig = go.Figure()
    for i, (name, data_points) in enumerate(datasets.items()):
        if data_points:
            fig.add_trace(go.Scatter(x=[p.date for p in data_points], y=[p.value for p in data_points], mode='lines', name=name, line=dict(color=colors[i % len(colors)], width=2)))
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=30, b=30), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=True,
                     legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(color='#ffffff', size=11)),
                     xaxis=dict(showgrid=False, showline=False, tickfont=dict(color='#8e8e93', size=10), tickformat='%b %d'),
                     yaxis=dict(showgrid=True, gridcolor='rgba(142,142,147,0.2)', showline=False, tickfont=dict(color='#8e8e93', size=10)),
                     hovermode='x unified', hoverlabel=dict(bgcolor='#1c1c1e', font_size=12, font_color='#ffffff'))
    return fig


def render_summary_page():
    preload_all_data()
    st.markdown('<div class="page-title">Artists</div>', unsafe_allow_html=True)
    tracked = load_tracked_artists()
    st.markdown(f'<div class="page-subtitle">{len(tracked)} artists tracked</div>', unsafe_allow_html=True)

    # Navigation buttons
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("View Deals", key="view_deals_btn", use_container_width=True):
            st.session_state.page = "deals"
            st.rerun()

    with st.expander("➕ Add Artist"):
        add_query = st.text_input("Search for artist to add", placeholder="Enter artist name...", key="add_search")
        if add_query and len(add_query) >= 2:
            # Search Spotify first for artist names
            try:
                with st.spinner("Searching Spotify..."):
                    spotify_results = spotify_client.search_artists(add_query, limit=8)
            except Exception as e:
                st.error(f"Spotify search failed: {e}")
                spotify_results = []

            if spotify_results:
                for i, result in enumerate(spotify_results[:5]):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.write(f"**{result.name}**")
                    with col2:
                        if result.spotify_id and st.button("Add", key=f"add_spotify_{i}_{result.spotify_id}"):
                            # Lookup sodatone_id from Snowflake using spotify_id
                            with st.spinner("Loading artist data..."):
                                try:
                                    mapping = snowflake_client.lookup_sodatone_ids([result.spotify_id])
                                    sodatone_id = mapping.get(result.spotify_id)
                                    if sodatone_id:
                                        add_tracked_artist(
                                            sodatone_id=sodatone_id,
                                            name=result.name,
                                            spotify_id=result.spotify_id,
                                            image_url=result.image_url
                                        )
                                        refresh_artist_data(sodatone_id, force=True)
                                        st.rerun()
                                    else:
                                        st.error(f"Artist '{result.name}' not found in database")
                                except Exception as e:
                                    st.error(f"Failed to add artist: {e}")
            elif add_query:
                st.caption("No artists found on Spotify")

    st.markdown("---")

    if tracked:
        metrics_dict = get_cached_metrics(tuple(a.sodatone_id for a in tracked))

        for idx, artist in enumerate(tracked):
            metrics = metrics_dict.get(artist.sodatone_id)

            # Get display name - use metrics name if available, otherwise use stored name
            display_name = metrics.name if metrics else artist.name

            # Get metrics values or use defaults
            if metrics:
                weekly_streams = metrics.streaming.weekly_us_streams or 0
                change = metrics.streaming.us_wow_change or 0
                sf = metrics.social.spotify_followers or 0
                sf_change, sf_dir = format_change(metrics.social.spotify_followers_change)
                ig = metrics.social.instagram_followers or 0
                ig_change, ig_dir = format_change(metrics.social.instagram_followers_change)
                tt = metrics.social.tiktok_followers or 0
                tt_change, tt_dir = format_change(metrics.social.tiktok_followers_change)
            else:
                # Defaults when metrics unavailable
                weekly_streams = 0
                change = 0
                sf, ig, tt = 0, 0, 0
                sf_change, sf_dir = "0%", "neutral"
                ig_change, ig_dir = "0%", "neutral"
                tt_change, tt_dir = "0%", "neutral"

            change_text, direction = format_change(change)
            is_positive = change >= 0

            sparkline_values = data_cache.get_sparkline_values(artist.sodatone_id, "us_streams")
            sparkline_svg = create_sparkline_svg(sparkline_values, is_positive, width=70, height=28)

            col1, col2 = st.columns([20, 1])
            with col1:
                # Card display
                card_html = f'''
                <div class="artist-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 16px;">
                        <div style="flex: 1;">
                            <div style="font-size: 17px; font-weight: 600; color: #ffffff;">{display_name}</div>
                            <div style="font-size: 13px; color: #8e8e93;">{format_number(weekly_streams)} streams/wk</div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 12px;">
                            {sparkline_svg}
                            <div style="text-align: right;">
                                <div style="font-size: 17px; font-weight: 600; color: {'#34c759' if is_positive else '#ff3b30'};">{change_text}</div>
                                <div style="font-size: 11px; color: #8e8e93;">this week</div>
                            </div>
                        </div>
                    </div>
                    <div style="display: flex; gap: 20px; margin-top: 12px; font-size: 12px; color: #8e8e93;">
                        <span>🎧 SF {format_number(sf)} <span style="color: {'#34c759' if sf_dir == 'positive' else '#ff3b30' if sf_dir == 'negative' else '#8e8e93'};">{sf_change}</span></span>
                        <span>📷 IG {format_number(ig)} <span style="color: {'#34c759' if ig_dir == 'positive' else '#ff3b30' if ig_dir == 'negative' else '#8e8e93'};">{ig_change}</span></span>
                        <span>🎵 TT {format_number(tt)} <span style="color: {'#34c759' if tt_dir == 'positive' else '#ff3b30' if tt_dir == 'negative' else '#8e8e93'};">{tt_change}</span></span>
                    </div>
                </div>
                '''
                st.markdown(card_html, unsafe_allow_html=True)

                # View button - click to go to detail page
                if st.button(f"📊 View {display_name}", key=f"card_{idx}", use_container_width=True):
                    st.session_state.selected_artist = artist.sodatone_id
                    st.session_state.selected_spotify_id = artist.spotify_id
                    st.session_state.page = "detail"
                    st.rerun()

            with col2:
                st.markdown("<div style='height: 70px'></div>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"del_{artist.sodatone_id}"):
                    remove_tracked_artist(artist.sodatone_id)
                    data_cache.clear_artist(artist.sodatone_id)
                    st.rerun()
    else:
        st.info("No artists tracked yet. Use the Add Artist section above.")

    # ========== TikTok Sounds Section ==========
    st.markdown("---")
    st.markdown('<div class="section-header">🎵 TikTok Sounds</div>', unsafe_allow_html=True)

    tracked_sounds = load_tracked_sounds()
    st.markdown(f'<div class="page-subtitle">{len(tracked_sounds)} sounds tracked</div>', unsafe_allow_html=True)

    # Add Sound expander
    with st.expander("➕ Add TikTok Sound"):
        st.caption("Enter a TikTok sound ID or URL. Add the sound in Chartex dashboard first.")

        sound_input = st.text_input(
            "Sound ID or TikTok URL",
            placeholder="e.g., 7171140178143266818 or https://tiktok.com/music/...",
            key="add_sound_input"
        )

        sound_name = st.text_input(
            "Sound Name (optional)",
            placeholder="e.g., Artist - Song Title",
            key="add_sound_name"
        )

        if sound_input:
            import re
            sound_id = None
            patterns = [
                r"tiktok\.com/music/[^/]+-(\d+)",
                r"tiktok\.com/music/(\d+)",
                r"^(\d+)$",
            ]
            for pattern in patterns:
                match = re.search(pattern, sound_input)
                if match:
                    sound_id = match.group(1)
                    break

            if sound_id:
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.success(f"Sound ID: {sound_id}")
                with col2:
                    if st.button("Add Sound", key="add_sound_btn"):
                        name = sound_name if sound_name else f"TikTok Sound {sound_id[-8:]}"
                        add_tracked_sound(sound_id=sound_id, name=name)
                        st.rerun()
                with col3:
                    if st.button("Test API", key="test_api_btn"):
                        # Test the Chartex API directly
                        import httpx
                        from src.config import settings
                        try:
                            url = f"https://chartex.com/external/v1/tiktok-sounds/{sound_id}/stats/tiktok-video-counts/"
                            headers = {
                                "X-APP-ID": settings.chartex.app_id or "NOT SET",
                                "X-APP-TOKEN": settings.chartex.app_token or "NOT SET",
                            }
                            # follow_redirects=True to handle 308 redirects
                            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                                resp = client.get(url, headers=headers, params={"mode": "total"})
                            st.code(f"URL: {url}\nStatus: {resp.status_code}\nResponse: {resp.text[:500]}")
                        except Exception as e:
                            st.error(f"API Test Error: {e}")
            else:
                st.error("Could not extract sound ID.")

    # Display tracked sounds
    if tracked_sounds:
        for sound in tracked_sounds:
            # Fetch data from Chartex
            api_error = None
            try:
                sound_data = chartex_client.get_sound_data(sound.sound_id, lookback_days=30)
            except Exception as e:
                api_error = str(e)
                sound_data = TikTokSound(
                    sound_id=sound.sound_id,
                    name=sound.name,
                    total_views=0,
                    total_creates=0,
                )

            # Show API error if any
            if api_error:
                st.error(f"Chartex API Error: {api_error}")

            col1, col2 = st.columns([20, 1])
            with col1:
                card_html = f'''
                <div class="artist-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 16px;">
                        <div style="flex: 1;">
                            <div style="font-size: 17px; font-weight: 600; color: #ffffff;">{sound.name or sound_data.name}</div>
                            <div style="font-size: 13px; color: #8e8e93;">ID: {sound.sound_id[-12:]}</div>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-size: 17px; font-weight: 600; color: #ffffff;">{format_number(sound_data.total_views)} views</div>
                            <div style="font-size: 11px; color: #8e8e93;">{format_number(sound_data.total_creates)} creates</div>
                        </div>
                    </div>
                    <div style="display: flex; gap: 20px; margin-top: 12px; font-size: 12px; color: #8e8e93;">
                        <span>📈 7d views: <span style="color: {'#34c759' if sound_data.views_7d > 0 else '#8e8e93'};">+{format_number(sound_data.views_7d)}</span></span>
                        <span>🎬 7d creates: <span style="color: {'#34c759' if sound_data.creates_7d > 0 else '#8e8e93'};">+{format_number(sound_data.creates_7d)}</span></span>
                        <span>24h: +{format_number(sound_data.views_24h)} views</span>
                    </div>
                </div>
                '''
                st.markdown(card_html, unsafe_allow_html=True)

                if st.button(f"📊 View Details", key=f"view_sound_{sound.sound_id}", use_container_width=True):
                    st.session_state.selected_sound = sound.sound_id
                    st.session_state.page = "sound_detail"
                    st.rerun()

            with col2:
                st.markdown("<div style='height: 70px'></div>", unsafe_allow_html=True)
                if st.button("🗑️", key=f"del_sound_{sound.sound_id}"):
                    remove_tracked_sound(sound.sound_id)
                    st.rerun()
    else:
        st.info("No sounds tracked yet. Add a TikTok sound above.")


def render_detail_page():
    artist_id = st.session_state.get("selected_artist")
    if not artist_id:
        st.session_state.page = "summary"
        st.rerun()
        return

    if st.button("← Artists", key="back_btn"):
        st.session_state.page = "summary"
        st.session_state.pop("similar_artists", None)
        st.session_state.pop("compare_data", None)
        st.session_state.pop("compare_artists", None)
        st.rerun()

    if "view_mode" not in st.session_state:
        st.session_state.view_mode = "streams"
    if "time_period" not in st.session_state:
        st.session_state.time_period = "1M"

    metrics = get_cached_metrics((artist_id,)).get(artist_id)
    if not metrics:
        st.error("Could not load artist data.")
        return

    period = st.session_state.time_period

    # Get and process data
    raw_streaming = data_cache.get_streaming_data(artist_id, "1Y")
    raw_social = data_cache.get_social_data(artist_id, "1Y")

    trimmed_us = trim_recent_streaming_data(raw_streaming.get("us_streams", []), days_to_trim=2)
    trimmed_global = trim_recent_streaming_data(raw_streaming.get("global_streams", []), days_to_trim=2)

    streaming_data = {
        "us_streams": pad_data_for_period(trimmed_us, period),
        "global_streams": pad_data_for_period(trimmed_global, period),
    }
    social_data = {
        "spotify": pad_data_for_period(raw_social.get("spotify", []), period),
        "instagram": pad_data_for_period(raw_social.get("instagram", []), period),
        "tiktok": pad_data_for_period(raw_social.get("tiktok", []), period),
    }

    us_change = calculate_period_change(trimmed_us, period)
    sf_change = calculate_period_change(raw_social.get("spotify", []), period)
    ig_change = calculate_period_change(raw_social.get("instagram", []), period)
    tt_change = calculate_period_change(raw_social.get("tiktok", []), period)

    # Header
    st.markdown(f'<div class="page-title">{metrics.name}</div>', unsafe_allow_html=True)

    if st.session_state.view_mode == "streams":
        # Calculate total US streams for the selected period
        us_period_total = sum(p.value for p in streaming_data.get("us_streams", []))
        change_text, direction = format_change(us_change)
        period_label = {"1W": "Weekly", "1M": "Monthly", "3M": "3-Month", "6M": "6-Month", "1Y": "Yearly", "2Y": "2-Year"}.get(period, period)
        st.markdown(f'<div class="metric-large">{format_number(us_period_total)}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-item">{period_label} US Streams <span class="social-{direction}">({change_text})</span></div>', unsafe_allow_html=True)
    else:
        sf_text, sf_dir = format_change(sf_change)
        ig_text, ig_dir = format_change(ig_change)
        tt_text, tt_dir = format_change(tt_change)
        total = (metrics.social.spotify_followers or 0) + (metrics.social.instagram_followers or 0) + (metrics.social.tiktok_followers or 0)
        st.markdown(f'<div class="metric-large">{format_number(total)}</div>', unsafe_allow_html=True)
        st.markdown(f'''<div class="metric-row">
            <div class="metric-item"><span class="metric-label">SF</span><span class="social-{sf_dir}">{sf_text}</span></div>
            <div class="metric-item"><span class="metric-label">IG</span><span class="social-{ig_dir}">{ig_text}</span></div>
            <div class="metric-item"><span class="metric-label">TT</span><span class="social-{tt_dir}">{tt_text}</span></div>
        </div>''', unsafe_allow_html=True)

    # View toggle
    col1, col2 = st.columns([2, 4])
    with col1:
        view = st.radio("View", ["Streams", "Followers"], index=0 if st.session_state.view_mode == "streams" else 1, horizontal=True, label_visibility="collapsed", key="view_radio")
        new_mode = "streams" if view == "Streams" else "followers"
        if new_mode != st.session_state.view_mode:
            st.session_state.view_mode = new_mode
            st.rerun()

    # Period selector
    periods = ["1W", "1M", "3M", "6M", "1Y", "2Y"]
    selected = st.radio("Period", periods, index=periods.index(st.session_state.time_period), horizontal=True, label_visibility="collapsed", key="period_radio")
    if selected != st.session_state.time_period:
        st.session_state.time_period = selected
        st.rerun()

    # Charts
    if st.session_state.view_mode == "streams":
        st.markdown('<div class="chart-title">US Streams (Daily)</div>', unsafe_allow_html=True)
        st.plotly_chart(create_chart(streaming_data.get("us_streams", []), height=250, color="#34c759"), use_container_width=True, config={'displayModeBar': False})
        st.markdown('<div class="chart-title">Global Streams (Daily)</div>', unsafe_allow_html=True)
        st.plotly_chart(create_chart(streaming_data.get("global_streams", []), height=250, color="#007aff"), use_container_width=True, config={'displayModeBar': False})
    else:
        st.markdown('<div class="chart-title">🎧 Spotify Followers</div>', unsafe_allow_html=True)
        st.plotly_chart(create_chart(social_data.get("spotify", []), height=160, color="#1DB954"), use_container_width=True, config={'displayModeBar': False})
        st.markdown('<div class="chart-title">📷 Instagram Followers</div>', unsafe_allow_html=True)
        st.plotly_chart(create_chart(social_data.get("instagram", []), height=160, color="#E1306C"), use_container_width=True, config={'displayModeBar': False})
        st.markdown('<div class="chart-title">🎵 TikTok Followers</div>', unsafe_allow_html=True)
        st.plotly_chart(create_chart(social_data.get("tiktok", []), height=160, color="#00f2ea"), use_container_width=True, config={'displayModeBar': False})

    # Stats
    st.markdown('<div class="section-header">Current Stats</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        sf_text, sf_dir = format_change(sf_change)
        arrow = "↑" if sf_dir == "positive" else "↓" if sf_dir == "negative" else ""
        st.markdown(f'<div class="stat-card"><div class="stat-label">🎧 Spotify Followers</div><div class="stat-value">{format_number(metrics.social.spotify_followers or 0)}</div><div class="stat-change-{sf_dir}">{arrow} {sf_text} ({period})</div></div>', unsafe_allow_html=True)
        tt_text, tt_dir = format_change(tt_change)
        arrow = "↑" if tt_dir == "positive" else "↓" if tt_dir == "negative" else ""
        st.markdown(f'<div class="stat-card"><div class="stat-label">🎵 TikTok Followers</div><div class="stat-value">{format_number(metrics.social.tiktok_followers or 0)}</div><div class="stat-change-{tt_dir}">{arrow} {tt_text} ({period})</div></div>', unsafe_allow_html=True)
    with col2:
        ig_text, ig_dir = format_change(ig_change)
        arrow = "↑" if ig_dir == "positive" else "↓" if ig_dir == "negative" else ""
        st.markdown(f'<div class="stat-card"><div class="stat-label">📷 Instagram</div><div class="stat-value">{format_number(metrics.social.instagram_followers or 0)}</div><div class="stat-change-{ig_dir}">{arrow} {ig_text} ({period})</div></div>', unsafe_allow_html=True)
        us_text, us_dir = format_change(us_change)
        arrow = "↑" if us_dir == "positive" else "↓" if us_dir == "negative" else ""
        us_total = sum(p.value for p in streaming_data.get("us_streams", [])) if streaming_data.get("us_streams") else 0
        st.markdown(f'<div class="stat-card"><div class="stat-label">🎵 US Streams ({period})</div><div class="stat-value">{format_number(us_total)}</div><div class="stat-change-{us_dir}">{arrow} {us_text}</div></div>', unsafe_allow_html=True)

    # Deal Analysis Section
    st.markdown("---")
    with st.expander("Analyze Deal", expanded=False):
        # Get raw streaming data for deal analysis (full year)
        raw_streaming_full = data_cache.get_streaming_data(artist_id, "1Y")
        form_data = render_deal_form(artist_id, metrics.name, raw_streaming_full)

        if form_data:
            try:
                analyzer = get_analyzer()
                request = DealAnalysisRequest(
                    artist_id=artist_id,
                    artist_name=metrics.name,
                    weekly_audio_streams=form_data["weekly_audio"],
                    weekly_video_streams=form_data["weekly_video"],
                    catalog_track_count=form_data["catalog_tracks"],
                    extra_tracks=form_data["extra_tracks"],
                    genre=form_data["genre"],
                    deal_type=form_data["deal_type"],
                    deal_percent=form_data["deal_percent"],
                    market_shares=form_data["market_shares"],
                    advance_share=form_data["advance_share"],
                    marketing_recoupable=form_data["marketing_recoupable"],
                    weeks_post_peak=form_data["weeks_post_peak"],
                    use_track_level_decay=form_data.get("use_track_level_decay", True),
                )

                analysis_mode = form_data.get("analysis_mode", "Get Recommendation")
                decay_mode = "Track-Level" if form_data.get("use_track_level_decay", True) else "Aggregate"

                if analysis_mode == "Analyze Specific Deal":
                    # Viability analysis mode - user provides deal terms
                    with st.spinner("Analyzing deal viability..."):
                        viability_result = analyzer.analyze_viability(
                            request=request,
                            advance=form_data["input_advance"],
                            marketing=form_data["input_marketing"],
                            discount_rate=form_data.get("discount_rate", 0.10),
                        )
                        st.session_state.viability_result = viability_result
                        st.session_state.deal_result = None  # Clear recommendation result
                        # Debug info
                        from src.pricer.model import compute_label_share, DealType
                        deal_type_enum = {"distribution": DealType.DISTRIBUTION, "profit_split": DealType.PROFIT_SPLIT, "royalty": DealType.ROYALTY}.get(form_data["deal_type"])
                        label_share = compute_label_share(deal_type_enum, form_data["deal_percent"]) if deal_type_enum else "Unknown"
                        st.info(f"Viability Analysis | Deal Type: {form_data['deal_type']} | Label %: {form_data['deal_percent']*100:.0f}% | Decay: {decay_mode}")
                else:
                    # Recommendation mode - system recommends deal costs
                    with st.spinner("Analyzing deal..."):
                        result = analyzer.analyze(request)
                        st.session_state.deal_result = result
                        st.session_state.viability_result = None  # Clear viability result
                        # Debug info
                        from src.pricer.model import compute_label_share, DealType
                        deal_type_enum = {"distribution": DealType.DISTRIBUTION, "profit_split": DealType.PROFIT_SPLIT, "royalty": DealType.ROYALTY}.get(form_data["deal_type"])
                        label_share = compute_label_share(deal_type_enum, form_data["deal_percent"]) if deal_type_enum else "Unknown"
                        st.info(f"Recommendation | Deal Type: {form_data['deal_type']} | Label %: {form_data['deal_percent']*100:.0f}% | Decay: {decay_mode} | Effective Label Share: {label_share*100:.1f}%")
            except FileNotFoundError as e:
                st.error(f"Data files not found. Please ensure decay_model.xlsx and ppu_rates.xlsx are in data/deal_calc/")
                st.session_state.deal_result = None
                st.session_state.viability_result = None
            except Exception as e:
                import traceback
                st.error(f"Analysis error: {str(e)}")
                st.code(traceback.format_exc())
                st.session_state.deal_result = None

        # Render appropriate results based on analysis mode
        if st.session_state.get("viability_result"):
            render_viability_results(st.session_state.viability_result)
        elif st.session_state.get("deal_result"):
            render_deal_results(st.session_state.deal_result)

    st.markdown("---")

    # Compare Artists Section
    st.markdown('<div class="section-header">Compare Artists</div>', unsafe_allow_html=True)

    # Initialize compare_artists list in session state if not present
    if "compare_artists" not in st.session_state:
        st.session_state.compare_artists = []

    # Search and add any artist
    with st.expander("➕ Add Artist to Compare", expanded=False):
        search_query = st.text_input("Search for artist", placeholder="Enter artist name...", key="compare_search")
        if search_query and len(search_query) >= 2:
            with st.spinner("Searching..."):
                search_results = snowflake_client.search_artists(search_query)
            if search_results:
                for result in search_results[:5]:
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.write(f"**{result.get('ARTIST_NAME', 'Unknown')}**")
                    with col2:
                        sodatone_id = str(result.get('SODATONE_ID', ''))
                        artist_name = result.get('ARTIST_NAME', 'Unknown')
                        # Check if already in compare list
                        already_added = any(a.get("sodatone_id") == sodatone_id for a in st.session_state.compare_artists)
                        if sodatone_id and not already_added:
                            if st.button("Add", key=f"add_cmp_{sodatone_id}"):
                                st.session_state.compare_artists.append({
                                    "name": artist_name,
                                    "sodatone_id": sodatone_id,
                                })
                                refresh_artist_data(sodatone_id)
                                st.rerun()
                        elif already_added:
                            st.write("✓")
            else:
                st.caption("No artists found")

    # Find Similar Artists (Spotify suggestions)
    spotify_id = st.session_state.get("selected_spotify_id")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Find Similar Artists", use_container_width=True, key="find_similar"):
            if spotify_id:
                with st.spinner("Finding..."):
                    similar = get_similar_artists_cached(spotify_id, metrics.name)
                    st.session_state.similar_artists = similar
    with col2:
        if st.session_state.compare_artists and st.button("🗑️ Clear All", use_container_width=True, key="clear_compare"):
            st.session_state.compare_artists = []
            st.session_state.pop("compare_data", None)
            st.session_state.pop("similar_artists", None)
            st.rerun()

    # Show manually added artists
    if st.session_state.compare_artists:
        st.markdown("**Added Artists:**")
        for i, artist in enumerate(st.session_state.compare_artists):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f'<div class="compare-card"><div class="compare-name">{artist["name"]}</div></div>', unsafe_allow_html=True)
            with col2:
                if st.button("✕", key=f"remove_cmp_{i}"):
                    st.session_state.compare_artists.pop(i)
                    st.rerun()

    # Show Spotify similar artists suggestions
    if "similar_artists" in st.session_state and st.session_state.similar_artists:
        st.markdown("**Spotify Suggestions:**")
        selected_similar = []
        for i, s in enumerate(st.session_state.similar_artists[:8]):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f'<div class="compare-card"><div class="compare-name">{s.name}</div></div>', unsafe_allow_html=True)
            with col2:
                if st.checkbox("", key=f"cmp_{i}"):
                    selected_similar.append(s)

        if selected_similar and st.button(f"Add {len(selected_similar)} Selected", use_container_width=True, key="add_similar"):
            with st.spinner("Loading..."):
                mapping = lookup_sodatone_ids_cached(tuple(a.spotify_id for a in selected_similar if a.spotify_id))
                if mapping:
                    for s in selected_similar:
                        sid = mapping.get(s.spotify_id)
                        if sid:
                            # Check if already in compare list
                            already_added = any(a.get("sodatone_id") == sid for a in st.session_state.compare_artists)
                            if not already_added:
                                st.session_state.compare_artists.append({
                                    "name": s.name,
                                    "sodatone_id": sid,
                                })
                                refresh_artist_data(sid)
                    st.rerun()

    # Compare button - appears when artists are added
    if st.session_state.compare_artists:
        if st.button(f"📊 Compare {len(st.session_state.compare_artists)} Artists", use_container_width=True, key="do_compare"):
            compare_data = {"artists": {}}
            for artist in st.session_state.compare_artists:
                compare_data["artists"][artist["name"]] = {"sodatone_id": artist["sodatone_id"]}
            st.session_state.compare_data = compare_data
            st.rerun()

    if "compare_data" in st.session_state and st.session_state.compare_data:
        st.markdown('<div class="section-header">Comparison Charts</div>', unsafe_allow_html=True)
        compare = st.session_state.compare_data

        if st.session_state.view_mode == "streams":
            # Collect all streaming data first to find common reference date
            all_us_data = [streaming_data.get("us_streams", [])]
            all_global_data = [streaming_data.get("global_streams", [])]
            compare_streaming_raw = {}
            for name, data in compare["artists"].items():
                raw = data_cache.get_streaming_data(data["sodatone_id"], "1Y")
                compare_streaming_raw[name] = raw
                trimmed_us = trim_recent_streaming_data(raw.get("us_streams", []), 2)
                trimmed_global = trim_recent_streaming_data(raw.get("global_streams", []), 2)
                all_us_data.append(trimmed_us)
                all_global_data.append(trimmed_global)

            # Find common max date across all datasets
            all_dates = []
            for data_list in all_us_data + all_global_data:
                if data_list:
                    all_dates.extend([p.date for p in data_list])
            stream_ref_end = max(all_dates) if all_dates else date.today() - timedelta(days=2)

            # US Streams Comparison
            st.markdown('<div class="chart-title">US Streams (Daily) Comparison</div>', unsafe_allow_html=True)
            us_datasets = {metrics.name: pad_data_for_period(streaming_data.get("us_streams", []), period, stream_ref_end)}
            for name, raw in compare_streaming_raw.items():
                trimmed = trim_recent_streaming_data(raw.get("us_streams", []), 2)
                us_datasets[name] = pad_data_for_period(trimmed, period, stream_ref_end)
            st.plotly_chart(create_comparison_chart(us_datasets, height=300), use_container_width=True, config={'displayModeBar': False})

            # Global Streams Comparison
            st.markdown('<div class="chart-title">Global Streams (Daily) Comparison</div>', unsafe_allow_html=True)
            global_datasets = {metrics.name: pad_data_for_period(streaming_data.get("global_streams", []), period, stream_ref_end)}
            for name, raw in compare_streaming_raw.items():
                trimmed = trim_recent_streaming_data(raw.get("global_streams", []), 2)
                global_datasets[name] = pad_data_for_period(trimmed, period, stream_ref_end)
            st.plotly_chart(create_comparison_chart(global_datasets, height=300), use_container_width=True, config={'displayModeBar': False})
        else:
            for platform, label in [("spotify", "Spotify Followers"), ("instagram", "Instagram Followers"), ("tiktok", "TikTok Followers")]:
                # Collect all data for this platform to find common reference date
                all_platform_data = [raw_social.get(platform, [])]
                compare_social_raw = {}
                for name, data in compare["artists"].items():
                    raw = data_cache.get_social_data(data["sodatone_id"], "1Y")
                    compare_social_raw[name] = raw
                    all_platform_data.append(raw.get(platform, []))

                # Find common max date across all datasets for this platform
                all_dates = []
                for data_list in all_platform_data:
                    if data_list:
                        all_dates.extend([p.date for p in data_list])
                social_ref_end = max(all_dates) if all_dates else date.today()

                # Build datasets with common reference date
                datasets = {metrics.name: pad_data_for_period(raw_social.get(platform, []), period, social_ref_end)}
                for name, raw in compare_social_raw.items():
                    datasets[name] = pad_data_for_period(raw.get(platform, []), period, social_ref_end)

                st.markdown(f'<div class="chart-title">{label} Comparison</div>', unsafe_allow_html=True)
                st.plotly_chart(create_comparison_chart(datasets, height=250), use_container_width=True, config={'displayModeBar': False})


def create_deal_chart(result: DealAnalysisResult, height=350):
    """Create a 10-year cash flow bar chart for deal analysis."""
    years = result.cash_flow.years
    gross = result.cash_flow.gross_revenue
    label_share = result.cash_flow.label_share
    artist_pay = result.cash_flow.artist_pay

    fig = go.Figure()

    # Gross revenue bars
    fig.add_trace(go.Bar(
        name='Gross Revenue',
        x=[f'Y{y}' for y in years],
        y=gross,
        marker_color='#3a3a3c',
        hovertemplate='Gross: $%{y:,.0f}<extra></extra>'
    ))

    # Label share bars
    fig.add_trace(go.Bar(
        name='Label Share',
        x=[f'Y{y}' for y in years],
        y=label_share,
        marker_color='#007aff',
        hovertemplate='Label: $%{y:,.0f}<extra></extra>'
    ))

    # Artist pay bars
    fig.add_trace(go.Bar(
        name='Artist Pay',
        x=[f'Y{y}' for y in years],
        y=artist_pay,
        marker_color='#34c759',
        hovertemplate='Artist: $%{y:,.0f}<extra></extra>'
    ))

    fig.update_layout(
        barmode='group',
        height=height,
        margin=dict(l=0, r=0, t=30, b=30),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(color='#ffffff', size=11)
        ),
        xaxis=dict(
            showgrid=False,
            showline=False,
            tickfont=dict(color='#8e8e93', size=10)
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor='rgba(142,142,147,0.2)',
            showline=False,
            tickfont=dict(color='#8e8e93', size=10),
            tickprefix='$',
            tickformat=',.0f'
        ),
        hovermode='x unified',
        hoverlabel=dict(bgcolor='#1c1c1e', font_size=12, font_color='#ffffff')
    )

    return fig


@st.cache_data(ttl=600, show_spinner=False)
def get_catalog_track_count_cached(artist_id: str) -> int:
    """Fetch catalog track count from Snowflake (cached)."""
    try:
        return snowflake_client.get_catalog_track_count(artist_id)
    except:
        return 0


# Available markets for deal analysis (common markets with PPU data)
AVAILABLE_MARKETS = [
    "USA", "UK", "GERMANY", "FRANCE", "CANADA", "AUSTRALIA", "JAPAN",
    "BRAZIL", "MEXICO", "SPAIN", "ITALY", "NETHERLANDS", "SWEDEN",
    "KOREA", "INDIA", "ARGENTINA", "CHILE", "COLOMBIA", "INDONESIA",
    "PHILIPPINES", "TAIWAN", "THAILAND", "TURKEY", "POLAND", "BELGIUM"
]


def render_deal_form(artist_id: str, artist_name: str, streaming_data: dict):
    """Render the deal analysis input form."""
    st.markdown('<div class="section-header">Deal Analysis</div>', unsafe_allow_html=True)

    # Get weekly streams from the most recent data
    us_streams = streaming_data.get("us_streams", [])
    us_video = streaming_data.get("us_video_streams", [])

    # Calculate weekly averages from last 7 days
    weekly_audio = sum(p.value for p in us_streams[-7:]) if us_streams else 0
    weekly_video = sum(p.value for p in us_video[-7:]) if us_video else 0

    # Auto-fetch catalog track count
    catalog_tracks_auto = get_catalog_track_count_cached(artist_id)

    # Analysis mode selector (outside form for dynamic updates)
    analysis_mode = st.radio(
        "Analysis Mode",
        options=["Get Recommendation", "Analyze Specific Deal"],
        index=0,
        horizontal=True,
        help="Recommendation: Get suggested deal costs. Analyze: Input your deal terms to see viability."
    )

    with st.form("deal_form"):
        col1, col2 = st.columns(2)

        with col1:
            genre = st.selectbox(
                "Genre",
                options=AVAILABLE_GENRES,
                index=0,
                help="Select the genre for decay curve"
            )
            weeks_post_peak = st.number_input(
                "Weeks Post-Peak",
                min_value=0,
                max_value=520,
                value=0,
                help="Weeks since peak - accounts for decay already happened"
            )
            deal_type = st.selectbox(
                "Deal Type",
                options=["distribution", "profit_split", "royalty"],
                index=0,
                format_func=lambda x: x.replace("_", " ").title()
            )
            deal_percent = st.number_input(
                "Label % (Deal Share)",
                min_value=0,
                max_value=100,
                value=25,
                help="Label's share of gross revenue"
            ) / 100.0

        with col2:
            # Show auto-detected track count with option to override
            catalog_tracks = st.number_input(
                "Catalog Track Count",
                min_value=1,
                max_value=5000,
                value=max(catalog_tracks_auto, 1),
                help=f"Auto-detected: {catalog_tracks_auto} tracks"
            )
            extra_tracks = st.number_input(
                "New Songs Owed",
                min_value=0,
                max_value=100,
                value=0,
                help="Number of new tracks owed in the deal"
            )
            marketing_recoupable = st.checkbox(
                "Marketing Recoupable",
                value=False,
                help="Whether marketing costs are recoupable"
            )
            discount_rate = st.number_input(
                "Discount Rate %",
                min_value=5,
                max_value=25,
                value=10,
                help="Discount rate for NPV calculations"
            ) / 100.0

        # Conditional inputs based on analysis mode
        if analysis_mode == "Analyze Specific Deal":
            st.markdown("**Your Deal Terms**")
            col_adv, col_mkt = st.columns(2)
            with col_adv:
                input_advance = st.number_input(
                    "Advance Amount ($)",
                    min_value=0,
                    max_value=100000000,
                    value=100000,
                    step=10000,
                    help="Artist advance amount"
                )
            with col_mkt:
                input_marketing = st.number_input(
                    "Marketing Costs ($)",
                    min_value=0,
                    max_value=50000000,
                    value=50000,
                    step=5000,
                    help="Marketing/recording costs"
                )
            advance_share = 0.70  # Default, not used in this mode
        else:
            # Recommendation mode - use advance share percentage
            advance_share = st.number_input(
                "Advance % of Total Cost",
                min_value=0,
                max_value=100,
                value=70,
                help="Portion of total cost as advance"
            ) / 100.0
            input_advance = 0
            input_marketing = 0

        # Track-level decay option
        st.markdown("**Decay Mode**")
        use_track_level_decay = st.checkbox(
            "Use Track-Level Decay",
            value=True,
            help="Decay each track individually based on release date (recommended). If disabled, uses aggregate decay."
        )
        if use_track_level_decay:
            st.caption(f"Track data will be fetched from Snowflake. Each track decays based on its release date.")
        else:
            st.caption(f"All {catalog_tracks} tracks will decay uniformly from weeks post-peak.")

        st.markdown("**Market Shares** (select up to 5 markets)")

        # Market selection - 5 rows for 5 markets
        market_shares = {}
        total_share = 0

        for i in range(5):
            col_market, col_pct = st.columns([3, 1])
            with col_market:
                # Default selections for first 3 markets
                default_idx = 0
                if i == 0:
                    default_idx = AVAILABLE_MARKETS.index("USA") if "USA" in AVAILABLE_MARKETS else 0
                elif i == 1:
                    default_idx = AVAILABLE_MARKETS.index("UK") if "UK" in AVAILABLE_MARKETS else 1
                elif i == 2:
                    default_idx = AVAILABLE_MARKETS.index("GERMANY") if "GERMANY" in AVAILABLE_MARKETS else 2

                market = st.selectbox(
                    f"Market {i+1}",
                    options=["(None)"] + AVAILABLE_MARKETS,
                    index=default_idx + 1 if i < 3 else 0,
                    key=f"market_{i}",
                    label_visibility="collapsed"
                )
            with col_pct:
                # Default percentages
                default_pct = 0
                if i == 0:
                    default_pct = 40
                elif i == 1:
                    default_pct = 15
                elif i == 2:
                    default_pct = 10

                pct = st.number_input(
                    f"% {i+1}",
                    min_value=0,
                    max_value=100,
                    value=default_pct,
                    step=5,
                    key=f"pct_{i}",
                    label_visibility="collapsed"
                )

            if market != "(None)" and pct > 0:
                market_shares[market] = pct / 100.0
                total_share += pct

        row_share = 100 - total_share
        st.markdown(f"**Rest of World:** {row_share}%")

        st.markdown(f"**Detected Streams:** Audio: {format_number(weekly_audio)}/wk | Video: {format_number(weekly_video)}/wk")

        button_text = "Get Recommendation" if analysis_mode == "Get Recommendation" else "Analyze Deal Viability"
        submitted = st.form_submit_button(button_text, use_container_width=True)

        if submitted:
            if total_share > 100:
                st.error("Market shares cannot exceed 100%")
                return None
            return {
                "analysis_mode": analysis_mode,
                "genre": genre,
                "weeks_post_peak": weeks_post_peak,
                "deal_type": deal_type,
                "deal_percent": deal_percent,
                "catalog_tracks": catalog_tracks,
                "extra_tracks": extra_tracks,
                "advance_share": advance_share,
                "marketing_recoupable": marketing_recoupable,
                "market_shares": market_shares,
                "weekly_audio": weekly_audio,
                "weekly_video": weekly_video,
                "use_track_level_decay": use_track_level_decay,
                "discount_rate": discount_rate,
                # Viability mode specific
                "input_advance": input_advance,
                "input_marketing": input_marketing,
            }

    return None


def render_deal_results(result: DealAnalysisResult):
    """Render the deal analysis results."""
    st.markdown('<div class="section-header">Deal Recommendations</div>', unsafe_allow_html=True)

    # Two recommendation cards side by side
    col1, col2 = st.columns(2)

    # 18-Month Payback Target
    with col1:
        st.markdown("**18-Month Payback Target**")
        irr_text = f"{result.pricing.payback_implied_irr*100:.1f}%" if result.pricing.payback_implied_irr else "N/A"
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Max Total Cost</div>
            <div class="stat-value">${format_number(result.pricing.payback_max_cost)}</div>
            <div class="stat-change-neutral">Advance: ${format_number(result.pricing.payback_advance)}</div>
            <div class="stat-change-neutral">Marketing: ${format_number(result.pricing.payback_marketing)}</div>
            <div class="stat-change-neutral">Implied IRR: {irr_text}</div>
        </div>''', unsafe_allow_html=True)

    # 15% IRR Target
    with col2:
        st.markdown("**15% IRR Target**")
        marketing_15 = result.pricing.irr_15_max_cost - result.pricing.irr_15_advance
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Max Total Cost</div>
            <div class="stat-value">${format_number(result.pricing.irr_15_max_cost)}</div>
            <div class="stat-change-neutral">Advance: ${format_number(result.pricing.irr_15_advance)}</div>
            <div class="stat-change-neutral">Marketing: ${format_number(marketing_15)}</div>
        </div>''', unsafe_allow_html=True)

    # Cash flow chart
    st.markdown('<div class="section-header">10-Year Cash Flow Projection</div>', unsafe_allow_html=True)
    st.plotly_chart(create_deal_chart(result), use_container_width=True, config={'displayModeBar': False})

    # Label metrics
    st.markdown('<div class="section-header">Label Metrics (at 15% IRR Cost)</div>', unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Label NPV</div>
            <div class="stat-value">${format_number(result.label_metrics.label_npv)}</div>
        </div>''', unsafe_allow_html=True)
    with col2:
        irr_text = f"{result.label_metrics.label_irr*100:.1f}%" if result.label_metrics.label_irr else "N/A"
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Label IRR</div>
            <div class="stat-value">{irr_text}</div>
        </div>''', unsafe_allow_html=True)
    with col3:
        moic_text = f"{result.label_metrics.label_moic:.2f}x" if result.label_metrics.label_moic else "N/A"
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Label MOIC</div>
            <div class="stat-value">{moic_text}</div>
        </div>''', unsafe_allow_html=True)
    with col4:
        payback_text = f"Year {result.label_metrics.label_payback_year}" if result.label_metrics.label_payback_year else "N/A"
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Payback Year</div>
            <div class="stat-value">{payback_text}</div>
        </div>''', unsafe_allow_html=True)

    # Save button
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("Save Analysis", key="save_deal", use_container_width=True):
            analysis_id = save_deal_analysis(result)
            st.success(f"Saved! ID: {analysis_id}")


def render_viability_results(result: dict):
    """Render the deal viability analysis results."""
    st.markdown('<div class="section-header">Deal Viability Analysis</div>', unsafe_allow_html=True)

    # Deal Summary
    st.markdown("**Deal Terms**")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Total Investment</div>
            <div class="stat-value">${format_number(result["total_investment"])}</div>
            <div class="stat-change-neutral">Advance: ${format_number(result["advance"])}</div>
        </div>''', unsafe_allow_html=True)
    with col2:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Marketing Costs</div>
            <div class="stat-value">${format_number(result["marketing"])}</div>
        </div>''', unsafe_allow_html=True)
    with col3:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Year 1 Revenue</div>
            <div class="stat-value">${format_number(result["year1_revenue"])}</div>
        </div>''', unsafe_allow_html=True)

    # Label Metrics
    st.markdown("**Label Profitability**")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        npv = result["label_metrics"]["label_npv"]
        npv_color = "positive" if npv > 0 else "negative"
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Label NPV</div>
            <div class="stat-value social-{npv_color}">${format_number(npv)}</div>
        </div>''', unsafe_allow_html=True)
    with col2:
        irr = result["label_metrics"].get("label_irr")
        irr_text = f"{irr*100:.1f}%" if irr else "N/A"
        irr_color = "positive" if irr and irr > 0.10 else "negative" if irr else "neutral"
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Label IRR</div>
            <div class="stat-value social-{irr_color}">{irr_text}</div>
        </div>''', unsafe_allow_html=True)
    with col3:
        moic = result["label_metrics"].get("label_moic")
        moic_text = f"{moic:.2f}x" if moic else "N/A"
        moic_color = "positive" if moic and moic > 1.0 else "negative" if moic else "neutral"
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Label MOIC</div>
            <div class="stat-value social-{moic_color}">{moic_text}</div>
        </div>''', unsafe_allow_html=True)
    with col4:
        payback = result["label_metrics"].get("label_payback_year")
        payback_text = f"Year {payback}" if payback else "Not Achieved"
        payback_color = "positive" if payback and payback <= 3 else "neutral" if payback else "negative"
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Payback Year</div>
            <div class="stat-value social-{payback_color}">{payback_text}</div>
        </div>''', unsafe_allow_html=True)

    # Artist Metrics
    st.markdown("**Artist Returns**")
    col1, col2, col3 = st.columns(3)
    with col1:
        artist_npv = result["artist_metrics"].get("npv_incl_advance", 0)
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Artist NPV (w/ Advance)</div>
            <div class="stat-value">${format_number(artist_npv)}</div>
        </div>''', unsafe_allow_html=True)
    with col2:
        total_cash = result["artist_metrics"].get("total_cash_incl_advance", 0)
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Total Cash to Artist</div>
            <div class="stat-value">${format_number(total_cash)}</div>
        </div>''', unsafe_allow_html=True)
    with col3:
        recoup_year = result["artist_metrics"].get("breakeven_year")
        recoup_text = f"Year {recoup_year}" if recoup_year else "Not Recouped"
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Recoupment Year</div>
            <div class="stat-value">{recoup_text}</div>
        </div>''', unsafe_allow_html=True)

    # Viability Assessment
    st.markdown("**Viability Assessment**")
    irr = result["label_metrics"].get("label_irr")
    moic = result["label_metrics"].get("label_moic")
    npv = result["label_metrics"]["label_npv"]

    if irr and irr >= 0.15 and moic and moic >= 1.5 and npv > 0:
        st.success("**Strong Deal** - IRR ≥15%, MOIC ≥1.5x, Positive NPV")
    elif irr and irr >= 0.10 and moic and moic >= 1.2 and npv > 0:
        st.info("**Acceptable Deal** - IRR ≥10%, MOIC ≥1.2x, Positive NPV")
    elif npv > 0:
        st.warning("**Marginal Deal** - Positive NPV but low returns")
    else:
        st.error("**Poor Deal** - Negative NPV, consider renegotiating terms")

    # Cash Flow Chart
    st.markdown('<div class="section-header">10-Year Cash Flow Projection</div>', unsafe_allow_html=True)
    cf = result["cash_flow"]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name='Gross Revenue',
        x=[f'Y{y}' for y in cf["years"]],
        y=cf["gross_revenue"],
        marker_color='#3a3a3c',
        hovertemplate='Gross: $%{y:,.0f}<extra></extra>'
    ))
    fig.add_trace(go.Bar(
        name='Label Share',
        x=[f'Y{y}' for y in cf["years"]],
        y=cf["label_share"],
        marker_color='#007aff',
        hovertemplate='Label: $%{y:,.0f}<extra></extra>'
    ))
    fig.add_trace(go.Bar(
        name='Artist Pay',
        x=[f'Y{y}' for y in cf["years"]],
        y=cf["artist_pay"],
        marker_color='#34c759',
        hovertemplate='Artist: $%{y:,.0f}<extra></extra>'
    ))

    fig.update_layout(
        barmode='group',
        height=350,
        margin=dict(l=0, r=0, t=30, b=30),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(color='#ffffff', size=11)),
        xaxis=dict(showgrid=False, showline=False, tickfont=dict(color='#8e8e93', size=10)),
        yaxis=dict(showgrid=True, gridcolor='rgba(142,142,147,0.2)', showline=False, tickfont=dict(color='#8e8e93', size=10), tickprefix='$', tickformat=',.0f'),
        hovermode='x unified',
        hoverlabel=dict(bgcolor='#1c1c1e', font_size=12, font_color='#ffffff')
    )

    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    # Cash Flow Table (collapsible)
    with st.expander("View Cash Flow Details"):
        df = pd.DataFrame({
            "Year": cf["years"],
            "Gross Revenue": [f"${v:,.0f}" for v in cf["gross_revenue"]],
            "Label Share": [f"${v:,.0f}" for v in cf["label_share"]],
            "Artist Pay": [f"${v:,.0f}" for v in cf["artist_pay"]],
            "Decay Multiplier": [f"{m:.2%}" for m in cf["multipliers"]],
        })
        st.dataframe(df, use_container_width=True, hide_index=True)


def render_deals_page():
    """Render the deals listing page."""
    st.markdown('<div class="page-title">Deal Analyses</div>', unsafe_allow_html=True)

    analyses = get_analyses_summary()
    st.markdown(f'<div class="page-subtitle">{len(analyses)} saved analyses</div>', unsafe_allow_html=True)

    if st.button("← Back to Artists", key="back_from_deals"):
        st.session_state.page = "summary"
        st.rerun()

    st.markdown("---")

    if not analyses:
        st.info("No deal analyses saved yet. Go to an artist detail page to create one.")
        return

    # Group by artist
    artists = {}
    for a in analyses:
        name = a.get("artist_name", "Unknown")
        if name not in artists:
            artists[name] = []
        artists[name].append(a)

    for artist_name, artist_analyses in artists.items():
        st.markdown(f'<div class="section-header">{artist_name}</div>', unsafe_allow_html=True)

        for a in artist_analyses:
            analysis_id = a.get("id", "")
            deal_type = (a.get("deal_type") or "").replace("_", " ").title()
            deal_pct = (a.get("deal_percent") or 0) * 100
            genre = a.get("genre", "")
            irr_15_cost = a.get("irr_15_max_cost", 0)
            label_irr = a.get("label_irr")
            label_moic = a.get("label_moic")
            saved_at = a.get("saved_at", "")[:10]

            irr_text = f"{label_irr*100:.1f}%" if label_irr else "N/A"
            moic_text = f"{label_moic:.2f}x" if label_moic else "N/A"

            col1, col2 = st.columns([6, 1])
            with col1:
                st.markdown(f'''<div class="stat-card">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div style="font-size: 14px; font-weight: 600; color: #ffffff;">{deal_type} ({deal_pct:.0f}%) - {genre}</div>
                            <div style="font-size: 12px; color: #8e8e93; margin-top: 4px;">
                                15% IRR Cost: ${format_number(irr_15_cost)} | IRR: {irr_text} | MOIC: {moic_text}
                            </div>
                        </div>
                        <div style="font-size: 11px; color: #8e8e93;">{saved_at}</div>
                    </div>
                </div>''', unsafe_allow_html=True)
            with col2:
                if st.button("Delete", key=f"del_deal_{analysis_id}"):
                    delete_analysis(analysis_id)
                    st.rerun()


def render_sound_detail_page():
    """Render the TikTok sound detail page."""
    sound_id = st.session_state.get("selected_sound")
    if not sound_id:
        st.session_state.page = "summary"
        st.rerun()
        return

    if st.button("← Back to Home", key="back_from_sound_detail"):
        st.session_state.page = "summary"
        st.rerun()

    # Get sound data
    tracked_sounds = load_tracked_sounds()
    sound_info = next((s for s in tracked_sounds if s.sound_id == sound_id), None)

    try:
        sound_data = chartex_client.get_sound_data(sound_id, lookback_days=90)
    except Exception as e:
        st.error(f"Failed to load sound data: {e}")
        return

    # Header
    sound_name = sound_info.name if sound_info else sound_data.name
    st.markdown(f'<div class="page-title">{sound_name}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-subtitle">Sound ID: {sound_id}</div>', unsafe_allow_html=True)

    # Key metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Total Views</div>
            <div class="stat-value">{format_number(sound_data.total_views)}</div>
        </div>''', unsafe_allow_html=True)
    with col2:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">Total Creates</div>
            <div class="stat-value">{format_number(sound_data.total_creates)}</div>
        </div>''', unsafe_allow_html=True)
    with col3:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">7-Day Views</div>
            <div class="stat-value stat-change-positive">+{format_number(sound_data.views_7d)}</div>
        </div>''', unsafe_allow_html=True)
    with col4:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-label">7-Day Creates</div>
            <div class="stat-value stat-change-positive">+{format_number(sound_data.creates_7d)}</div>
        </div>''', unsafe_allow_html=True)

    # Time period selector
    periods = ["1W", "1M", "3M"]
    if "sound_period" not in st.session_state:
        st.session_state.sound_period = "1M"

    selected_period = st.radio(
        "Period",
        periods,
        index=periods.index(st.session_state.sound_period),
        horizontal=True,
        label_visibility="collapsed",
        key="sound_period_radio"
    )
    if selected_period != st.session_state.sound_period:
        st.session_state.sound_period = selected_period
        st.rerun()

    # Filter data by period
    period_days = {"1W": 7, "1M": 30, "3M": 90}.get(selected_period, 30)
    cutoff_date = date.today() - timedelta(days=period_days)

    views_filtered = [p for p in sound_data.views_history if p.date >= cutoff_date]
    creates_filtered = [p for p in sound_data.creates_history if p.date >= cutoff_date]

    # Views chart
    st.markdown('<div class="section-header">Daily Views</div>', unsafe_allow_html=True)
    if views_filtered:
        st.plotly_chart(
            create_chart(views_filtered, height=250, color="#ff3b30"),
            use_container_width=True,
            config={'displayModeBar': False}
        )
    else:
        st.info("No view data available for this period. Make sure the sound is being tracked in Chartex.")

    # Creates chart
    st.markdown('<div class="section-header">Daily Creates</div>', unsafe_allow_html=True)
    if creates_filtered:
        st.plotly_chart(
            create_chart(creates_filtered, height=250, color="#007aff"),
            use_container_width=True,
            config={'displayModeBar': False}
        )
    else:
        st.info("No creates data available for this period.")

    # TikTok link
    st.markdown("---")
    tiktok_url = sound_info.tiktok_url if sound_info else f"https://www.tiktok.com/music/original-sound-{sound_id}"
    st.markdown(f"[Open in TikTok]({tiktok_url})")


def main():
    if "page" not in st.session_state:
        st.session_state.page = "summary"
    if "selected_artist" not in st.session_state:
        st.session_state.selected_artist = None
    if "deal_result" not in st.session_state:
        st.session_state.deal_result = None

    if st.session_state.page == "detail" and st.session_state.selected_artist:
        render_detail_page()
    elif st.session_state.page == "deals":
        render_deals_page()
    elif st.session_state.page == "sound_detail":
        render_sound_detail_page()
    else:
        render_summary_page()


if __name__ == "__main__":
    main()

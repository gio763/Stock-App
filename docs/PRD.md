# Artist Stock App - Product Requirements Document

**Version:** 1.0.2
**Last Updated:** February 2026
**Author:** Gio

---

## 1. Overview

### 1.1 Product Summary
The Artist Stock App is an internal tool for tracking and analyzing music artist performance metrics, styled after the Apple Stocks app. It aggregates data from multiple sources (Snowflake/Sodatone, Spotify, TikTok) to provide a unified view of artist growth and engagement.

### 1.2 Target Users
- A&R professionals
- Music industry analysts
- Artist management teams

### 1.3 Key Value Proposition
- **Unified Dashboard**: View streaming, social, and TikTok metrics in one place
- **Trend Analysis**: Track artist growth over time with interactive charts
- **Deal Analysis**: Model potential artist deals with decay-adjusted projections
- **TikTok Sound Tracking**: Monitor viral sound performance and creates

---

## 2. Features

### 2.1 Artist Tracking

| Feature | Description | Status |
|---------|-------------|--------|
| Search & Add Artists | Search by name via Spotify API, lookup in Sodatone database | ✅ Complete |
| Artist Cards | Display key metrics (streams, followers, changes) in card format | ✅ Complete |
| Artist Detail View | Full metrics dashboard with time-series charts | ✅ Complete |
| Similar Artists | Show Spotify-related artists with Sodatone data | ✅ Complete |
| Remove Artists | Delete from tracking list | ✅ Complete |

### 2.2 Metrics Displayed

**Streaming Metrics (from Snowflake/Sodatone)**
- Weekly US Audio Streams
- Weekly Global Audio Streams
- Daily US/Global Streams
- Week-over-Week Change (%)

**Social Metrics (from Snowflake/Sodatone)**
- Spotify Followers + Change
- Instagram Followers + Change
- TikTok Followers + Change
- TikTok Sound Creates + Change

### 2.3 Time-Series Charts

| Period | Days |
|--------|------|
| 1W | 7 |
| 1M | 30 |
| 3M | 90 |
| 6M | 180 |
| 1Y | 365 |
| 2Y | 730 |

Charts available for:
- US Streams
- Global Streams
- Spotify Followers
- Instagram Followers
- TikTok Followers

### 2.4 TikTok Sound Tracking

| Feature | Description | Data Source |
|---------|-------------|-------------|
| Add Sound by URL | Parse TikTok music URLs to extract sound ID | - |
| Total Creates | Number of videos using the sound | Chartex API |
| 7-Day Creates | Recent growth in video usage | Chartex API |
| 24-Hour Creates | Daily growth metric | Chartex API |
| Total Views | Aggregate views across videos | Apify (optional) |
| Sound Detail Page | Full metrics and history chart | - |
| Link to Artist | Associate sounds with tracked artists | - |

### 2.5 Deal Analysis

| Feature | Description |
|---------|-------------|
| Deal Calculator | Input deal terms (advance, royalty rate, term) |
| Decay Modeling | Project future streams using catalog age decay |
| Genre-Based Decay | Different decay rates per genre |
| Track-Level Analysis | Individual track projections based on peak dates |
| Recoupment Estimate | Calculate time/streams to recoup advance |
| Deal Comparison | Save and compare multiple deal scenarios |

---

## 3. Technical Architecture

### 3.1 Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | Streamlit |
| Styling | Custom CSS (Apple Stocks theme) |
| Charts | Plotly |
| Deployment | Render (Docker) |
| Database | Snowflake (read-only) |
| Local Storage | JSON files + Session State |

### 3.2 Data Sources

| Source | Purpose | Authentication |
|--------|---------|----------------|
| Snowflake (Sodatone) | Artist metrics, streaming data, social stats | JWT with RSA key |
| Spotify API | Artist search, similar artists | OAuth Client Credentials |
| Chartex API | TikTok sound creates data | App ID + Token |
| Apify | TikTok sound views (optional) | API Token |
| Microlink | TikTok sound metadata fallback | None (public API) |

### 3.3 Environment Variables

```
# Required
SNOWFLAKE_PRIVATE_KEY_B64=<base64-encoded RSA key>
APP_PASSWORD=<app access password>

# Spotify (for artist search)
SPOTIFY_CLIENT_ID=<spotify client id>
SPOTIFY_CLIENT_SECRET=<spotify client secret>

# TikTok Sound Tracking
CHARTEX_APP_ID=<chartex app id>
CHARTEX_APP_TOKEN=<chartex app token>

# Optional
APIFY_TOKEN=<apify token for views>
```

### 3.4 File Structure

```
Stock App/
├── app.py                 # Main Streamlit application
├── config/
│   └── settings.yaml      # Snowflake/Spotify configuration
├── src/
│   ├── config.py          # Settings loader
│   ├── models.py          # Data models (dataclasses)
│   ├── queries.py         # SQL queries for Snowflake
│   ├── snowflake_client.py # Snowflake API client
│   ├── spotify_client.py  # Spotify API client
│   ├── chartex_client.py  # Chartex API client
│   ├── apify_client.py    # Apify client for TikTok views
│   ├── tiktok_scraper.py  # TikTok data aggregation
│   ├── storage.py         # Artist persistence
│   ├── tiktok_storage.py  # TikTok sound persistence
│   ├── data_cache.py      # In-memory caching
│   ├── deal_analysis.py   # Deal modeling logic
│   └── deal_storage.py    # Deal persistence
├── data/                  # Local JSON storage (gitignored)
├── Dockerfile             # Container build
└── requirements.txt       # Python dependencies
```

---

## 4. Data Flow

### 4.1 Artist Addition Flow
```
User enters artist name
    → Spotify API search
    → Select artist from results
    → Lookup Sodatone ID in Snowflake
    → Add to tracked_artists.json
    → Fetch metrics from Snowflake
    → Fetch similar artists from Spotify
    → Cache recommendations
```

### 4.2 TikTok Sound Addition Flow
```
User enters TikTok URL
    → Extract sound ID from URL
    → Query Chartex API (creates data)
    → If not found: Playwright scrape
    → If views needed: Apify scrape
    → Fallback: Microlink (metadata only)
    → Add to tracked_tiktok_sounds.json
    → Save metrics snapshot
```

### 4.3 Metrics Refresh Flow
```
App loads / Refresh button clicked
    → Load tracked artist IDs
    → Batch query Snowflake for metrics
    → Cache in session state
    → Display in UI
```

---

## 5. Known Limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| Render ephemeral filesystem | Tracked artists/sounds reset on deploy | Session state backup persists during session |
| Chartex no view data | Only creates available from Chartex | Apify provides views (requires token, costs money) |
| Snowflake query latency | Slow initial load | Optimized to fetch only tracked artists |
| Password re-auth on version change | Users must re-login after deploys | Intentional for security |

---

## 6. Future Enhancements

### 6.1 Near-Term (Planned)
- [ ] Persistent storage via Snowflake table for tracked artists
- [ ] Email/Slack alerts for significant metric changes
- [ ] Export functionality (CSV/Excel)
- [ ] Bulk artist import

### 6.2 Long-Term (Potential)
- [ ] YouTube metrics integration
- [ ] Apple Music data
- [ ] Automated deal recommendations
- [ ] Multi-user support with role-based access
- [ ] Mobile-responsive redesign

---

## 7. API Reference

### 7.1 Chartex API
- **Endpoint**: `https://api.chartex.com/external/v1/tiktok-sounds`
- **Auth**: `X-APP-ID` and `X-APP-TOKEN` headers
- **Rate Limit**: Contact Chartex for limits
- **Response Fields**:
  - `tiktok_sound_id`
  - `tiktok_total_video_count` (creates)
  - `tiktok_last_7_days_video_count`
  - `tiktok_last_24_hours_video_count`
  - `tiktok_name_of_sound`
  - `tiktok_sound_creator_name`

### 7.2 Snowflake Tables Used
- Artist metrics summary
- Streaming time series
- Social follower time series
- Spotify-to-Sodatone ID mapping
- Track catalog with streams

---

## 8. Deployment

### 8.1 Render Configuration
- **Service Type**: Web Service
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
- **Docker**: Uses Dockerfile for Playwright support

### 8.2 Deploy Process
1. Push to `main` branch on GitHub
2. Render auto-deploys from GitHub
3. ~2-3 minute build time
4. Health check on `/`

---

## 9. Support & Contacts

| Role | Contact |
|------|---------|
| Product Owner | Gio |
| Chartex API Support | chartex.com |
| Snowflake/Sodatone | Internal data team |

---

*Document generated February 2026*

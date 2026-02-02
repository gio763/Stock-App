"""SQL queries for Stock App."""

# Simple/fast query for summary view - includes all needed fields with calculated percentages
ARTIST_SUMMARY_QUERY = """
WITH spotify_current AS (
    SELECT
        spotify_account_id,
        follower_count,
        date
    FROM sodatone.spotify_account_follower_count_interpolations
    WHERE date >= CURRENT_DATE - 1
    QUALIFY ROW_NUMBER() OVER (PARTITION BY spotify_account_id ORDER BY date DESC) = 1
),
spotify_week_ago AS (
    SELECT
        spotify_account_id,
        follower_count,
        date
    FROM sodatone.spotify_account_follower_count_interpolations
    WHERE date BETWEEN CURRENT_DATE - 8 AND CURRENT_DATE - 6
    QUALIFY ROW_NUMBER() OVER (PARTITION BY spotify_account_id ORDER BY date DESC) = 1
)
SELECT
    a.id AS SODATONE_ID,
    a.name AS ARTIST_NAME,
    a.cached_country AS LOCATION,
    la.us_this_period AS WEEKLY_US_STREAMS,
    la.global_this_period AS WEEKLY_GLOBAL_STREAMS,
    DIV0((la.us_this_period - la.us_last_period), NULLIF(la.us_last_period, 0)) AS US_WOW_CHANGE,
    DIV0((la.global_this_period - la.global_last_period), NULLIF(la.global_last_period, 0)) AS GLOBAL_WOW_CHANGE,
    COALESCE(sc.follower_count, sac.follower_count) AS SPOTIFY_FOLLOWERS,
    DIV0((sc.follower_count - sw.follower_count), NULLIF(sw.follower_count, 0)) AS SPOTIFY_CHANGE,
    iam.follower_count AS INSTAGRAM_FOLLOWERS,
    DIV0(iam.follower_count_7_day_delta, NULLIF(iam.follower_count - iam.follower_count_7_day_delta, 0)) AS INSTAGRAM_CHANGE,
    tum.follower_count AS TIKTOK_FOLLOWERS,
    DIV0(tum.follower_count_7_day_delta, NULLIF(tum.follower_count - tum.follower_count_7_day_delta, 0)) AS TIKTOK_CHANGE
FROM sodatone.artists a
LEFT JOIN sodatone.spotify_accounts sac ON sac.artist_id = a.id
LEFT JOIN spotify_current sc ON sc.spotify_account_id = sac.id
LEFT JOIN spotify_week_ago sw ON sw.spotify_account_id = sac.id
LEFT JOIN sodatone.luminate_accounts la ON la.spotify_account_id = sac.id
LEFT JOIN sodatone.tiktok_users tu ON tu.artist_id = a.id
LEFT JOIN sodatone.tiktok_user_growth_metrics tum ON tum.tiktok_user_id = tu.id
LEFT JOIN sodatone.instagram_accounts ia ON ia.artist_id = a.id
LEFT JOIN sodatone.instagram_account_growth_metrics iam ON iam.instagram_account_id = ia.id
WHERE a.id IN ({id_filter})
"""

# Search for artists by name
ARTIST_SEARCH_QUERY = """
SELECT DISTINCT
    a.id AS SODATONE_ID,
    a.name AS ARTIST_NAME,
    CONCAT('https://app.sodatone.com/artists/', a.id) AS ARTIST_URL,
    sac.spotify_id AS SPOTIFY_ID,
    a.cached_country AS LOCATION
FROM sodatone.artists a
LEFT JOIN sodatone.spotify_accounts sac ON sac.artist_id = a.id
WHERE LOWER(a.name) LIKE LOWER('%{search_term}%')
LIMIT 20
"""

# Get current metrics for tracked artists (simplified - matches Gregg Daily Update structure)
ARTIST_METRICS_QUERY = """
WITH artist_subset AS (
    SELECT * FROM sodatone.artists WHERE id IN ({id_filter})
),
spotify_current AS (
    SELECT
        spotify_account_id,
        follower_count,
        date
    FROM sodatone.spotify_account_follower_count_interpolations
    WHERE date >= CURRENT_DATE - 1
    QUALIFY ROW_NUMBER() OVER (PARTITION BY spotify_account_id ORDER BY date DESC) = 1
),
spotify_week_ago AS (
    SELECT
        spotify_account_id,
        follower_count,
        date
    FROM sodatone.spotify_account_follower_count_interpolations
    WHERE date BETWEEN CURRENT_DATE - 8 AND CURRENT_DATE - 6
    QUALIFY ROW_NUMBER() OVER (PARTITION BY spotify_account_id ORDER BY date DESC) = 1
),
main_luminate_data AS (
    SELECT DISTINCT
        spotify_accounts.id AS spotify_account_id,
        luminate_unified_song_spotify_tracks.unified_song_id
    FROM sodatone.luminate_unified_song_spotify_tracks
    INNER JOIN sodatone.spotify_tracks ON spotify_tracks.id = luminate_unified_song_spotify_tracks.spotify_track_id
    INNER JOIN sodatone.spotify_albums ON spotify_albums.id = spotify_tracks.spotify_album_id
    INNER JOIN sodatone.spotify_accounts ON spotify_accounts.id = spotify_tracks.primary_spotify_account_id
    INNER JOIN artist_subset ON artist_subset.id = spotify_accounts.artist_id
),
complete_daily_luminate_data AS (
    SELECT
        spotify_account_id,
        date,
        COALESCE(SUM(us_audio_stream_count), 0) AS us_audio_streams,
        COALESCE(SUM(global_audio_stream_count), 0) AS global_audio_streams
    FROM main_luminate_data
    INNER JOIN sodatone.LUMINATE_DAILY_SONG_METRICS_HISTORY history
        ON main_luminate_data.unified_song_id = history.unified_song_id
    GROUP BY spotify_account_id, date
),
complete_last_day_luminate_data AS (
    SELECT spotify_account_id, date, us_audio_streams, global_audio_streams
    FROM complete_daily_luminate_data
    WHERE date >= DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '3 day'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY spotify_account_id ORDER BY date DESC) = 1
),
complete_last_week_luminate_data AS (
    SELECT
        spotify_account_id,
        COALESCE(SUM(us_audio_streams), 0) AS us_audio_streams,
        COALESCE(SUM(global_audio_streams), 0) AS global_audio_streams
    FROM complete_daily_luminate_data
    WHERE date >= DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '9 days'
    GROUP BY 1
),
complete_last_last_week_luminate_data AS (
    SELECT
        spotify_account_id,
        COALESCE(SUM(us_audio_streams), 0) AS us_audio_streams,
        COALESCE(SUM(global_audio_streams), 0) AS global_audio_streams
    FROM complete_daily_luminate_data
    WHERE date BETWEEN DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '16 days'
        AND DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '9 days'
    GROUP BY 1
)
SELECT
    a.id AS SODATONE_ID,
    CONCAT('https://app.sodatone.com/artists/', a.id) AS ARTIST_URL,
    a.name AS ARTIST_NAME,
    a.cached_country AS LOCATION,
    st.name AS TOP_TRACK_NAME,
    sac.spotify_id AS SPOTIFY_ID,
    clwld.us_audio_streams AS WEEKLY_US_STREAMS,
    DIV0((clwld.us_audio_streams - cllwld.us_audio_streams), cllwld.us_audio_streams) AS US_WOW_CHANGE,
    cldld.us_audio_streams AS DAILY_US_STREAMS,
    clwld.global_audio_streams AS WEEKLY_GLOBAL_STREAMS,
    DIV0((clwld.global_audio_streams - cllwld.global_audio_streams), cllwld.global_audio_streams) AS GLOBAL_WOW_CHANGE,
    cldld.global_audio_streams AS DAILY_GLOBAL_STREAMS,
    COALESCE(sc.follower_count, sac.follower_count) AS SPOTIFY_FOLLOWERS,
    DIV0((sc.follower_count - sw.follower_count), NULLIF(sw.follower_count, 0)) AS SPOTIFY_CHANGE,
    iam.follower_count AS INSTAGRAM_FOLLOWERS,
    DIV0(iam.follower_count_7_day_delta, NULLIF(iam.follower_count - iam.follower_count_7_day_delta, 0)) AS INSTAGRAM_CHANGE,
    tum.follower_count AS TIKTOK_FOLLOWERS,
    DIV0(tum.follower_count_7_day_delta, NULLIF(tum.follower_count - tum.follower_count_7_day_delta, 0)) AS TIKTOK_CHANGE,
    tts.post_count AS TIKTOK_SOUND_CREATES,
    DIV0(ttsm.post_count_7_day_delta, NULLIF(tts.post_count - ttsm.post_count_7_day_delta, 0)) AS TIKTOK_SOUND_CHANGE
FROM artist_subset a
LEFT JOIN sodatone.spotify_accounts sac ON sac.artist_id = a.id
LEFT JOIN spotify_current sc ON sc.spotify_account_id = sac.id
LEFT JOIN spotify_week_ago sw ON sw.spotify_account_id = sac.id
LEFT JOIN sodatone.spotify_tracks st ON st.primary_spotify_account_id = sac.id
LEFT JOIN sodatone.spotify_albums sal ON sal.id = st.spotify_album_id
LEFT JOIN complete_last_day_luminate_data cldld ON cldld.spotify_account_id = sac.id
LEFT JOIN complete_last_week_luminate_data clwld ON clwld.spotify_account_id = sac.id
LEFT JOIN complete_last_last_week_luminate_data cllwld ON cllwld.spotify_account_id = sac.id
LEFT JOIN sodatone.tiktok_users tu ON tu.artist_id = a.id
LEFT JOIN sodatone.tiktok_user_growth_metrics tum ON tum.tiktok_user_id = tu.id
LEFT JOIN sodatone.instagram_accounts ia ON ia.artist_id = a.id
LEFT JOIN sodatone.instagram_account_growth_metrics iam ON iam.instagram_account_id = ia.id
LEFT JOIN (
    SELECT tts.*
    FROM sodatone.tiktok_sounds tts
    INNER JOIN sodatone.tiktok_sound_growth_metrics ttsm ON ttsm.tiktok_sound_id = tts.id
    QUALIFY ROW_NUMBER() OVER (PARTITION BY tts.id ORDER BY post_count_7_day_delta DESC NULLS LAST) = 1
) tts ON tts.spotify_track_id = st.id
LEFT JOIN sodatone.tiktok_sound_growth_metrics ttsm ON ttsm.tiktok_sound_id = tts.id
QUALIFY ROW_NUMBER() OVER (PARTITION BY a.id ORDER BY st.popularity DESC NULLS LAST) = 1
"""

# Time series query for streaming data - DAILY granularity
STREAMING_TIME_SERIES_QUERY = """
WITH artist_spotify AS (
    SELECT sac.id AS spotify_account_id
    FROM sodatone.artists a
    JOIN sodatone.spotify_accounts sac ON sac.artist_id = a.id
    WHERE a.id IN ({id_filter})
),
main_luminate_data AS (
    SELECT DISTINCT
        asp.spotify_account_id,
        lust.unified_song_id
    FROM artist_spotify asp
    JOIN sodatone.spotify_tracks st ON st.primary_spotify_account_id = asp.spotify_account_id
    JOIN sodatone.luminate_unified_song_spotify_tracks lust ON lust.spotify_track_id = st.id
)
SELECT
    history.date AS DATE,
    COALESCE(SUM(history.us_audio_stream_count), 0) AS US_STREAMS,
    COALESCE(SUM(history.global_audio_stream_count), 0) AS GLOBAL_STREAMS,
    COALESCE(SUM(history.us_video_stream_count), 0) AS US_VIDEO_STREAMS
FROM main_luminate_data mld
JOIN sodatone.LUMINATE_DAILY_SONG_METRICS_HISTORY history ON mld.unified_song_id = history.unified_song_id
WHERE history.date >= DATEADD('month', -{lookback_months}, CURRENT_DATE())
GROUP BY 1
ORDER BY 1
"""

# Time series for social followers - DAILY granularity
SOCIAL_TIME_SERIES_QUERY = """
SELECT
    interp.date AS DATE,
    'spotify' AS PLATFORM,
    interp.follower_count AS FOLLOWERS
FROM sodatone.spotify_account_follower_count_interpolations interp
JOIN sodatone.spotify_accounts sac ON sac.id = interp.spotify_account_id
WHERE sac.artist_id IN ({id_filter})
    AND interp.date >= DATEADD('month', -{lookback_months}, CURRENT_DATE())

UNION ALL

SELECT
    interp.date AS DATE,
    'instagram' AS PLATFORM,
    interp.follower_count AS FOLLOWERS
FROM sodatone.instagram_account_follower_count_interpolations interp
JOIN sodatone.instagram_accounts ia ON ia.id = interp.instagram_account_id
WHERE ia.artist_id IN ({id_filter})
    AND interp.date >= DATEADD('month', -{lookback_months}, CURRENT_DATE())

UNION ALL

SELECT
    interp.date AS DATE,
    'tiktok' AS PLATFORM,
    interp.follower_count AS FOLLOWERS
FROM sodatone.tiktok_user_follower_count_interpolations interp
JOIN sodatone.tiktok_users tu ON tu.id = interp.tiktok_user_id
WHERE tu.artist_id IN ({id_filter})
    AND interp.date >= DATEADD('month', -{lookback_months}, CURRENT_DATE())
ORDER BY 1, 2
"""

# Lookup Sodatone ID from Spotify ID
SPOTIFY_TO_SODATONE_QUERY = """
SELECT
    a.id AS SODATONE_ID,
    a.name AS ARTIST_NAME,
    sac.spotify_id AS SPOTIFY_ID
FROM sodatone.artists a
JOIN sodatone.spotify_accounts sac ON sac.artist_id = a.id
WHERE sac.spotify_id IN ({spotify_ids})
"""

# Get catalog track count for an artist
CATALOG_TRACK_COUNT_QUERY = """
SELECT
    COUNT(DISTINCT st.id) AS TRACK_COUNT
FROM sodatone.artists a
JOIN sodatone.spotify_accounts sac ON sac.artist_id = a.id
JOIN sodatone.spotify_tracks st ON st.primary_spotify_account_id = sac.id
WHERE a.id IN ({id_filter})
"""

# Get track-level catalog data with release dates and current weekly streams
# Used for individual track decay calculations in deal analysis
TRACK_CATALOG_WITH_STREAMS_QUERY = """
WITH track_weekly_streams AS (
    SELECT
        st.id AS track_id,
        COALESCE(SUM(h.us_audio_stream_count), 0) AS weekly_us_audio_streams,
        COALESCE(SUM(h.global_audio_stream_count), 0) AS weekly_global_audio_streams,
        COALESCE(SUM(h.us_video_stream_count), 0) AS weekly_us_video_streams
    FROM sodatone.spotify_tracks st
    INNER JOIN sodatone.luminate_unified_song_spotify_tracks lust ON lust.spotify_track_id = st.id
    INNER JOIN sodatone.LUMINATE_DAILY_SONG_METRICS_HISTORY h ON h.unified_song_id = lust.unified_song_id
    WHERE st.primary_spotify_account_id IN (
        SELECT id FROM sodatone.spotify_accounts WHERE artist_id IN ({id_filter})
    )
    AND h.date >= DATEADD('day', -7, CURRENT_DATE())
    GROUP BY st.id
)
SELECT
    st.id AS TRACK_ID,
    st.name AS TRACK_NAME,
    sa.name AS ALBUM_NAME,
    sa.release_date AS RELEASE_DATE,
    st.popularity AS SPOTIFY_POPULARITY,
    COALESCE(tws.weekly_us_audio_streams, 0) AS WEEKLY_US_AUDIO_STREAMS,
    COALESCE(tws.weekly_global_audio_streams, 0) AS WEEKLY_GLOBAL_AUDIO_STREAMS,
    COALESCE(tws.weekly_us_video_streams, 0) AS WEEKLY_US_VIDEO_STREAMS,
    DATEDIFF('week', sa.release_date, CURRENT_DATE()) AS WEEKS_SINCE_RELEASE
FROM sodatone.spotify_tracks st
INNER JOIN sodatone.spotify_albums sa ON sa.id = st.spotify_album_id
LEFT JOIN track_weekly_streams tws ON tws.track_id = st.id
WHERE st.primary_spotify_account_id IN (
    SELECT id FROM sodatone.spotify_accounts WHERE artist_id IN ({id_filter})
)
ORDER BY tws.weekly_us_audio_streams DESC NULLS LAST
"""

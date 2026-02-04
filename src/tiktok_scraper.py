"""TikTok scraper using Playwright for full browser automation."""

from __future__ import annotations

import logging
import re
from typing import Optional

from .models import TikTokSound

logger = logging.getLogger(__name__)

# Import Playwright
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.error("Playwright not installed!")


def _parse_count(count_str: str) -> int:
    """Parse a count string that may have K/M suffixes."""
    count_str = count_str.replace(',', '').strip()
    if 'k' in count_str.lower():
        return int(float(count_str.lower().replace('k', '')) * 1000)
    elif 'm' in count_str.lower():
        return int(float(count_str.lower().replace('m', '')) * 1000000)
    elif 'b' in count_str.lower():
        return int(float(count_str.lower().replace('b', '')) * 1000000000)
    else:
        try:
            return int(count_str)
        except ValueError:
            return 0


def scrape_tiktok_sound(sound_id: str) -> Optional[TikTokSound]:
    """Scrape TikTok sound data using Playwright browser automation.

    Args:
        sound_id: The TikTok sound ID (numeric string)

    Returns:
        TikTokSound object if successful, None otherwise
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.error("Playwright not available")
        return None

    url = f"https://www.tiktok.com/music/original-sound-{sound_id}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            logger.info("Loading TikTok page for sound %s", sound_id)
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(5000)  # Wait for JS to load

            title = page.title()
            logger.info("Page title: %s", title)

            # Check if valid music page
            if title == "TikTok - Make Your Day" or "| TikTok" not in title:
                logger.warning("Sound %s not found on TikTok", sound_id)
                browser.close()
                return None

            # Extract sound name from title
            sound_name = title.replace(' | TikTok', '').replace(' - original sound', '').strip()
            if not sound_name:
                sound_name = f"TikTok Sound {sound_id[-8:]}"

            # Get page text to find video count
            body_text = page.locator('body').text_content() or ""

            # Find video count (creates)
            creates = 0
            video_match = re.search(r'(\d[\d,\.]*[KkMm]?)\s*videos?', body_text, re.IGNORECASE)
            if video_match:
                creates = _parse_count(video_match.group(1))
                logger.info("Found %d creates for sound %s", creates, sound_id)

            browser.close()

            return TikTokSound(
                sound_id=sound_id,
                name=sound_name,
                artist_name=sound_name,
                tiktok_url=url,
                total_creates=creates,
                creates_7d=0,
                creates_24h=0,
                total_views=0,
                views_7d=0,
                views_24h=0,
            )

    except Exception as e:
        logger.error("Scraping failed for sound %s: %s", sound_id, e)
        return None


def scrape_tiktok_sound_from_url(url: str) -> Optional[TikTokSound]:
    """Scrape TikTok sound data from a TikTok URL."""
    patterns = [
        r"tiktok\.com/music/[^/]+-(\d+)",
        r"tiktok\.com/music/(\d+)",
    ]

    sound_id = None
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            sound_id = match.group(1)
            break

    if not sound_id:
        logger.warning("Could not extract sound ID from URL: %s", url)
        return None

    return scrape_tiktok_sound(sound_id)


def is_scraper_available() -> bool:
    """Check if the TikTok scraper is available."""
    return PLAYWRIGHT_AVAILABLE

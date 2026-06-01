"""
@billimindst → Substack Notes Bot
----------------------------------
Watches the @billimindst X account via RSS.
When a new original post is detected (no retweets, no replies),
it posts the text to Substack Notes automatically.

Runs every 10 minutes on Railway.
"""

import os
import re
import json
import time
import logging
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config (from environment variables) ───────────────────────────────────────
X_USERNAME        = os.environ.get("X_USERNAME", "billimindst")
SUBSTACK_SID      = os.environ.get("SUBSTACK_SID")          # connect.sid cookie value
SUBSTACK_HANDLE   = os.environ.get("SUBSTACK_HANDLE", "billionairemindset")
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", "600"))  # 10 min default
POSTED_LOG_FILE   = os.environ.get("POSTED_LOG_FILE", "posted_ids.json")

# ── Validation ────────────────────────────────────────────────────────────────
if not SUBSTACK_SID:
    raise EnvironmentError(
        "SUBSTACK_SID environment variable is not set. "
        "Add it in Railway → Variables."
    )

# ── Posted-IDs persistence ────────────────────────────────────────────────────
def load_posted_ids() -> set:
    """Load set of already-posted tweet IDs from disk."""
    if Path(POSTED_LOG_FILE).exists():
        try:
            with open(POSTED_LOG_FILE) as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_posted_ids(ids: set) -> None:
    """Persist posted tweet IDs to disk."""
    with open(POSTED_LOG_FILE, "w") as f:
        json.dump(list(ids), f)


# ── X RSS Feed ────────────────────────────────────────────────────────────────
RSS_URL = f"https://rsshub.app/twitter/user/{X_USERNAME}"
# Fallback mirrors in case primary is down
RSS_MIRRORS = [
    f"https://rsshub.app/twitter/user/{X_USERNAME}",
    f"https://nitter.privacydev.net/{X_USERNAME}/rss",
    f"https://nitter.poast.org/{X_USERNAME}/rss",
]


def fetch_rss_feed() -> str | None:
    """Try RSS mirrors until one responds."""
    for url in RSS_MIRRORS:
        try:
            r = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 BillimindstBot/1.0"
            })
            if r.status_code == 200 and "<item>" in r.text:
                log.info(f"RSS fetched from: {url}")
                return r.text
        except Exception as e:
            log.warning(f"RSS mirror failed ({url}): {e}")
    log.error("All RSS mirrors failed.")
    return None


def parse_tweets(rss_xml: str) -> list[dict]:
    """
    Parse RSS XML and return list of tweet dicts.
    Each dict has: id, text, url, published
    """
    tweets = []
    try:
        root = ET.fromstring(rss_xml)
        # Handle both RSS 2.0 and Atom namespaces
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        channel = root.find("channel")
        if channel is None:
            return tweets

        for item in channel.findall("item"):
            title_el = item.find("title")
            link_el  = item.find("link")
            guid_el  = item.find("guid")
            desc_el  = item.find("description")

            raw_text = ""
            if title_el is not None and title_el.text:
                raw_text = title_el.text.strip()
            elif desc_el is not None and desc_el.text:
                # Strip HTML tags from description
                raw_text = re.sub(r"<[^>]+>", "", desc_el.text).strip()

            link = link_el.text.strip() if link_el is not None and link_el.text else ""
            guid = guid_el.text.strip() if guid_el is not None and guid_el.text else link

            # Stable ID: hash of the URL/guid
            tweet_id = hashlib.md5(guid.encode()).hexdigest()

            tweets.append({
                "id":   tweet_id,
                "text": raw_text,
                "url":  link,
            })
    except ET.ParseError as e:
        log.error(f"RSS parse error: {e}")

    return tweets


def is_original_post(text: str) -> bool:
    """
    Return True only if this is an original post, not a retweet or reply.
    Filters:
    - RT @... (retweet)
    - @username at the start (reply)
    - Empty text
    """
    if not text:
        return False
    if text.startswith("RT @"):
        return False
    if text.startswith("@"):
        return False
    return True


def clean_text(text: str) -> str:
    """
    Clean tweet text for Substack:
    - Remove trailing URLs (t.co links)
    - Strip extra whitespace
    """
    # Remove t.co URLs at end of text
    text = re.sub(r"\s+https?://t\.co/\S+$", "", text).strip()
    text = re.sub(r"\s+https?://t\.co/\S+", " ", text).strip()
    return text


# ── Substack Notes API ────────────────────────────────────────────────────────
SUBSTACK_API = "https://substack.com/api/v1"


def post_substack_note(text: str) -> bool:
    """
    Post text as a Substack Note using the internal API.
    Returns True on success.
    """
    headers = {
        "Content-Type": "application/json",
        "Cookie": f"substack.sid={SUBSTACK_SID}",
        "User-Agent": "Mozilla/5.0 BillimindstBot/1.0",
        "Referer": "https://substack.com",
        "Origin": "https://substack.com",
    }

    # Substack Notes body format
    # Body is a Prosemirror JSON doc
    payload = {
        "bodyJson": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": text
                        }
                    ]
                }
            ]
        }
    }

    try:
        r = requests.post(
            f"{SUBSTACK_API}/notes",
            json=payload,
            headers=headers,
            timeout=20,
        )

        if r.status_code in (200, 201):
            log.info(f"✅ Posted to Substack Notes: \"{text[:60]}...\"")
            return True
        elif r.status_code == 401:
            log.error("❌ Substack auth failed — SUBSTACK_SID cookie may have expired. Re-extract from browser.")
            return False
        else:
            log.error(f"❌ Substack API error {r.status_code}: {r.text[:200]}")
            return False

    except requests.RequestException as e:
        log.error(f"❌ Substack request failed: {e}")
        return False


def verify_substack_auth() -> bool:
    """Test that our Substack session is valid on startup."""
    headers = {
        "Cookie": f"substack.sid={SUBSTACK_SID}",
        "User-Agent": "Mozilla/5.0 BillimindstBot/1.0",
        "Referer": "https://substack.com",
    }
    try:
        # Use the reader feed endpoint — reliable auth check
        r = requests.get(
            "https://substack.com/api/v1/reader/feed/home?limit=1",
            headers=headers,
            timeout=10,
        )
        if r.status_code == 200:
            log.info(f"✅ Substack auth OK — session valid")
            return True
        elif r.status_code == 401:
            log.error(f"❌ Substack auth failed (401 Unauthorized) — re-extract substack.sid cookie from browser")
            return False
        else:
            # Try alternate endpoint
            r2 = requests.get(
                "https://substack.com/api/v1/subscriptions",
                headers=headers,
                timeout=10,
            )
            if r2.status_code == 200:
                log.info(f"✅ Substack auth OK — session valid")
                return True
            log.error(f"❌ Substack auth check failed ({r.status_code}) — check your SUBSTACK_SID")
            return False
    except Exception as e:
        log.error(f"❌ Substack auth check error: {e}")
        return False


# ── Main Loop ─────────────────────────────────────────────────────────────────
def run():
    log.info("=" * 50)
    log.info("@billimindst → Substack Notes Bot starting...")
    log.info(f"Polling @{X_USERNAME} every {POLL_INTERVAL_SEC}s")
    log.info(f"Posting to Substack: @{SUBSTACK_HANDLE}")
    log.info("=" * 50)

    # Verify Substack auth on startup
    if not verify_substack_auth():
        log.warning("⚠️ Substack auth check inconclusive — will attempt posting anyway. If posts fail, re-extract substack.sid.")

    posted_ids = load_posted_ids()
    log.info(f"Loaded {len(posted_ids)} previously posted tweet IDs")

    # On first run, seed with existing tweets so we don't blast old content
    first_run = len(posted_ids) == 0

    while True:
        try:
            log.info(f"Checking @{X_USERNAME} feed...")
            rss_xml = fetch_rss_feed()

            if rss_xml:
                tweets = parse_tweets(rss_xml)
                log.info(f"Found {len(tweets)} tweets in feed")

                new_posts = 0
                for tweet in tweets:
                    if tweet["id"] in posted_ids:
                        continue  # Already handled

                    if first_run:
                        # Seed IDs without posting on first run
                        posted_ids.add(tweet["id"])
                        continue

                    if not is_original_post(tweet["text"]):
                        log.info(f"Skipping (retweet/reply): \"{tweet['text'][:50]}\"")
                        posted_ids.add(tweet["id"])
                        continue

                    clean = clean_text(tweet["text"])
                    if not clean:
                        posted_ids.add(tweet["id"])
                        continue

                    success = post_substack_note(clean)
                    posted_ids.add(tweet["id"])

                    if success:
                        new_posts += 1
                        # Small delay between posts to avoid rate limiting
                        time.sleep(3)

                if first_run:
                    log.info(f"First run — seeded {len(posted_ids)} existing tweet IDs. Will post NEW tweets only from now on.")
                    first_run = False
                else:
                    log.info(f"Cycle complete — {new_posts} new posts sent to Substack")

                save_posted_ids(posted_ids)

        except KeyboardInterrupt:
            log.info("Shutting down gracefully...")
            save_posted_ids(posted_ids)
            break
        except Exception as e:
            log.error(f"Unexpected error in main loop: {e}", exc_info=True)

        log.info(f"Sleeping {POLL_INTERVAL_SEC}s until next check...")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    run()

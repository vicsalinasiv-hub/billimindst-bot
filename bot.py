"""
@billimindst → Substack Notes Bot (Webhook Edition)
-----------------------------------------------------
Receives a webhook from TweetHunter/IFTTT/Zapier when a tweet is published,
then posts the text to Substack Notes automatically.

Two modes:
1. WEBHOOK MODE (recommended): Receives POST from TweetHunter/IFTTT
2. POLLING MODE (fallback): Watches X via RSSHub public instance

Runs on Railway. Exposes port 8080 for webhook.
"""

import os
import re
import json
import time
import logging
import hashlib
import threading
import xml.etree.ElementTree as ET
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
X_USERNAME        = os.environ.get("X_USERNAME", "billimindst")
SUBSTACK_SID      = os.environ.get("SUBSTACK_SID")
SUBSTACK_HANDLE   = os.environ.get("SUBSTACK_HANDLE", "billionairemindset")
WEBHOOK_SECRET    = os.environ.get("WEBHOOK_SECRET", "billimindst2026")
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", "600"))
POSTED_LOG_FILE   = os.environ.get("POSTED_LOG_FILE", "posted_ids.json")
PORT              = int(os.environ.get("PORT", "8080"))
MODE              = os.environ.get("MODE", "both")  # webhook, polling, or both

if not SUBSTACK_SID:
    raise EnvironmentError("SUBSTACK_SID environment variable is not set.")

# ── Posted-IDs ────────────────────────────────────────────────────────────────
def load_posted_ids() -> set:
    if Path(POSTED_LOG_FILE).exists():
        try:
            with open(POSTED_LOG_FILE) as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def save_posted_ids(ids: set) -> None:
    with open(POSTED_LOG_FILE, "w") as f:
        json.dump(list(ids), f)

posted_ids = load_posted_ids()
posted_ids_lock = threading.Lock()

# ── Text helpers ──────────────────────────────────────────────────────────────
def is_original_post(text: str) -> bool:
    if not text: return False
    if text.startswith("RT @"): return False
    if text.startswith("@"): return False
    return True

def clean_text(text: str) -> str:
    text = re.sub(r"\s+https?://t\.co/\S+$", "", text).strip()
    text = re.sub(r"\s+https?://t\.co/\S+", " ", text).strip()
    return text

def make_id(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

# ── Substack Notes API ────────────────────────────────────────────────────────
def post_substack_note(text: str) -> bool:
    headers = {
        "Content-Type": "application/json",
        "Cookie": f"substack.sid={SUBSTACK_SID}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://substack.com",
        "Origin": "https://substack.com",
    }
    payload = {
        "bodyJson": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": text}]
                }
            ]
        }
    }
    try:
        r = requests.post(
            "https://substack.com/api/v1/notes",
            json=payload,
            headers=headers,
            timeout=20,
        )
        if r.status_code in (200, 201):
            log.info(f'✅ Posted to Substack: "{text[:60]}"')
            return True
        elif r.status_code == 401:
            log.error("❌ Substack 401 — SUBSTACK_SID expired. Re-extract from browser.")
            return False
        else:
            log.error(f"❌ Substack error {r.status_code}: {r.text[:300]}")
            return False
    except Exception as e:
        log.error(f"❌ Substack request failed: {e}")
        return False

def handle_new_tweet(text: str, tweet_id: str = None) -> bool:
    """Central handler for any new tweet from any source."""
    global posted_ids
    
    tid = tweet_id or make_id(text)
    
    with posted_ids_lock:
        if tid in posted_ids:
            log.info(f"Skipping duplicate: {tid}")
            return False
    
    if not is_original_post(text):
        log.info(f'Skipping retweet/reply: "{text[:50]}"')
        with posted_ids_lock:
            posted_ids.add(tid)
            save_posted_ids(posted_ids)
        return False
    
    clean = clean_text(text)
    if not clean:
        return False
    
    success = post_substack_note(clean)
    
    with posted_ids_lock:
        posted_ids.add(tid)
        save_posted_ids(posted_ids)
    
    return success

# ── Webhook Server ────────────────────────────────────────────────────────────
class WebhookHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        pass  # Suppress default HTTP logs (we use our own)
    
    def do_GET(self):
        """Health check endpoint."""
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK - Billimindst bot running")
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        """
        Webhook endpoint. Accepts tweet text from IFTTT/TweetHunter.
        
        Expected body (JSON):
          {"text": "your tweet here", "secret": "billimindst2026"}
        
        Or form-encoded:
          text=your+tweet&secret=billimindst2026
        """
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        
        tweet_text = None
        secret = None
        
        content_type = self.headers.get("Content-Type", "")
        
        try:
            if "application/json" in content_type:
                data = json.loads(body)
                tweet_text = data.get("text") or data.get("tweet") or data.get("body")
                secret = data.get("secret", "")
            else:
                # Form-encoded or plain text
                try:
                    params = parse_qs(body.decode())
                    tweet_text = params.get("text", [None])[0] or params.get("tweet", [None])[0]
                    secret = params.get("secret", [""])[0]
                except Exception:
                    tweet_text = body.decode().strip()
                    secret = WEBHOOK_SECRET  # Trust plain text if no secret field
        except Exception as e:
            log.error(f"Webhook parse error: {e}")
            self.send_response(400)
            self.end_headers()
            return
        
        # Verify secret
        if secret != WEBHOOK_SECRET:
            log.warning(f"Webhook rejected — wrong secret")
            self.send_response(403)
            self.end_headers()
            return
        
        if not tweet_text:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing tweet text")
            return
        
        log.info(f'📨 Webhook received: "{tweet_text[:60]}"')
        
        # Handle in background thread so we can respond immediately
        threading.Thread(
            target=handle_new_tweet,
            args=(tweet_text,),
            daemon=True
        ).start()
        
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")


# ── RSS Polling ───────────────────────────────────────────────────────────────
RSS_MIRRORS = [
    f"https://rsshub.app/twitter/user/{X_USERNAME}",
    f"https://rsshub.app/x/user/{X_USERNAME}",
    f"https://rss.app/feeds/twitter/{X_USERNAME}.xml",
]

def fetch_rss() -> str | None:
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
    return None

def parse_rss(xml: str) -> list[dict]:
    tweets = []
    try:
        root = ET.fromstring(xml)
        channel = root.find("channel")
        if not channel:
            return tweets
        for item in channel.findall("item"):
            title = item.find("title")
            link  = item.find("link")
            guid  = item.find("guid")
            text  = title.text.strip() if title is not None and title.text else ""
            url   = link.text.strip() if link is not None and link.text else ""
            gid   = guid.text.strip() if guid is not None and guid.text else url
            tweets.append({
                "id": hashlib.md5(gid.encode()).hexdigest(),
                "text": text,
            })
    except Exception as e:
        log.error(f"RSS parse error: {e}")
    return tweets

def polling_loop():
    global posted_ids
    log.info(f"📡 Polling mode: checking @{X_USERNAME} every {POLL_INTERVAL_SEC}s")
    
    first_run = len(posted_ids) == 0
    
    while True:
        try:
            xml = fetch_rss()
            if xml:
                tweets = parse_rss(xml)
                log.info(f"Found {len(tweets)} tweets in RSS feed")
                
                if first_run:
                    with posted_ids_lock:
                        for t in tweets:
                            posted_ids.add(t["id"])
                        save_posted_ids(posted_ids)
                    log.info(f"First run — seeded {len(tweets)} IDs. New tweets only from now on.")
                    first_run = False
                else:
                    new = 0
                    for tweet in tweets:
                        with posted_ids_lock:
                            already = tweet["id"] in posted_ids
                        if not already:
                            if handle_new_tweet(tweet["text"], tweet["id"]):
                                new += 1
                                time.sleep(2)
                    if new:
                        log.info(f"Posted {new} new tweets to Substack")
            else:
                log.warning("All RSS mirrors failed — will retry next cycle")
        except Exception as e:
            log.error(f"Polling error: {e}", exc_info=True)
        
        time.sleep(POLL_INTERVAL_SEC)


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    log.info("=" * 55)
    log.info("@billimindst → Substack Notes Bot starting...")
    log.info(f"Mode: {MODE} | Port: {PORT}")
    log.info(f"Posting to Substack: @{SUBSTACK_HANDLE}")
    log.info("=" * 55)
    
    # Start polling in background if enabled
    if MODE in ("polling", "both"):
        t = threading.Thread(target=polling_loop, daemon=True)
        t.start()
    
    # Start webhook server (always — Railway needs a port to be open)
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    log.info(f"🌐 Webhook server listening on port {PORT}")
    log.info(f"   POST /  with JSON: {{\"text\": \"tweet\", \"secret\": \"{WEBHOOK_SECRET}\"}}")
    log.info(f"   GET  /health  →  health check")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")

if __name__ == "__main__":
    run()

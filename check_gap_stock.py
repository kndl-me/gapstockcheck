
#!/usr/bin/env python3
"""
GAP Size Monitor - Discord-friendly
- Posts to webhooks using both 'content' (Discord) and 'text' (Slack-style) keys.
- Only sends notifications when size appears IN STOCK (by default).
"""
import argparse, json, re, sys, requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA}

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text

def check_once(url, size):
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    size_lower = size.lower()
    # Negatives first
    if re.search(rf"\b{re.escape(size_lower)}\b\s*[-–:]?\s*(out of stock|sold out|unavailable)", text):
        return False, "out of stock text found"
    # Positives
    if re.search(rf"\b{re.escape(size_lower)}\b.*(add to bag|add to cart|in stock|available)", text):
        return True, "appears available"
    return None, "could not determine"

def notify(webhook, message):
    payload = {"content": message, "text": message, "username": "GAP Stock Monitor"}
    try:
        requests.post(webhook, json=payload, timeout=10)
    except Exception as e:
        print(f"Webhook failed: {e}", file=sys.stderr)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--size", required=True)
    ap.add_argument("--webhook")
    ap.add_argument("--quiet", action="store_true", help="suppress console output unless IN STOCK or unknown")
    ap.add_argument("--always-notify", action="store_true", help="send a test notification regardless of stock")
    args = ap.parse_args()

    ok, detail = check_once(args.url, args.size)
    msg = f"⚠️ Could not determine stock for {args.size} ({detail})\n{args.url}"
    if ok is True:
        msg = f"✅ Size {args.size} appears IN STOCK ({detail})\n{args.url}"
    elif ok is False:
        msg = f"❌ Size {args.size} appears OUT OF STOCK ({detail})\n{args.url}"

    if args.always-notify or not args.quiet or ok is True or ok is None:
        print(msg)

    if args.webhook:
        if args.always-notify or ok is True or ok is None:
            notify(args.webhook, msg)

if __name__ == "__main__":
    main()

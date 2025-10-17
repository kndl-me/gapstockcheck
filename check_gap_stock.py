
#!/usr/bin/env python3
"""
GAP Size Monitor - Checks a GAP product page for availability of a target size.
Usage example:
    python check_gap_stock.py --url "https://www.gap.com/browse/product.do?pid=XXXXX" --size L --webhook "https://hooks.slack.com/services/..."
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
    if re.search(rf"\b{re.escape(size_lower)}\b\s*[-–:]?\s*(out of stock|sold out|unavailable)", text):
        return False, "out of stock text found"
    if re.search(rf"\b{re.escape(size_lower)}\b.*(add to bag|in stock|available)", text):
        return True, "appears available"
    return None, "could not determine"

def notify(webhook, message):
    try:
        requests.post(webhook, json={"text": message}, timeout=10)
    except Exception as e:
        print(f"Webhook failed: {e}", file=sys.stderr)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--size", required=True)
    ap.add_argument("--webhook")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    ok, detail = check_once(args.url, args.size)
    msg = f"⚠️ Could not determine stock for {args.size} ({detail})\n{args.url}"
    if ok is True:
        msg = f"✅ Size {args.size} appears IN STOCK ({detail})\n{args.url}"
    elif ok is False:
        msg = f"❌ Size {args.size} appears OUT OF STOCK ({detail})\n{args.url}"

    if not args.quiet or ok:
        print(msg)
    if args.webhook and ok:
        notify(args.webhook, msg)

if __name__ == "__main__":
    main()

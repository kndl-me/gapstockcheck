#!/usr/bin/env python3
"""
GAP Size Monitor — Robust parser (JSON-aware) + Discord-safe
- Looks for availability in JSON-LD and embedded JSON first.
- Falls back to page text heuristics (Add to Bag / Out of Stock near size).
- Posts to Discord-compatible webhooks via `content` (also includes `text` for Slack).
"""
import argparse, json, re, sys, requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

TRUTHY = {"true","in stock","instock","available","yes","in_stock","in-stock","availableforpurchase","ok"}
FALSY  = {"false","out of stock","outofstock","unavailable","no","soldout","sold out","notavailable"}

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text

def parse_json_blocks(soup: BeautifulSoup):
    blocks = []
    # JSON-LD
    for tag in soup.find_all("script", type="application/ld+json"):
        txt = tag.get_text(strip=True)
        try:
            data = json.loads(txt)
            if isinstance(data, list):
                blocks.extend([d for d in data if isinstance(d, dict)])
            elif isinstance(data, dict):
                blocks.append(data)
        except Exception:
            continue
    # Other scripts — look for big JSON-ish objects containing availability fields
    for tag in soup.find_all("script"):
        txt = tag.string or tag.get_text() or ""
        if not txt or ("{" not in txt):
            continue
        if not re.search(r"(availability|inStock|availabilityStatus|offers|variants|sku|size|inventory)", txt, re.I):
            continue
        # Try to extract JSON objects with a simple brace-matching approach
        for m in re.finditer(r"(?P<json>\{(?:[^{}]|(?P>json))*\})", txt, re.DOTALL):
            js = m.group("json")
            if not re.search(r"(availability|inStock|availabilityStatus|offers|variants|sku|size|inventory)", js, re.I):
                continue
            # Try strict JSON first
            try:
                blocks.append(json.loads(js))
                continue
            except Exception:
                pass
            # Try common coercions: single quotes -> double quotes
            try:
                coerced = js.replace("'", '"')
                blocks.append(json.loads(coerced))
            except Exception:
                pass
    return blocks

def flatten(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(flatten(v, key))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            key = f"{prefix}[{i}]" if prefix else f"[{i}]"
            out.update(flatten(v, key))
    else:
        out[prefix] = d
    return out

def find_size_records(blocks):
    recs = []
    for b in blocks:
        flat = flatten(b)
        for k, v in flat.items():
            if not isinstance(v, (str, int, float, bool)):
                continue
            lk = k.lower()
            if any(tok in lk for tok in ("size","variant","sku","label")):
                parent = k.rsplit(".", 1)[0] if "." in k else ""
                record = {kk: vv for kk, vv in flat.items() if parent and kk.startswith(parent)}
                if record and record not in recs:
                    recs.append(record)
    return recs

def interpret_availability(records, target_size):
    t = target_size.strip().lower()
    for rec in records:
        fields = {k.lower(): str(v).strip() for k, v in rec.items() if isinstance(v, (str,int,float,bool))}
        # candidate size strings
        size_values = [v for k, v in fields.items() if any(s in k for s in ("size","label","variant","name"))]
        size_match = any(t == sv.lower() or re.search(rf"\b{re.escape(t)}\b", sv, re.I) for sv in size_values)
        if not size_match:
            continue
        # availability signals
        avail_values = [v for k, v in fields.items() if any(a in k for a in ("avail","in_stock","instock","stock","isavailable","inventory","availabilitystatus","status"))]
        qty_values   = [v for k, v in fields.items() if "qty" in k or "quantity" in k]
        # quantities
        for q in qty_values:
            if str(q).isdigit() and int(q) > 0:
                return True, f"quantity={q}"
        # textual
        for av in avail_values:
            lav = str(av).lower()
            if lav in TRUTHY or re.search(r"in\s*stock|available|ok|true", lav):
                return True, str(av)
            if lav in FALSY or re.search(r"out\s*of\s*stock|sold\s*out|unavailable|false", lav):
                return False, str(av)
    return None

def fallback_text(soup: BeautifulSoup, target_size: str):
    t = target_size.strip().lower()
    text = soup.get_text(" ", strip=True).lower()
    # direct phrases including size
    if re.search(rf"\b{re.escape(t)}\b\s*[-–—:]?\s*(out of stock|sold out|unavailable)", text):
        return False, "text: out of stock"
    if re.search(rf"\b{re.escape(t)}\b.*(add to bag|add to cart|in stock|available)", text):
        return True, "text: likely in stock"
    # generic cues if size isn't echoed in text
    if re.search(r"add to bag|add to cart", text):
        return True, "text: add to bag found"
    if re.search(r"out of stock|sold out|unavailable", text):
        return False, "text: global out of stock"
    return None

def check_once(url, target_size, debug=False):
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    # 1) JSON-based parsing
    blocks = parse_json_blocks(soup)
    records = find_size_records(blocks)
    res = interpret_availability(records, target_size)
    if isinstance(res, tuple):
        return res
    # 2) Fallback text
    res2 = fallback_text(soup, target_size)
    if res2 is not None:
        return res2
    if debug:
        candidates = soup.find_all(string=re.compile(r"(in stock|out of stock|add to bag|size)", re.I))
        print("[debug] candidates:", [c.strip()[:80] for c in candidates[:15]], file=sys.stderr)
    return None, "could not determine"

def notify(webhook, message):
    # Discord uses 'content'; include 'text' for Slack compatibility.
    payload = {"content": message, "text": message, "username": "GAP Stock Monitor"}
    try:
        requests.post(webhook, json=payload, timeout=10)
    except Exception:
        # swallow webhook errors to keep runs green
        pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--size", required=True, help='Use the visible label, e.g., "Large" or "L"')
    ap.add_argument("--webhook")
    ap.add_argument("--quiet", action="store_true", help="suppress console unless IN STOCK or unknown")
    ap.add_argument("--always_notify", action="store_true", help="send a test notification regardless of stock")
    ap.add_argument("--debug", action="store_true", help="print debug parsing hints")
    args = ap.parse_args()

    ok, detail = check_once(args.url, args.size, debug=args.debug)
    msg = f"⚠️ Could not determine stock for {args.size} ({detail})\n{args.url}"
    if ok is True:
        msg = f"✅ Size {args.size} appears IN STOCK ({detail})\n{args.url}"
    elif ok is False:
        msg = f"❌ Size {args.size} appears OUT OF STOCK ({detail})\n{args.url}"

    if args.always_notify or not args.quiet or ok is True or ok is None:
        print(msg)

    if args.webhook and (args.always_notify or ok is True or ok is None):
        notify(args.webhook, msg)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Drill News Scanner — Web App (memory-optimised for Render free tier)
Scrapes Investegate daily for drilling-related RNS from resource sector companies.
Summarises each with Claude API (200-word max + assessment).
Serves results on a mobile-friendly web page.
"""

import gc
import os
import time
import json
from datetime import datetime, date
from pathlib import Path

import requests
from bs4 import BeautifulSoup, SoupStrainer
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# --- Configuration ---
BASE_URL = "https://www.investegate.co.uk"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CACHE_FILE = Path("/tmp/drill_news_cache.json")
MAX_PAGES = 8          # Limit pagination (covers ~400 announcements)
MAX_RNS_CHARS = 4000   # Truncate RNS text to save memory
MAX_MATCHES = 15       # Cap drill matches to summarise

# --- Drilling keywords (headline-level filter) ---
DRILL_HEADLINE_KEYWORDS = [
    "drill", "drilling", "drilled",
    "spud", "spudded", "spudding",
    "well test", "well result", "well completion",
    "exploration update", "exploration result",
    "assay", "assay result",
    "resource estimate", "resource update",
    "maiden resource",
    "bore", "borehole",
    "core sample", "diamond drill",
    "RC drill", "reverse circulation",
    "infill", "step-out", "step out",
    "intercept", "mineralisation", "mineralization",
    "gold grade", "copper grade", "ore grade",
    "metres of", "meters of",
    "flow test", "flow rate", "IP test",
    "geological", "geophysical",
    "seismic", "survey result",
    "oil discovery", "gas discovery",
    "production update", "production result",
    "operations update", "operational update",
    "field development",
    "JORC", "NI 43-101", "43-101",
    "CPR", "competent person",
    "preliminary economic assessment", "PEA",
    "definitive feasibility", "DFS",
    "pre-feasibility", "PFS",
    "scoping study",
    "pilot plant",
    "test work", "testwork", "metallurgical",
]

RESOURCE_SECTOR_KEYWORDS = [
    "mining", "mines", "miner",
    "resources", "resource",
    "metals", "metal",
    "gold", "silver", "copper", "zinc", "lithium", "nickel",
    "cobalt", "tin", "iron", "uranium", "platinum", "palladium",
    "rare earth", "graphite", "manganese", "vanadium", "tungsten",
    "helium",
    "oil", "gas", "petroleum", "energy",
    "exploration", "explorer",
    "mineral", "minerals",
]

STRONG_DRILL_KEYWORDS = [
    "drill", "drilling", "drilled", "spud", "spudded",
    "assay", "intercept", "mineralisation", "mineralization",
    "jorc", "ni 43-101", "43-101", "cpr", "competent person",
    "borehole", "core sample", "diamond drill", "rc drill",
    "flow test", "flow rate", "well test", "well result",
    "maiden resource", "resource estimate",
    "dfs", "pfs", "pea", "scoping study",
]


# --- Scrape Investegate (memory-lean: parse only <table>) ---
def scrape_investegate():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })
    session.cookies.set("utype", "PI", domain="www.investegate.co.uk")

    all_announcements = []
    today = date.today()
    today_str = today.strftime("%-d %b %Y")
    today_str_padded = today.strftime("%d %b %Y")

    parse_only = SoupStrainer("table")

    for page_num in range(1, MAX_PAGES + 1):
        url = f"{BASE_URL}/" if page_num == 1 else f"{BASE_URL}/?page={page_num}"
        try:
            resp = session.get(url, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser", parse_only=parse_only)
            resp.close()
        except Exception as e:
            print(f"  Warning: page {page_num} failed: {e}")
            break

        tbody = soup.find("tbody")
        if not tbody:
            del soup
            gc.collect()
            break

        page_count = 0
        found_today = False
        past_today = False

        for tr in tbody.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 4:
                continue

            time_text = cells[0].get_text(strip=True)
            company_text = cells[2].get_text(strip=True)
            ann_cell = cells[3]
            ann_text = ann_cell.get_text(strip=True)
            link_tag = ann_cell.find("a")
            ann_url = ""
            if link_tag and link_tag.get("href"):
                href = link_tag["href"]
                ann_url = href if href.startswith("http") else BASE_URL + href

            if today_str in time_text or today_str_padded in time_text:
                found_today = True
                page_count += 1
                all_announcements.append({
                    "time": time_text,
                    "company": company_text,
                    "announcement": ann_text,
                    "url": ann_url,
                })
            elif found_today:
                past_today = True
                break

        del soup
        gc.collect()

        print(f"  Page {page_num}: {page_count} announcements")

        if past_today or (page_num > 1 and not found_today):
            break

        time.sleep(0.3)

    return all_announcements, session


# --- Check if drilling-related ---
def is_drill_related(announcement):
    headline = announcement["announcement"].lower()
    company = announcement["company"].lower()
    combined = headline + " " + company

    headline_match = any(kw.lower() in headline for kw in DRILL_HEADLINE_KEYWORDS)
    if not headline_match:
        return False

    if any(kw.lower() in combined for kw in RESOURCE_SECTOR_KEYWORDS):
        return True

    return any(kw in headline for kw in STRONG_DRILL_KEYWORDS)


# --- Fetch full RNS text (lean: parse only content div) ---
def fetch_rns_text(url, session):
    try:
        resp = session.get(url, timeout=15)
        text = resp.text
        resp.close()

        # Try targeted parse first
        strainer = SoupStrainer(class_="fr-view-element")
        soup = BeautifulSoup(text, "html.parser", parse_only=strainer)
        content = soup.find(class_="fr-view-element")
        if content:
            result = content.get_text(separator="\n", strip=True)[:MAX_RNS_CHARS]
            del soup, text
            gc.collect()
            return result

        # Fallback: parse article/main
        del soup
        soup = BeautifulSoup(text, "html.parser",
                             parse_only=SoupStrainer(["article", "main"]))
        for tag in soup.find_all(["article", "main"]):
            result = tag.get_text(separator="\n", strip=True)[:MAX_RNS_CHARS]
            del soup, text
            gc.collect()
            return result

        del soup, text
        gc.collect()
        return "Could not extract RNS content."
    except Exception as e:
        return f"Error fetching RNS: {e}"


# --- Summarise with Claude ---
def summarise_with_claude(matches):
    if not ANTHROPIC_API_KEY:
        return None

    rns_data = ""
    for m in matches:
        rns_data += f"\n{'='*40}\n"
        rns_data += f"Company: {m['company']}\n"
        rns_data += f"Headline: {m['announcement']}\n"
        rns_data += f"Time: {m['time']}\n"
        rns_data += f"URL: {m['url']}\n"
        rns_data += f"RNS Text:\n{m.get('rns_text', 'N/A')}\n"

    prompt = (
        "You are a UK broker-dealer analyst specialising in resource sector companies "
        "(mining, oil & gas, energy). Review today's drilling-related RNS announcements.\n\n"
        "For EACH announcement, provide:\n"
        "1. A summary (max 200 words) covering key drilling/exploration details.\n"
        "2. Assessment: **Positive**, **Negative**, or **Neutral** with brief reason.\n\n"
        "Format:\n\n"
        "COMPANY NAME — Headline\n"
        "Summary: [text]\n"
        "Assessment: [Positive/Negative/Neutral] — [reason]\n"
        "---\n\n"
        "Announcements:\n" + rns_data
    )

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01"
    }

    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=body, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        del data
        return "\n".join(text_blocks)
    except Exception as e:
        print(f"Claude API error: {e}")
        return None


# --- Basic fallback ---
def basic_summary(matches):
    lines = []
    for m in matches:
        lines.append(f"{m['company']} — {m['announcement']}")
        rns = m.get("rns_text", "")
        if rns and rns not in ("No URL available.", "Could not extract RNS content."):
            count = 0
            for line in rns.split("\n"):
                stripped = line.strip()
                if stripped and len(stripped) > 15:
                    lines.append(f"  {stripped}")
                    count += 1
                    if count >= 4:
                        break
        lines.append("")
    return "\n".join(lines)


# --- Run the full scan ---
def run_scan():
    print(f"[{datetime.now()}] Starting drill news scan...")
    result = {
        "date": date.today().isoformat(),
        "date_display": date.today().strftime("%A %d %B %Y"),
        "scanned": 0,
        "matched": 0,
        "matches": [],
        "summary": "",
        "last_updated": datetime.now().isoformat(),
        "status": "ok",
    }

    try:
        announcements, session = scrape_investegate()
        result["scanned"] = len(announcements)
        gc.collect()

        if not announcements:
            result["summary"] = "No announcements found. Markets may not be open yet."
            save_cache(result)
            return result

        drill_matches = [a for a in announcements if is_drill_related(a)]
        del announcements
        gc.collect()

        result["matched"] = len(drill_matches)

        if not drill_matches:
            result["summary"] = "No drilling-related resource sector announcements found today."
            save_cache(result)
            return result

        # Cap matches to avoid memory issues
        drill_matches = drill_matches[:MAX_MATCHES]

        # Fetch full RNS text one at a time
        for m in drill_matches:
            if m["url"]:
                print(f"  Reading: {m['company']} — {m['announcement']}")
                m["rns_text"] = fetch_rns_text(m["url"], session)
                time.sleep(0.3)
            else:
                m["rns_text"] = "No URL available."

        session.close()

        result["matches"] = [
            {
                "company": m["company"],
                "announcement": m["announcement"],
                "time": m["time"],
                "url": m["url"],
            }
            for m in drill_matches
        ]

        # Claude summary
        claude_summary = summarise_with_claude(drill_matches)
        if claude_summary:
            result["summary"] = claude_summary
        else:
            result["summary"] = basic_summary(drill_matches)

        del drill_matches
        gc.collect()

    except Exception as e:
        result["status"] = "error"
        result["summary"] = f"Scan failed: {e}"
        print(f"Scan error: {e}")

    save_cache(result)
    print(f"[{datetime.now()}] Done. {result['matched']} hits from {result['scanned']} announcements.")
    return result


# --- Cache ---
def save_cache(data):
    try:
        CACHE_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Cache write error: {e}")


def load_cache():
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except Exception:
        pass
    return None


def get_or_refresh():
    cached = load_cache()
    if cached and cached.get("date") == date.today().isoformat():
        return cached
    return run_scan()


# --- Routes ---
@app.route("/")
def index():
    data = get_or_refresh()
    return render_template("index.html", data=data)


@app.route("/refresh")
def refresh():
    data = run_scan()
    return render_template("index.html", data=data)


@app.route("/api/data")
def api_data():
    data = get_or_refresh()
    return jsonify(data)


@app.route("/api/refresh")
def api_refresh():
    data = run_scan()
    return jsonify(data)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

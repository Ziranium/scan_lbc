#!/usr/bin/env python3
"""Scan LeBonCoin real estate sales ads containing a keyword (default: "loyer") for a given city (default: Nantes).

Usage:
  python3 scripts/scan_lbc.py --city Nantes --query loyer --pages 2 --out results.csv

This is a best-effort scraper that fetches search result pages for property sales, extracts ad URLs,
parses each ad's text to find sale price, loyer, charges and taxe foncière, and computes
gross and net rentability.

Note: Leboncoin structure may change; if you have a specific search URL, pass it
with --search-url to bypass the built-in search builder.
"""

import argparse
import re
import json
import os
from pathlib import Path
import sys
import time
import random
from urllib.parse import urljoin, urlencode, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.leboncoin.fr/",
}

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


AMOUNT_RE = re.compile(r"([0-9]{1,3}(?:[ \u00A0\.,][0-9]{3})*(?:[\.,][0-9]+)?)\s*(?:€|euros?)")


def fetch(url, session=None, playwright_render=False, save_to=None, proxy=None, **kw):
    """Fetch a URL. Supports optional Playwright rendering and saving HTML.

    Parameters:
      - playwright_render: if True, attempt to use Playwright to render JS pages.
      - save_to: optional path to save the fetched HTML for debugging.
      - proxy: optional proxy URL to pass to requests.
    """
    s = session or requests
    headers = kw.pop("headers", None) or HEADERS

    # Playwright render path (lazy import)
    if playwright_render:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=headers.get("User-Agent"))
                page.goto(url, wait_until="networkidle", timeout=30000)
                html = page.content()
                browser.close()
                if save_to:
                    try:
                        Path(save_to).write_text(html, encoding="utf-8")
                    except Exception:
                        pass
                return html
        except Exception as e:
            # If Playwright is not installed or initialization fails, log and fall back
            # to the regular requests-based fetch path instead of raising.
            print(f"Playwright unavailable or failed ({e}); falling back to requests.")

    # Requests path with UA rotation and retries for 403
    resp = None
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        resp = s.get(url, headers=headers, timeout=15, proxies=proxies, **kw)
    except Exception:
        resp = None

    if resp is not None and getattr(resp, "status_code", None) == 403:
        # Retry with exponential backoff for 403 errors (2 retries max)
        for attempt in range(2):
            delay = (5 ** (attempt + 1)) + random.uniform(0, 2)  # 5-7s, 25-27s
            print(f"   ⏳ 403 Forbidden - attente {delay:.1f}s avant retry...")
            time.sleep(delay)
            headers2 = headers.copy()
            headers2["User-Agent"] = random.choice(USER_AGENTS)
            try:
                resp = s.get(url, headers=headers2, timeout=15, proxies=proxies, **kw)
                if resp.status_code == 200:
                    print(f"   ✅ Retry réussi")
                    break
            except Exception:
                resp = None

    if resp is None:
        resp = s.get(url, timeout=15, proxies=proxies, **kw)

    resp.raise_for_status()
    html = resp.text
    if save_to:
        try:
            Path(save_to).write_text(html, encoding="utf-8")
        except Exception:
            pass
    
    # Add longer delay to avoid rate limiting (2-3s)
    time.sleep(random.uniform(2, 3))
    return html


def build_search_url(city, query, page=1):
    # Build a recherche URL for real estate sales. Category 9 = immobilier
    params = {"text": query, "locations": city, "category": "9", "owner_type": "all", "sort": "time", "order": "desc"}
    base = "https://www.leboncoin.fr/recherche"
    if page and page > 1:
        params["page"] = page
    return base + "?" + urlencode(params)


def extract_ad_links_from_search(html):
    soup = BeautifulSoup(html, "lxml")
    links = set()

    # 1) Anchor tags (usual case)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            if "/annonces/" in href or href.startswith("/v") or href.startswith("/vi") or href.startswith("/ad"):
                links.add(urljoin("https://www.leboncoin.fr", href.split("#")[0]))
        elif "leboncoin.fr" in href and ("/annonces/" in href or "/v" in href or "/vi" in href or "/ad" in href):
            links.add(href.split("#")[0])

    # 2) JSON-LD embedded data may contain URLs
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "null")
        except Exception:
            data = None
        if not data:
            continue
        # data can be dict or list; traverse and find strings containing paths
        def walk(obj):
            if isinstance(obj, str):
                if (obj.startswith("/annonces/") or obj.startswith("/v") or obj.startswith("/vi") or "leboncoin.fr/annonces" in obj):
                    yield obj
            elif isinstance(obj, dict):
                for v in obj.values():
                    yield from walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from walk(v)

        for found in walk(data):
            path = found.split("#")[0]
            if path.startswith("/"):
                links.add(urljoin("https://www.leboncoin.fr", path))
            else:
                links.add(path)

    # 3) Fallback: regex search inside HTML for known ad path patterns (useful when links are embedded in JS)
    for m in re.finditer(r'["\'](\/((?:annonces)|v|vi)[^"\']+)["\']', html):
        p = m.group(1).split("#")[0]
        links.add(urljoin("https://www.leboncoin.fr", p))

    # Filter out non-ad root links like '/annonces' or '/vi' without identifier
    def is_ad_url(u):
        try:
            p = urlparse(u).path
        except Exception:
            return False
        parts = [seg for seg in p.split("/") if seg]
        if not parts:
            return False
        # common ad prefixes with at least one more segment
        if parts[0] in ("annonces", "v", "vi") and len(parts) >= 2:
            return True
        # contains numeric id or html extension
        for seg in parts:
            if seg.isdigit() or seg.endswith('.htm') or seg.endswith('.html'):
                return True
        return False

    filtered = [u for u in links if is_ad_url(u)]
    return filtered


def parse_amounts_near_keyword(text, keyword, strict=False):
    """Find amount near a keyword in text.
    
    If strict=True, only look within a small window (50 chars) after the keyword.
    If strict=False, look within a larger window (300 chars).
    """
    text_lower = text.lower()
    keyword_lower = keyword.lower()
    start = 0
    
    while True:
        idx = text_lower.find(keyword_lower, start)
        if idx == -1:
            break
        
        # For "charges", be strict (only look close after the keyword)
        # For "loyer", be more lenient
        if strict:
            # Only search within 50 characters after keyword
            search_end = min(len(text), idx + len(keyword) + 50)
            search_snippet = text[idx:search_end]
        else:
            # Look around the keyword
            window = 300
            snippet_start = max(0, idx - window)
            snippet_end = min(len(text), idx + window)
            search_snippet = text[snippet_start:snippet_end]
        
        # Search for amount starting from keyword position
        m = AMOUNT_RE.search(search_snippet[len(keyword):]) if not strict else AMOUNT_RE.search(search_snippet[len(keyword):])
        if m:
            raw = m.group(1)
            return parse_amount(raw), search_snippet
        
        start = idx + 1  # move past this occurrence
    
    return None, None


def parse_amount(raw):
    if raw is None:
        return None
    
    # Normalize French number formats:
    # "4 524,92" or "4.524,92" (space/dot as thousands, comma as decimal)
    # "4 524.92" (space as thousands, dot as decimal)
    # "4524.92" (dot as decimal)
    # "3.125" (3+ digits after last separator = thousands, not decimal)
    # Rule: Money decimals are max 2 digits (euros and cents); >2 digits = thousands separator
    
    v = raw.strip()
    v = v.replace('\u00A0', ' ')  # Replace non-breaking space with regular space
    
    # Find the rightmost separator (could be . or ,)
    if ',' in v or '.' in v:
        # Get the last occurrence
        last_comma = v.rfind(',')
        last_dot = v.rfind('.')
        
        # Determine which is the decimal separator:
        # - Rightmost one is decimal IF it has 1-2 digits after it
        # - Otherwise, it's a thousands separator
        
        def digits_after(s, pos):
            """Count digits after position pos"""
            count = 0
            for i in range(pos + 1, len(s)):
                if s[i].isdigit():
                    count += 1
                else:
                    break
            return count
        
        comma_digits = digits_after(v, last_comma) if last_comma >= 0 else 0
        dot_digits = digits_after(v, last_dot) if last_dot >= 0 else 0
        
        # Decimal separator must have 1-2 digits after it
        if last_comma > last_dot:
            # Comma is rightmost
            if 1 <= comma_digits <= 2:
                # Comma is decimal: replace all dots/spaces with nothing (thousands), keep comma as decimal
                v = v.replace(' ', '').replace('.', '')
                v = v.replace(',', '.')
            else:
                # Comma has >2 digits = thousands separator, no decimal
                v = v.replace(' ', '').replace(',', '').replace('.', '')
        else:
            # Dot is rightmost
            if 1 <= dot_digits <= 2:
                # Dot is decimal: replace all spaces/commas with nothing (thousands), keep dot
                v = v.replace(' ', '').replace(',', '')
            else:
                # Dot has >2 digits = thousands separator, no decimal
                v = v.replace(' ', '').replace(',', '').replace('.', '')
    else:
        # No separators: just remove spaces
        v = v.replace(' ', '')
    
    try:
        return float(v)
    except Exception:
        return None


def detect_period_from_snippet(snippet):
    s = snippet.lower()
    if "par mois" in s or "/mois" in s or "€/mois" in s or "mois" in s and "par an" not in s:
        return "monthly"
    if "par an" in s or "/an" in s or "annuel" in s or "par an" in s:
        return "annual"
    return None


def parse_ad_page(url, session=None, playwright_render=False, save_to=None, proxy=None):
    html = fetch(url, session=session, playwright_render=playwright_render, save_to=save_to, proxy=proxy)
    soup = BeautifulSoup(html, "lxml")

    title = (soup.title.string or "").strip() if soup.title else ""

    # full text for regex search
    text = soup.get_text(separator=" \n ", strip=True)
    
    # Also extract body text from JSON for more complete content
    body_text = ""
    script = soup.find('script', {'id': '__NEXT_DATA__'})
    ad_data = {}
    if script:
        try:
            data = json.loads(script.string)
            ad_data = data.get('props', {}).get('pageProps', {}).get('ad', {})
            body_text = ad_data.get('body', '')
        except:
            pass
    
    # Combine texts for searching (body first as it may have more structured info)
    combined_text = body_text + "\n" + text if body_text else text
    
    # Price: try to parse from JSON data in the page
    price = None
    if ad_data:
        try:
            price_list = ad_data.get('price', [])
            if price_list:
                price = float(price_list[0])  # price is in euros
        except:
            pass

    if price is None:
        # fallback to text parsing
        price_keywords = ["prix de vente", "prix", "vente"]
        for kw in price_keywords:
            price, _ = parse_amounts_near_keyword(combined_text, kw)
            if price:
                break

        # fallback: largest amount on page (assuming sale price is the highest)
        if price is None:
            amounts = []
            for m in AMOUNT_RE.finditer(combined_text):
                val = parse_amount(m.group(1))
                if val and val > 10000:  # assume sale prices >10k
                    amounts.append(val)
            if amounts:
                price = max(amounts)

    # loyer (rent) - use pattern-based extraction for accuracy
    # Order: SPECIFIC patterns first, then GENERIC patterns
    # IMPORTANT: Loyer is typically 300-3000€/month; if > 5000€ it's likely the sale price, not rental
    loyer = None
    loyer_snip = None
    monthly_rent = None
    
    # Pattern 1: "Loyer annuel : X €" or "loyer annuel X €" - SPECIFIC, check first
    m = re.search(r'loyer\s+annuel\s*:?\s*([0-9]{1,3}(?:[ \u00A0\.,][0-9]{3})*(?:[\.,][0-9]+)?)\s*(?:€|euros?)', combined_text, re.IGNORECASE)
    if m:
        loyer = parse_amount(m.group(1))
        # Sanity check: annual loyer should be 3.6k-36k (monthly 300-3000€)
        if loyer and 3600 <= loyer <= 36000:
            loyer_snip = combined_text[max(0, m.start()-50):min(len(combined_text), m.end()+100)]
            monthly_rent = loyer / 12.0
        else:
            loyer = None
    
    if monthly_rent is None:
        # Pattern 2: "loyer mensuel de X €" or "loyer mensuel X €" - SPECIFIC
        m = re.search(r'loyer\s+mensuel\s+de\s+([0-9]{1,3}(?:[ \u00A0\.,][0-9]{3})*(?:[\.,][0-9]+)?)', combined_text, re.IGNORECASE)
        if m:
            monthly_rent = parse_amount(m.group(1))
            # Sanity check: monthly loyer should be 300-3000€
            if monthly_rent and 300 <= monthly_rent <= 3000:
                loyer_snip = combined_text[max(0, m.start()-50):min(len(combined_text), m.end()+100)]
            else:
                monthly_rent = None
    
    if monthly_rent is None:
        # Pattern 3: "loyer X € [/ an | par an]" - SPECIFIC, check before generic
        m = re.search(r'loyer[^0-9]*([0-9]{1,3}(?:[ \u00A0\.,][0-9]{3})*(?:[\.,][0-9]+)?)\s*€\s*(?:/\s*an|par\s+an)', combined_text, re.IGNORECASE)
        if m:
            loyer = parse_amount(m.group(1))
            # Sanity check: annual loyer should be 3.6k-36k
            if loyer and 3600 <= loyer <= 36000:
                loyer_snip = combined_text[max(0, m.start()-50):min(len(combined_text), m.end()+100)]
                monthly_rent = loyer / 12.0
            else:
                loyer = None
    
    if monthly_rent is None:
        # Pattern 4: "loyer X €" - GENERIC (allows "loyer annuel", "loyer mensuel", "loyer charges comprises", etc.)
        m = re.search(r'loyer[^0-9]*([0-9]{1,3}(?:[ \u00A0\.,][0-9]{3})*(?:[\.,][0-9]+)?)\s*€', combined_text, re.IGNORECASE)
        if m:
            loyer = parse_amount(m.group(1))
            loyer_snip = combined_text[max(0, m.start()-50):min(len(combined_text), m.end()+100)]
            # Need to determine if monthly or annual based on snippet
            snippet = combined_text[max(0, m.start()):min(len(combined_text), m.end()+100)]
            if 'annuel' in snippet.lower() or 'par an' in snippet.lower() or '/an' in snippet.lower():
                # Sanity check: annual loyer should be 3.6k-36k
                if loyer and 3600 <= loyer <= 36000:
                    monthly_rent = loyer / 12.0
                else:
                    loyer = None
            else:
                # Sanity check: monthly loyer should be 300-3000€
                if loyer and 300 <= loyer <= 3000:
                    monthly_rent = loyer
                else:
                    loyer = None
    
    if monthly_rent is None:
        # Pattern 5: "loyer X euros" (no € symbol but word euros)
        m = re.search(r'loyer\s+([0-9]{1,3}(?:[ \u00A0\.,][0-9]{3})*(?:[\.,][0-9]+)?)\s+euros?', combined_text, re.IGNORECASE)
        if m:
            loyer = parse_amount(m.group(1))
            # Sanity check: if no currency context, assume monthly (300-3000€)
            if loyer and 300 <= loyer <= 3000:
                loyer_snip = combined_text[max(0, m.start()-50):min(len(combined_text), m.end()+100)]
                monthly_rent = loyer
            else:
                loyer = None
    
    if monthly_rent is None:
        # Pattern 6: "soit ... X euros par mois" (common pattern after annual rent)
        m = re.search(r'soit\s+.*?([0-9]{1,3}(?:[ \u00A0\.,][0-9]{3})*(?:[\.,][0-9]+)?)\s*euros?\s+par\s+mois', combined_text, re.IGNORECASE | re.DOTALL)
        if m and m.group(1):  # Make sure we found an amount
            monthly_rent = parse_amount(m.group(1))
            # Sanity check: monthly loyer should be 300-3000€
            if monthly_rent and 300 <= monthly_rent <= 3000:
                loyer_snip = combined_text[max(0, m.start()-50):min(len(combined_text), m.end()+100)]
            else:
                monthly_rent = None

    # taxe foncière - search BEFORE charges to avoid false positives
    taxe, taxe_snip = parse_amounts_near_keyword(combined_text, "taxe fonci", strict=True)
    if taxe is None:
        taxe, taxe_snip = parse_amounts_near_keyword(combined_text, "taxe foncière", strict=True)
    taxe_period = detect_period_from_snippet(taxe_snip or "")

    # charges - use multiple patterns to handle different formats
    # Look specifically for "charges" followed by an amount
    charges = None
    charges_snip = None
    
    # Pattern 1: "charges X €" or "charges X euros"
    m = re.search(r'charges\s+([0-9]{1,3}(?:[ \u00A0\.,][0-9]{3})*(?:[\.,][0-9]+)?)\s*(?:€|euros?)', combined_text, re.IGNORECASE)
    if m:
        charges = parse_amount(m.group(1))
        charges_snip = combined_text[max(0, m.start()-50):min(len(combined_text), m.end()+100)]
    else:
        # Pattern 2: "X € de charges" (with or without +)
        m = re.search(r'[+\s]?([0-9]{1,3}(?:[ \u00A0\.,][0-9]{3})*(?:[\.,][0-9]+)?)\s*€\s+de\s+charges', combined_text, re.IGNORECASE)
        if m:
            charges = parse_amount(m.group(1))
            charges_snip = combined_text[max(0, m.start()-50):min(len(combined_text), m.end()+100)]
        else:
            # Pattern 3: "charges locatives", "charges mensuel", "charge de copropriété" (longer keyword searches)
            for kw in ["charges locatives", "charges mensuel", "charge de copropriété", "charges annuelles"]:
                charges, charges_snip = parse_amounts_near_keyword(combined_text, kw, strict=True)
                if charges is not None:
                    break
    
    charges_period = detect_period_from_snippet(charges_snip or "")

    monthly_charges = None
    if charges is not None:
        if charges_period == "annual":
            monthly_charges = charges / 12.0
        else:
            monthly_charges = charges

    taxe_annual = None
    if taxe is not None:
        if taxe_period == "monthly":
            taxe_annual = taxe * 12.0
        else:
            taxe_annual = taxe

    # compute rents
    annual_rent = monthly_rent * 12.0 if monthly_rent is not None else None
    annual_charges = monthly_charges * 12.0 if monthly_charges is not None else None

    gross_yield = None
    net_yield = None
    if price and annual_rent:
        try:
            gross_yield = (annual_rent / price) * 100.0
            
            # Sanity check: if yield > 20%, the detected loyer is probably the sale price, not rental
            # (normal rental yields are 3-10%, anything >20% is unrealistic)
            if gross_yield > 20.0:
                # Reject this loyer detection as it's likely a false positive
                annual_rent = None
                monthly_rent = None
                gross_yield = None
            else:
                if annual_charges is None:
                    annual_charges = 0.0
                if taxe_annual is None:
                    taxe_annual = 0.0
                net_yield = ((annual_rent - annual_charges - taxe_annual) / price) * 100.0
        except Exception:
            pass

    if gross_yield is not None:
        gross_yield = round(gross_yield, 2)
    if net_yield is not None:
        net_yield = round(net_yield, 2)

    # Round all numeric values to 2 decimal places
    if price is not None:
        price = round(price, 2)
    if monthly_rent is not None:
        monthly_rent = round(monthly_rent, 2)
    if annual_rent is not None:
        annual_rent = round(annual_rent, 2)
    if monthly_charges is not None:
        monthly_charges = round(monthly_charges, 2)
    if annual_charges is not None:
        annual_charges = round(annual_charges, 2)
    if taxe_annual is not None:
        taxe_annual = round(taxe_annual, 2)

    return {
        "url": url,
        "title": title,
        "price": price,
        "monthly_rent": monthly_rent,
        "annual_rent": annual_rent,
        "monthly_charges": monthly_charges,
        "annual_charges": annual_charges,
        "taxe_fonciere_annual": taxe_annual,
        "gross_yield_pct": gross_yield,
        "net_yield_pct": net_yield,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="Nantes", help="City or location for search (default: Nantes)")
    ap.add_argument("--query", default="loyer", help="Search query (default: loyer)")
    ap.add_argument("--pages", type=int, default=2, help="Number of search result pages to scan")
    ap.add_argument("--search-url", default=None, help="Full search URL to use instead of building one")
    ap.add_argument("--out", default="results.csv", help="CSV output file (default: results.csv)")
    ap.add_argument("--delay", type=float, default=1.0, help="Delay between requests in seconds")
    ap.add_argument("--use-playwright", action="store_true", help="Use Playwright to render pages (requires Playwright) ")
    ap.add_argument("--max-ads", type=int, default=None, help="Maximum number of ads to parse (default: all)")
    ap.add_argument("--save-html", default=None, help="Directory to save fetched HTML for debugging")
    ap.add_argument("--proxy", default=None, help="Optional proxy URL (http://user:pass@host:port)")
    args = ap.parse_args()

    session = requests.Session()
    # perform an initial request to the homepage to obtain cookies and reduce bot detection
    try:
        session.get("https://www.leboncoin.fr/", headers=HEADERS, timeout=10)
    except Exception:
        pass

    ad_urls = []
    if args.search_url:
        for p in range(1, args.pages + 1):
            url = args.search_url
            if "page=" in url:
                # naive replace
                url = re.sub(r"page=\d+", f"page={p}", url)
            else:
                url = url + ("&" if "?" in url else "?") + f"page={p}"
            print(f"Fetching search page: {url}")
            try:
                save_path = None
                if args.save_html:
                    os.makedirs(args.save_html, exist_ok=True)
                    save_path = os.path.join(args.save_html, f"search_page_{p}.html")
                html = fetch(url, session=session, playwright_render=args.use_playwright, save_to=save_path, proxy=args.proxy)
            except Exception as e:
                print(f"Error fetching {url}: {e}")
                continue
            new_links = extract_ad_links_from_search(html)
            print(f"Found {len(new_links)} links on page {p}")
            ad_urls.extend(new_links)
            time.sleep(args.delay)
    else:
        for p in range(1, args.pages + 1):
            url = build_search_url(args.city, args.query, page=p)
            print(f"Fetching search page: {url}")
            try:
                save_path = None
                if args.save_html:
                    os.makedirs(args.save_html, exist_ok=True)
                    save_path = os.path.join(args.save_html, f"search_page_{p}.html")
                html = fetch(url, session=session, playwright_render=args.use_playwright, save_to=save_path, proxy=args.proxy)
            except Exception as e:
                print(f"Error fetching {url}: {e}")
                continue
            new_links = extract_ad_links_from_search(html)
            print(f"Found {len(new_links)} links on page {p}")
            ad_urls.extend(new_links)
            time.sleep(args.delay)

    # dedupe while preserving order
    seen = set()
    ad_urls_filtered = []
    for u in ad_urls:
        if u not in seen:
            seen.add(u)
            ad_urls_filtered.append(u)

    print(f"Total unique ads to parse: {len(ad_urls_filtered)}")

    if args.max_ads:
        ad_urls_filtered = ad_urls_filtered[:args.max_ads]
        print(f"Limited to {len(ad_urls_filtered)} ads for debugging")

    rows = []
    for i, u in enumerate(ad_urls_filtered, 1):
        print(f"[{i}/{len(ad_urls_filtered)}] Parsing {u}")
        try:
            save_path = None
            if args.save_html:
                os.makedirs(args.save_html, exist_ok=True)
                save_path = os.path.join(args.save_html, f"ad_{i}.html")
            row = parse_ad_page(u, session=session, playwright_render=args.use_playwright, save_to=save_path, proxy=args.proxy)
            rows.append(row)
        except Exception as e:
            print(f"Failed to parse {u}: {e}")
        time.sleep(args.delay)

    if not rows:
        print("No data parsed. Exiting.")
        sys.exit(1)

    df = pd.DataFrame(rows)
    df.to_csv(args.out, index=False, sep=';')
    print(f"Saved {len(df)} rows to {args.out}")
    
    # Print summary statistics
    print("\n" + "="*80)
    print(f"RÉSUMÉ - Extraction LeBonCoin Nantes (loyer)")
    print("="*80)
    
    print(f"\n📊 STATISTIQUES GÉNÉRALES:")
    print(f"  • Total annonces extraites: {len(df)}")
    print(f"  • Avec prix: {len(df[df['price'].notna()])}")
    print(f"  • Avec loyer: {len(df[df['monthly_rent'].notna()])}")
    print(f"  • Avec charges: {len(df[df['monthly_charges'].notna()])}")
    print(f"  • Avec rendement brut: {len(df[df['gross_yield_pct'].notna()])}")
    
    # Rent statistics
    df_with_rent = df[df['monthly_rent'].notna()]
    if len(df_with_rent) > 0:
        print(f"\n💰 LOYER MENSUEL:")
        print(f"  • Min: {df_with_rent['monthly_rent'].min():.2f}€")
        print(f"  • Max: {df_with_rent['monthly_rent'].max():.2f}€")
        print(f"  • Moyen: {df_with_rent['monthly_rent'].mean():.2f}€")
    
    # Yield statistics
    df_with_yield = df[df['gross_yield_pct'].notna()]
    if len(df_with_yield) > 0:
        print(f"\n📈 RENDEMENT BRUT:")
        print(f"  • Min: {df_with_yield['gross_yield_pct'].min():.2f}%")
        print(f"  • Max: {df_with_yield['gross_yield_pct'].max():.2f}%")
        print(f"  • Moyen: {df_with_yield['gross_yield_pct'].mean():.2f}%")
    
    # Top 10 yields
    print(f"\n🏆 TOP 10 MEILLEURS RENDEMENTS BRUTS:")
    top = df[df['gross_yield_pct'].notna()].nlargest(10, 'gross_yield_pct')
    for i, (idx, row) in enumerate(top.iterrows(), 1):
        title = row['title'][:40]
        print(f"  {i:2}. {title:40} | Prix: {row['price']:>9.0f}€ | Loyer: {row['monthly_rent']:>6.0f}€/m | Rendement: {row['gross_yield_pct']:>6.2f}% | {row['url']}")
    
    print("\n" + "="*80)
    print(f"✅ Fichier sauvegardé: {args.out}")
    print("="*80)


if __name__ == "__main__":
    main()

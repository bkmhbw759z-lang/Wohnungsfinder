"""Generischer Parser für Portale ohne bekannte API: findet Inserat-Links samt Preis/PLZ im Kartentext."""
import re, urllib.request
from urllib.parse import urljoin
from bs4 import BeautifulSoup

SOURCES = {  # Name: [URLs]; bei Fehlern zeigt die App den Status, dann URL anpassen
    "immowelt":    ["https://www.immowelt.at/liste/wien/wohnungen/mieten?pma=650&sort=createdAt%2Bdesc"],
    "derstandard": ["https://immobilien.derstandard.at/suche/wien/mieten-wohnung?preis=-650"],
    "immoscout24": ["https://www.immobilienscout24.at/regional/wien/wien/wohnung-mieten"],
    "findmyhome":  ["https://www.findmyhome.at/wohnung-mieten/wien"],
    "wohnnet":     ["https://www.wohnnet.at/immobilien/mietwohnungen/wien"],
    "immodirekt":  ["https://www.immodirekt.at/mieten/wohnung/wien"],
    "immobilien.net": ["https://www.immobilien.net/mietwohnungen/wien"],
    "remax":       ["https://www.remax.at/de/immobilien/mieten/wohnung/wien"],
}
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Accept-Language": "de-AT,de;q=0.9"}
PRICE = re.compile(r"(?:€\s*|EUR\s*)(\d{1,4}(?:\.\d{3})*(?:,\d{1,2})?)|(\d{1,4}(?:\.\d{3})*(?:,\d{1,2})?)\s*(?:€|EUR)")
PLZ = re.compile(r"\b(1[0-2]\d0)\b")
ROOMS = re.compile(r"(\d(?:,5)?)\s*(?:Zimmer|Zi\b|-Zimmer)", re.I)
SIZE = re.compile(r"(\d{2,3}(?:,\d+)?)\s*m²")

def f(s): return float(s.replace(".", "").replace(",", ".")) if s else None

def scrape(name, url):
    html = urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=30).read().decode("utf-8", "ignore")
    soup, out, seen = BeautifulSoup(html, "html.parser"), [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if href in seen or href.rstrip("/") == url.rstrip("/"): continue
        card = a
        for _ in range(5):                       # bis zum Kartencontainer hochgehen
            t = card.get_text(" ", strip=True)
            if PRICE.search(t) and PLZ.search(t): break
            if card.parent is None: break
            card = card.parent
        t = card.get_text(" ", strip=True)
        pm, zm = PRICE.search(t), PLZ.search(t)
        if not (pm and zm) or len(t) > 900 or len(PRICE.findall(t)) > 1: continue
        price = f(pm.group(1) or pm.group(2))
        if not price or price < 150: continue
        seen.add(href)
        r, s = ROOMS.search(t), SIZE.search(t)
        img = card.find("img")
        title = (a.get_text(" ", strip=True) or t)[:110]
        out.append({"id": f"{name}:{href}", "title": title, "price": price,
                    "rooms": f(r.group(1)) if r else None, "size": f(s.group(1)) if s else None,
                    "plz": zm.group(1), "location": name, "url": href, "text": t,
                    "img": urljoin(url, img.get("src") or img.get("data-src") or "") if img else ""})
    return out

"""Wohnungsfinder WU Wien: holt willhaben-Mietwohnungen, filtert, schreibt listings.json."""
import json, os, re, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

MAX_PRICE = 650                      # Gesamtmiete inkl. BK
MIN_ROOMS = 1
PLZ = {"1010", "1020", "1030", "1040", "1050", "1060", "1070", "1080", "1090", "1200", "1220"}
# Näher an der WU = höherer Score
PLZ_SCORE = {"1020": 4, "1030": 3, "1090": 3, "1200": 3, "1010": 2, "1080": 2,
             "1040": 2, "1060": 1, "1070": 1, "1050": 1, "1220": 1}
RESERVED = re.compile(r"(?<!rechte )reserviert|(?<!nicht )\bvermietet\b|anfrage-?stopp|nicht mehr verfügbar|"
                      r"bereits vergeben|derzeit keine anfragen|inserat (ist )?(abgelaufen|inaktiv)|nicht mehr online", re.I)
BAD_TEXT = re.compile(RESERVED.pattern + r"|wohn-?ticket|wiener wohnen|gemeindewohnung|gemeindebau|smart-?wohnung|"
                      r"\bwg\b|wohngemeinschaft|mitbewohner|zimmer in (einer|der) wohnung|"
                      r"untermiete|nur für studenten.*wg", re.I)
OUT = "listings.json"
BASE = "https://www.willhaben.at"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept-Language": "de-AT,de;q=0.9"}

def fetch_page(page):
    q = urllib.parse.urlencode({"areaId": 900, "PRICE_TO": MAX_PRICE, "rows": 90,
                                "sort": 1, "page": page})
    url = f"{BASE}/iad/immobilien/mietwohnungen/mietwohnung-angebote?{q}"
    html = urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30).read().decode()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    data = json.loads(m.group(1))
    return data["props"]["pageProps"]["searchResult"]["advertSummaryList"]["advertSummary"]

def attr(ad, *names):
    for a in ad.get("attributes", {}).get("attribute", []):
        if a["name"] in names and a.get("values"):
            return a["values"][0]
    return None

def num(s):
    try: return float(str(s).replace(",", "."))
    except (TypeError, ValueError): return None

def parse(ad):
    st = (ad.get("advertStatus") or {}).get("id")
    if st and st != "active": return None          # reserviert/inaktiv laut willhaben
    plz = str(attr(ad, "POSTCODE") or "")
    price = num(attr(ad, "RENT/PER_MONTH_LETTINGS", "PRICE"))
    rooms = num(attr(ad, "NUMBER_OF_ROOMS"))
    size = num(attr(ad, "ESTATE_SIZE/LIVING_AREA", "ESTATE_SIZE"))
    title = attr(ad, "HEADING") or ad.get("description", "")
    text = f"{title} {attr(ad, 'BODY_DYN') or ''}"
    if plz not in PLZ or not price or price > MAX_PRICE: return None
    if rooms is not None and rooms < MIN_ROOMS: return None
    if BAD_TEXT.search(text): return None
    seo = attr(ad, "SEO_URL")
    img = attr(ad, "MMO") or ""
    score = PLZ_SCORE.get(plz, 0) + (3 if rooms and rooms >= 2 else 0)
    warn = bool(size and price / size < 7)   # verdächtig günstig
    return {"id": str(ad["id"]), "title": title, "price": price, "rooms": rooms, "size": size,
            "plz": plz, "location": attr(ad, "LOCATION") or "", "score": score, "warn": warn,
            "url": f"{BASE}/iad/{seo}" if seo else f"{BASE}/iad/object?adId={ad['id']}",
            "img": f"https://cache.willhaben.at/mmo/{img}" if img else ""}

def finish(l, source):
    """Gemeinsame Filter/Score für generische Quellen."""
    if l["plz"] not in PLZ or l["price"] > MAX_PRICE: return None
    if l["rooms"] is not None and l["rooms"] < MIN_ROOMS: return None
    if BAD_TEXT.search(l.pop("text", "") + " " + l["title"]): return None
    l["score"] = PLZ_SCORE.get(l["plz"], 0) + (3 if l["rooms"] and l["rooms"] >= 2 else 0)
    l["warn"] = bool(l["size"] and l["price"] / l["size"] < 7)
    l["source"] = source
    return l

def verify(l):
    """False, wenn Inserat gelöscht (404) oder als reserviert/vermietet markiert ist."""
    try:
        html = urllib.request.urlopen(urllib.request.Request(l["url"], headers=HEADERS), timeout=25).read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code not in (404, 410)
    except Exception:
        return True
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "footer"]): t.decompose()
    return not RESERVED.search(soup.get_text(" ", strip=True)[:3000])

def notify(new):
    tok, chat = os.getenv("TG_TOKEN"), os.getenv("TG_CHAT")
    if not (tok and chat): return
    for l in new[:10]:
        msg = f"🏠 {l['title']}\n€{l['price']:.0f} · {l['rooms'] or '?'} Zi · {l['size'] or '?'} m² · {l['plz']}\n{l['url']}"
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=20)

def main():
    old = {}
    if os.path.exists(OUT):
        old = {l["id"]: l for l in json.load(open(OUT)).get("listings", [])}
    dead = set()
    if os.path.exists(OUT): dead = set(json.load(open(OUT)).get("dead", []))
    found, status = {}, {}
    for p in (1, 2, 3):
        try: ads = fetch_page(p)
        except Exception as e:
            status["willhaben"] = f"Fehler: {str(e)[:60]}"; print("willhaben", p, e); break
        for ad in ads:
            l = parse(ad)
            if l: l["source"] = "willhaben"; found[l["id"]] = l
        status["willhaben"] = sum(1 for l in found.values() if l["source"] == "willhaben")
        time.sleep(2)
    import generic
    seen_keys = {(l["plz"], l["price"], l["size"]) for l in found.values() if l["size"]}
    for name, urls in generic.SOURCES.items():
        n = 0
        for u in urls:
            try:
                for l in generic.scrape(name, u):
                    l = finish(l, name)
                    if not l: continue
                    k = (l["plz"], l["price"], l["size"])
                    if l["size"] and k in seen_keys: continue   # gleiche Wohnung schon von anderem Portal
                    seen_keys.add(k); found[l["id"]] = l; n += 1
            except Exception as e:
                status[name] = f"Fehler: {str(e)[:60]}"; print(name, e); break
            time.sleep(2)
        else: status[name] = n
    if not found and not old:
        print("Keine Treffer / Parser prüfen"); return
    now = datetime.now(timezone.utc).isoformat()
    for i in list(found):
        if i in dead: del found[i]
        elif i in old: found[i]["checked"] = old[i].get("checked", "")
    # Detailseiten prüfen (25 pro Lauf, neue und am längsten ungeprüfte zuerst)
    for l in sorted(found.values(), key=lambda x: x.get("checked", ""))[:25]:
        if verify(l): l["checked"] = now
        else: dead.add(l["id"]); del found[l["id"]]
        time.sleep(1)
    new = []
    for i, l in found.items():
        l["first_seen"] = old.get(i, {}).get("first_seen", now)
        if i not in old: new.append(l)
    notify(new)
    json.dump({"updated": now, "sources": status, "dead": sorted(dead)[-3000:], "listings": list(found.values())}, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(len(found), "Treffer,", len(new), "neu")

if __name__ == "__main__":
    main()


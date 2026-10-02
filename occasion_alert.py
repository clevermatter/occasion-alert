"""Occasion-alert: zoekt op AutoScout24, Gaspedaal (en optioneel Marktplaats)
naar occasions en meldt nieuwe advertenties en prijsdalingen via Telegram.

Dezelfde auto op meerdere sites (zelfde kilometerstand + bouwjaar) wordt
herkend en maar één keer gemeld, met de links naar alle sites.

    python occasion_alert.py --dry-run         # toont berichten, verstuurt niets
    python occasion_alert.py --test-telegram   # stuurt één testbericht

Alleen standaardbibliotheek, dus geen pip install nodig.
"""

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config.json"
STATE_FILE = BASE / "state.json"
MELD_FOUT_NA = 3  # waarschuw via Telegram als een bron zo vaak achter elkaar faalt

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.5",
}


def stad(naam):
    """'`S-HERTOGENBOSCH' -> "'s-Hertogenbosch", 'VENLO' -> 'Venlo'."""
    naam = (naam or "").replace("`", "'").title()
    return re.sub(r"^'S-", "'s-", naam)


def haal(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def getal(waarde):
    if isinstance(waarde, (int, float)):
        return int(waarde)
    cijfers = re.sub(r"[^\d]", "", str(waarde or ""))
    return int(cijfers) if cijfers else None


def advertentie(bron, id_, titel, prijs, bouwjaar, km, plaats, afstand_km, url, extra=""):
    return {
        "bron": bron,
        "id": f"{bron}:{id_}",
        "titel": " ".join((titel or "").split()),
        "prijs": getal(prijs) or 0,
        "bouwjaar": getal(bouwjaar),
        "km": getal(km),
        "plaats": (plaats or "").strip(),
        "afstand_km": afstand_km,
        "url": url,
        "zoektekst": f"{titel} {extra}".lower(),
    }


# ----------------------------------------------------------------- AutoScout24

def autoscout24(cfg):
    b = cfg["autoscout24"]
    params = {
        "atype": "C",
        "cy": "NL",
        "fuel": b.get("brandstof", ""),
        "priceto": cfg["max_prijs_euro"],
        "zip": cfg["postcode"],
        "zipr": cfg["straal_km"],
        "kmto": cfg.get("max_kilometerstand") or "",
        "sort": "age",
        "desc": 1,
    }
    url = (
        f"https://www.autoscout24.nl/lst/{b['merk']}/{b['model']}?"
        + urllib.parse.urlencode({k: v for k, v in params.items() if v != ""})
    )
    pagina = haal(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', pagina, re.S)
    if not m:
        raise RuntimeError("AutoScout24: geen __NEXT_DATA__ in de pagina (geblokkeerd of nieuw formaat)")
    listings = json.loads(m.group(1))["props"]["pageProps"]["listings"]

    ads = []
    for l in listings:
        v, t = l.get("vehicle", {}), l.get("tracking", {})
        loc, prijs = l.get("location", {}), l.get("price", {})
        eerste_reg = t.get("firstRegistration") or ""  # "01-2022"
        ads.append(
            advertentie(
                "AutoScout24",
                l["id"],
                f"{v.get('make', '')} {v.get('model', '')} {v.get('modelVersionInput') or ''}",
                prijs.get("priceRaw") or t.get("price"),
                eerste_reg[-4:] if eerste_reg else None,
                t.get("mileage") or v.get("mileageInKm"),
                stad(loc.get("city")),
                loc.get("distanceToSearchLocationInKm"),
                "https://www.autoscout24.nl" + l.get("url", ""),
                extra=v.get("fuel", ""),
            )
        )
    return ads


# ------------------------------------------------------------------- Gaspedaal

def gaspedaal(cfg):
    b = cfg["gaspedaal"]
    params = {
        "trefw": b.get("trefwoord", ""),
        "pmax": cfg["max_prijs_euro"],
        "kmax": cfg.get("max_kilometerstand") or "",
        "pc": cfg["postcode"],
        "strl": cfg["straal_km"],
        "srt": "dt-d",  # nieuwste eerst
    }
    zoek_url = f"https://www.gaspedaal.nl/{b['pad']}?" + urllib.parse.urlencode(
        {k: v for k, v in params.items() if v != ""}
    )
    pagina = haal(zoek_url)
    lijst = None
    for blok in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', pagina, re.S):
        try:
            data = json.loads(blok)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            lijst = data
            break
    if lijst is None:
        raise RuntimeError("Gaspedaal: geen advertentielijst in de pagina (geblokkeerd of nieuw formaat)")

    ads = []
    for element in lijst.get("itemListElement", []):
        item = element.get("item", {})
        id_ = item.get("@id", "").split("#")[-1]
        offer = item.get("offers", {})
        adres = (offer.get("seller") or {}).get("address", {})
        ads.append(
            advertentie(
                "Gaspedaal",
                id_,
                item.get("name"),
                offer.get("price"),
                item.get("productionDate") or item.get("vehicleModelDate"),
                (item.get("mileageFromOdometer") or {}).get("value"),
                adres.get("addressLocality"),
                None,
                f"{zoek_url}#{id_}",
                extra=item.get("fuelType", ""),
            )
        )
    return ads


# ----------------------------------------------------------------- Marktplaats

def marktplaats(cfg):
    ads = []
    for term in cfg["marktplaats"]["zoektermen"]:
        params = [
            ("l1CategoryId", 91),
            ("limit", 100),
            ("offset", 0),
            ("query", term),
            ("searchInTitleAndDescription", "true"),
            ("postcode", cfg["postcode"]),
            ("distanceMeters", int(cfg["straal_km"]) * 1000),
            ("attributeRanges[]", f"PriceCents:null:{int(cfg['max_prijs_euro']) * 100}"),
            ("sortBy", "SORT_INDEX"),
            ("sortOrder", "DECREASING"),
        ]
        data = json.loads(haal("https://www.marktplaats.nl/lrp/api/search?" + urllib.parse.urlencode(params)))
        for l in data["listings"]:
            attrs = {a.get("key"): a.get("value") for a in l.get("attributes") or []}
            loc = l.get("location") or {}
            vip = l.get("vipUrl") or ""
            ads.append(
                advertentie(
                    "Marktplaats",
                    l.get("itemId"),
                    l.get("title"),
                    round(((l.get("priceInfo") or {}).get("priceCents") or 0) / 100),
                    attrs.get("constructionYear"),
                    attrs.get("mileage"),
                    loc.get("cityName"),
                    round(loc["distanceMeters"] / 1000) if loc.get("distanceMeters") else None,
                    vip if vip.startswith("http") else "https://www.marktplaats.nl" + vip,
                    extra=f"{l.get('description', '')} {' '.join(map(str, attrs.values()))}",
                )
            )
        time.sleep(2)
    return ads


BRONNEN = {  # config-sleutel: (weergavenaam, functie)
    "autoscout24": ("AutoScout24", autoscout24),
    "gaspedaal": ("Gaspedaal", gaspedaal),
    "marktplaats": ("Marktplaats", marktplaats),
}


# --------------------------------------------------------------- filteren/samenvoegen

def voldoet(ad, cfg):
    titel = ad["titel"].lower()
    if not all(w in titel for w in cfg.get("titel_moet_bevatten", [])):
        return False
    if not any(w in ad["zoektekst"] for w in cfg.get("moet_een_van_bevatten", [])):
        return False
    if any(w in titel for w in cfg.get("uitsluiten", [])):
        return False
    if not (cfg.get("min_prijs_euro", 0) <= ad["prijs"] <= cfg["max_prijs_euro"]):
        return False
    if cfg.get("min_bouwjaar") and ad["bouwjaar"] and ad["bouwjaar"] < cfg["min_bouwjaar"]:
        return False
    if cfg.get("max_kilometerstand") and ad["km"] and ad["km"] > cfg["max_kilometerstand"]:
        return False
    return True


def auto_sleutel(ad):
    """Zelfde kilometerstand + bouwjaar = vrijwel zeker dezelfde auto."""
    if ad["km"] and ad["km"] > 100 and ad["bouwjaar"]:
        return f"auto:{ad['km']}-{ad['bouwjaar']}"
    return ad["id"]


def voeg_samen(ads):
    autos = {}
    for ad in ads:
        sleutel = auto_sleutel(ad)
        auto = autos.get(sleutel)
        if auto is None:
            autos[sleutel] = {**ad, "sleutel": sleutel, "links": {ad["bron"]: ad["url"]}}
            continue
        auto["links"].setdefault(ad["bron"], ad["url"])
        if ad["afstand_km"] is not None and auto["afstand_km"] is None:
            auto["afstand_km"] = ad["afstand_km"]
        if ad["prijs"] < auto["prijs"]:  # laagste prijs leidend
            auto.update(prijs=ad["prijs"], titel=ad["titel"])
    return autos


# -------------------------------------------------------------------- Telegram

def euro(bedrag):
    return "€" + f"{bedrag:,}".replace(",", ".")


def details(auto):
    delen = [euro(auto["prijs"])]
    if auto["bouwjaar"]:
        delen.append(str(auto["bouwjaar"]))
    if auto["km"]:
        delen.append(f"{auto['km']:,} km".replace(",", "."))
    return " · ".join(delen)


def plaats(auto):
    p = html.escape(auto["plaats"] or "?", quote=False)
    return f"{p} ({auto['afstand_km']} km)" if auto["afstand_km"] is not None else p


def links(auto):
    return " | ".join(f'<a href="{html.escape(u)}">{b}</a>' for b, u in auto["links"].items())


def bericht_nieuw(auto, naam):
    return (
        f"🚗 <b>Nieuwe {html.escape(naam)}</b>\n"
        f"{html.escape(auto['titel'], quote=False)}\n"
        f"💶 {details(auto)}\n"
        f"📍 {plaats(auto)}\n"
        f"🔗 {links(auto)}"
    )


def bericht_prijsdaling(auto, oude_prijs):
    return (
        f"📉 <b>Prijs verlaagd met {euro(oude_prijs - auto['prijs'])}</b>\n"
        f"{html.escape(auto['titel'], quote=False)}\n"
        f"💶 <s>{euro(oude_prijs)}</s> → <b>{details(auto)}</b>\n"
        f"📍 {plaats(auto)}\n"
        f"🔗 {links(auto)}"
    )


def berichten_overzicht(autos, naam, bronnen):
    kop = (
        f"✅ <b>Occasion-alert actief: {html.escape(naam)}</b>\n"
        f"Bronnen: {', '.join(bronnen)}\n"
        f"Nu {len(autos)} auto('s) te koop. Vanaf nu meld ik alleen nieuwe "
        f"advertenties en prijsdalingen.\n"
    )
    regels = [
        f"• {details(a)} — {plaats(a)} — {links(a)}"
        for a in sorted(autos, key=lambda a: a["prijs"])
    ]
    berichten, huidig = [], kop
    for r in regels:
        if len(huidig) + len(r) > 4000:
            berichten.append(huidig)
            huidig = ""
        huidig += "\n" + r
    berichten.append(huidig)
    return berichten


def stuur(tekst, dry_run=False):
    if dry_run:
        print("----- [dry-run] -----\n" + tekst)
        return
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    for chat_id in [c.strip() for c in os.environ["TELEGRAM_CHAT_ID"].split(",") if c.strip()]:
        body = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": tekst, "parse_mode": "HTML", "disable_web_page_preview": "true"}
        ).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
        with urllib.request.urlopen(req, timeout=30) as resp:
            if json.load(resp).get("ok") is not True:
                raise RuntimeError("Telegram weigerde het bericht")
        time.sleep(1)


# ------------------------------------------------------------------------ main

def main():
    dry_run = "--dry-run" in sys.argv
    if "--test-telegram" in sys.argv:
        stuur("👋 Testbericht van je occasion-alert. De verbinding werkt!")
        return

    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    eerste_run = not STATE_FILE.exists()
    state = {} if eerste_run else json.loads(STATE_FILE.read_text(encoding="utf-8"))
    gezien = state.setdefault("autos", {})
    fouten = state.setdefault("fouten", {})
    ooit_gelukt = set(state.get("bronnen_ooit_gelukt", []))

    alle_ads, gelukt, mislukt = [], [], []
    for sleutel, (naam, functie) in BRONNEN.items():
        if not cfg.get(sleutel, {}).get("aan"):
            continue
        try:
            ads = functie(cfg)
            passend = [a for a in ads if voldoet(a, cfg)]
            print(f"{naam}: {len(ads)} resultaten, {len(passend)} passend")
            alle_ads += passend
            gelukt.append(naam)
            fouten[sleutel] = 0
        except Exception as e:  # één kapotte bron mag de rest niet tegenhouden
            print(f"::warning::{naam} mislukt: {e}")
            mislukt.append(naam)
            fouten[sleutel] = fouten.get(sleutel, 0) + 1
            if fouten[sleutel] == MELD_FOUT_NA:
                stuur(
                    f"⚠️ {naam} lukt al {MELD_FOUT_NA} keer achter elkaar niet.\n"
                    f"<code>{html.escape(str(e))[:300]}</code>",
                    dry_run,
                )

    if not gelukt:
        raise SystemExit("Alle bronnen zijn mislukt")

    autos = voeg_samen(alle_ads)
    print(f"{len(autos)} unieke auto('s)")

    if eerste_run:
        for tekst in berichten_overzicht(list(autos.values()), cfg["naam"], gelukt):
            stuur(tekst, dry_run)
    else:
        # Een bron die voor het eerst werkt (net aangezet of eerder steeds mislukt)
        # zou anders al zijn bestaande aanbod als "nieuw" melden.
        stil = set(gelukt) - ooit_gelukt
        for auto in sorted(autos.values(), key=lambda a: a["prijs"]):
            bekend = gezien.get(auto["sleutel"])
            if bekend is None:
                if not set(auto["links"]) <= stil:
                    stuur(bericht_nieuw(auto, cfg["naam"]), dry_run)
            elif auto["prijs"] < bekend["prijs"]:
                stuur(bericht_prijsdaling(auto, bekend["prijs"]), dry_run)

    vandaag = date.today().isoformat()
    for auto in autos.values():
        oud = gezien.get(auto["sleutel"], {})
        prijs = auto["prijs"]
        if mislukt and oud:  # bron tijdelijk weg: onthoud de laagst bekende prijs
            prijs = min(prijs, oud["prijs"])
        gezien[auto["sleutel"]] = {
            "prijs": prijs,
            "titel": auto["titel"],
            "eerst_gezien": oud.get("eerst_gezien", vandaag),
        }
    state["bronnen_ooit_gelukt"] = sorted(ooit_gelukt | set(gelukt))

    if not dry_run:
        STATE_FILE.write_text(
            json.dumps(state, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
    if mislukt:
        print(f"::warning::Mislukte bronnen deze run: {', '.join(mislukt)}")


if __name__ == "__main__":
    main()

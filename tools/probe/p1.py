"""Sonde : disponibilite des tickers Yahoo, flux RSS du FT, calendrier economique."""
import re
import xml.etree.ElementTree as ET

import requests
import yfinance as yf

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"}

print("##### Yahoo Finance")
T = {"S&P 500": "^GSPC", "Nasdaq": "^IXIC", "CAC 40": "^FCHI", "DAX": "^GDAXI", "Nikkei": "^N225", "Euro Stoxx 50": "^STOXX50E", "FTSE": "^FTSE", "Hang Seng": "^HSI",
     "VIX": "^VIX", "EURUSD": "EURUSD=X", "DXY": "DX-Y.NYB", "USDJPY": "JPY=X", "GBPUSD": "GBPUSD=X", "Or": "GC=F", "Argent": "SI=F", "WTI": "CL=F", "Brent": "BZ=F",
     "Cuivre": "HG=F", "Gaz TTF": "TTF=F", "US 10 ans": "^TNX", "US 5 ans": "^FVX", "US 3 mois": "^IRX", "US 30 ans": "^TYX", "HYG": "HYG", "TLT": "TLT", "Bund fut": "FGBL=F"}
for name, tk in T.items():
    try:
        h = yf.Ticker(tk).history(period="1y")
        if h.empty:
            print(f"{name:<14}{tk:<12} VIDE")
            continue
        c = h["Close"]
        print(f"{name:<14}{tk:<12} n={len(h):>3} dernier={c.iloc[-1]:>10.3f} veille={(c.iloc[-1]/c.iloc[-2]-1)*100:+.2f}% 1m={(c.iloc[-1]/c.iloc[-22]-1)*100 if len(c)>22 else float('nan'):+.1f}% date={h.index[-1].date()}")
    except Exception as e:
        print(f"{name:<14}{tk:<12} ERREUR {type(e).__name__} {str(e)[:60]}")

print("\n##### FT RSS")
FEEDS = ["https://www.ft.com/rss/home", "https://www.ft.com/markets?format=rss", "https://www.ft.com/global-economy?format=rss", "https://www.ft.com/companies?format=rss",
         "https://www.ft.com/world?format=rss", "https://www.ft.com/opinion?format=rss", "https://www.ft.com/lex?format=rss", "https://www.ft.com/alphaville?format=rss",
         "https://www.ft.com/technology?format=rss", "https://www.ft.com/?format=rss"]
for u in FEEDS:
    try:
        r = requests.get(u, headers=UA, timeout=25)
        items = []
        if r.ok and "<item" in r.text:
            root = ET.fromstring(r.content)
            for it in root.iter("item"):
                items.append((it.findtext("title"), (it.findtext("description") or "")[:110], it.findtext("pubDate"), it.findtext("link")))
        print(r.status_code, u, len(r.text), "items:", len(items))
        for t, d, p, l in items[:2]:
            print("    -", t, "|", p, "|", re.sub(r"\s+", " ", d))
    except Exception as e:
        print("ERR", u, type(e).__name__, str(e)[:80])

print("\n##### Calendrier economique")
for u in ["https://nfs.faireconomy.media/ff_calendar_thisweek.json"]:
    try:
        r = requests.get(u, headers=UA, timeout=25)
        print(r.status_code, u, len(r.text), r.text[:300])
        if r.ok:
            j = r.json()
            print("evenements:", len(j), "impact:", sorted({x.get("impact") for x in j}), "pays:", sorted({x.get("country") for x in j}))
            print([ (x["date"], x["country"], x["title"], x["impact"], x.get("forecast"), x.get("previous")) for x in j if x["impact"] == "High"][:6])
    except Exception as e:
        print("ERR", u, type(e).__name__, str(e)[:80])
print("FIN")

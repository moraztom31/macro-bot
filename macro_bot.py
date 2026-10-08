"""
Briefing macro quotidien envoyé sur Telegram.

Contenu : tonalité du marché, mouvements inhabituels (mesurés en écarts-types), tableau
actions / taux / changes / matières premières / volatilité / crypto avec variations
1 jour, 1 semaine et 1 mois, lecture croisée des marchés, calendrier économique du jour
et sélection des articles du Financial Times les plus utiles à lire.

Aucune clé d'API payante : Yahoo Finance (yfinance), flux RSS publics du FT (titres et
résumés), calendrier économique public.
"""

import html
import os
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

PARIS = ZoneInfo("Europe/Paris")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

SEND_FROM_HOUR = 7      # on n'envoie jamais avant 7h (Paris)
SEND_UNTIL_HOUR = 22    # ... ni après 22h
SEND_WEEKENDS = False   # samedi/dimanche : marchés fermés, rien de nouveau

# ---------------------------------------------------------------------------
# Actifs suivis : (nom affiché, ticker Yahoo, type de format)
# types : idx, fut, yield, fx4, fx2, cmd, vix, etf, crypto
# ---------------------------------------------------------------------------
GROUPS = [
    ("📈 Actions", [("S&P 500", "^GSPC", "idx"), ("Nasdaq", "^IXIC", "idx"), ("Euro Stoxx 50", "^STOXX50E", "idx"), ("CAC 40", "^FCHI", "idx"),
                    ("DAX", "^GDAXI", "idx"), ("FTSE 100", "^FTSE", "idx"), ("Nikkei 225", "^N225", "idx"), ("Hang Seng", "^HSI", "idx")]),
    ("🔮 Futures", [("S&P fut.", "ES=F", "fut"), ("Nasdaq fut.", "NQ=F", "fut")]),
    ("🏦 Taux US", [("US 3 mois", "^IRX", "yield"), ("US 5 ans", "^FVX", "yield"), ("US 10 ans", "^TNX", "yield"), ("US 30 ans", "^TYX", "yield")]),
    ("💱 Changes", [("EUR/USD", "EURUSD=X", "fx4"), ("USD/JPY", "JPY=X", "fx2"), ("GBP/USD", "GBPUSD=X", "fx4"), ("Dollar Index", "DX-Y.NYB", "fx2")]),
    ("🛢️ Matières premières", [("Brent", "BZ=F", "cmd"), ("WTI", "CL=F", "cmd"), ("Gaz TTF", "TTF=F", "cmd"), ("Or", "GC=F", "cmd"),
                               ("Argent", "SI=F", "cmd"), ("Cuivre", "HG=F", "cmd")]),
    ("🌡️ Volatilité & crédit", [("VIX", "^VIX", "vix"), ("High yield HYG", "HYG", "etf"), ("Treasuries TLT", "TLT", "etf")]),
    ("₿ Crypto", [("Bitcoin", "BTC-USD", "crypto"), ("Ethereum", "ETH-USD", "crypto")]),
]
EQUITY_CASH = ["S&P 500", "Nasdaq", "Euro Stoxx 50", "CAC 40", "DAX", "FTSE 100", "Nikkei 225", "Hang Seng"]
FT_FEEDS = {"markets": "https://www.ft.com/markets?format=rss", "economy": "https://www.ft.com/global-economy?format=rss",
            "lex": "https://www.ft.com/lex?format=rss", "companies": "https://www.ft.com/companies?format=rss",
            "opinion": "https://www.ft.com/opinion?format=rss", "alphaville": "https://www.ft.com/alphaville?format=rss",
            "world": "https://www.ft.com/world?format=rss", "home": "https://www.ft.com/rss/home"}
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


# ---------------------------------------------------------------------------
# Formatage
# ---------------------------------------------------------------------------
def fr(s):
    """Virgule décimale française."""
    return s.replace(".", ",")


def num(x, spec):
    """Nombre formaté avec virgule décimale : num(3.14159, '.2f') -> '3,14'."""
    return fr(format(x, spec))


def fmt_price(kind, v):
    if kind == "yield":
        return fr(f"{v:.2f}") + "%"
    if kind == "fx4":
        return fr(f"{v:.4f}")
    if kind == "fx2":
        return fr(f"{v:.2f}")
    if v >= 10000:
        return f"{v:,.0f}".replace(",", " ")
    if v >= 1000:
        return f"{v:,.0f}".replace(",", " ")
    if v >= 100:
        return fr(f"{v:.1f}")
    return fr(f"{v:.2f}")


def fmt_chg(kind, v):
    if v is None:
        return "–"
    if kind == "yield":
        return f"{v * 100:+.0f}pb"
    return fr(f"{v:+.1f}") + "%"


def esc(s):
    return html.escape(str(s), quote=False)


# ---------------------------------------------------------------------------
# Données de marché
# ---------------------------------------------------------------------------
def fetch_close(ticker):
    """Série des cours de clôture sur 1 an (pandas.Series) ou None."""
    import yfinance as yf

    for _ in range(2):
        try:
            h = yf.Ticker(ticker).history(period="1y")
            c = h["Close"].dropna()
            if len(c) >= 5:
                return c
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] {ticker}: {type(e).__name__} {str(e)[:80]}", file=sys.stderr)
    return None


def compute_stats(close, kind):
    """Variations 1j / 1 semaine / 1 mois, écart-type du mouvement du jour (z), tendance."""
    c = [float(x) for x in close]
    if len(c) < 5:
        return None
    use_diff = kind == "yield"

    def chg(a, b):
        return (a - b) if use_diff else ((a / b - 1) * 100 if b else 0.0)

    last = c[-1]
    d1 = chg(last, c[-2])
    d5 = chg(last, c[-6]) if len(c) > 5 else None
    d21 = chg(last, c[-22]) if len(c) > 21 else None
    moves = [chg(c[i], c[i - 1]) for i in range(max(1, len(c) - 61), len(c) - 1)]
    sd = statistics.pstdev(moves) if len(moves) >= 20 else 0
    z = d1 / sd if sd else None
    ma50 = statistics.fmean(c[-50:]) if len(c) >= 50 else None
    ma200 = statistics.fmean(c[-200:]) if len(c) >= 200 else None
    rank = sum(1 for x in c if x <= last) / len(c) * 100
    return {"last": last, "d1": d1, "d5": d5, "d21": d21, "z": z, "ma50": ma50, "ma200": ma200,
            "hi": max(c), "lo": min(c), "rank": rank, "date": close.index[-1].date()}


def load_market():
    """-> dict nom -> {kind, group, stats}. Les tickers sans données sont simplement absents."""
    items = [(g, n, t, k) for g, lst in GROUPS for n, t, k in lst]
    with ThreadPoolExecutor(max_workers=5) as pool:
        closes = list(pool.map(lambda x: fetch_close(x[2]), items))
    data = {}
    for (g, n, t, k), c in zip(items, closes):
        s = compute_stats(c, k) if c is not None else None
        if s:
            data[n] = {"kind": k, "group": g, "s": s}
        else:
            print(f"[WARN] pas de données pour {n} ({t})", file=sys.stderr)
    return data


# ---------------------------------------------------------------------------
# Tonalité de marché et lecture croisée
# ---------------------------------------------------------------------------
def d1(data, name):
    return data[name]["s"]["d1"] if name in data else None


def regime(data):
    """Note de risque transparente : positive = appétit pour le risque. Renvoie (libellé, raisons)."""
    score, why = 0.0, []
    eq = [d1(data, n) for n in EQUITY_CASH if d1(data, n) is not None]
    if eq:
        avg = sum(eq) / len(eq)
        score += max(-2, min(2, avg / 0.5))
        why.append(f"actions {num(avg, '+.1f')}% en moyenne ({sum(1 for x in eq if x > 0)}/{len(eq)} en hausse)")
    if "VIX" in data:
        v = data["VIX"]["s"]
        if v["last"] > 30:
            score -= 2
        elif v["last"] > 20:
            score -= 1
        if v["d1"] > 8:
            score -= 1
        elif v["d1"] < -8:
            score += 1
        why.append(f"VIX {num(v['last'], '.1f')} ({num(v['d1'], '+.0f')}%)")
    if "High yield HYG" in data:
        h = data["High yield HYG"]["s"]["d1"]
        score += 0.5 if h > 0.2 else (-1 if h < -0.3 else 0)
    dxy = d1(data, "Dollar Index")
    if dxy is not None:
        score += -0.5 if dxy > 0.4 else (0.5 if dxy < -0.4 else 0)
        if abs(dxy) > 0.3:
            why.append(f"dollar {num(dxy, '+.1f')}%")
    gold = d1(data, "Or")
    if gold is not None and eq and gold > 1 and sum(eq) / len(eq) < 0:
        score -= 0.5
    if score >= 2:
        label = "risk-on net 🟢"
    elif score >= 0.7:
        label = "plutôt risk-on 🟢"
    elif score <= -2:
        label = "risk-off net 🔴"
    elif score <= -0.7:
        label = "plutôt prudente 🟠"
    else:
        label = "neutre ⚪"
    return label, why


def readings(data):
    """Lecture croisée des marchés : liste de phrases, les plus marquantes d'abord."""
    out = []  # (priorité, texte)

    def s(name):
        return data[name]["s"] if name in data else None

    y10, y3m, y5 = s("US 10 ans"), s("US 3 mois"), s("US 5 ans")
    if y10:
        bp1 = y10["d1"] * 100
        bp21 = y10["d21"] * 100 if y10["d21"] is not None else 0
        txt = f"Taux US 10 ans à {num(y10['last'], '.2f')}% ({bp1:+.0f} pb sur la journée, {bp21:+.0f} pb sur 1 mois)"
        if abs(bp21) >= 25:
            txt += " : " + ("montée rapide des taux longs, pression sur les valorisations et les actifs longs" if bp21 > 0 else "détente marquée des taux longs, favorable aux actifs de duration")
        if y3m:
            spread = (y10["last"] - y3m["last"]) * 100
            txt += f". Courbe 3 mois–10 ans : {spread:+.0f} pb" + (" (inversée, signal de ralentissement)" if spread < 0 else " (pentue)") + "."
        out.append((abs(y10["z"] or 0) + abs(bp21) / 25, txt))
    tlt = s("Treasuries TLT")
    if tlt and tlt["d21"] is not None and tlt["d21"] < -3:
        out.append((1.5, f"Les obligations longues souffrent : TLT {num(tlt['d21'], '+.1f')}% sur 1 mois."))

    brent, wti = s("Brent"), s("WTI")
    for nm, st in (("Brent", brent), ("WTI", wti)):
        if st and abs(st["d1"]) >= 2:
            sens = "bondit" if st["d1"] > 0 else "chute"
            extra = " : risque inflationniste et pression sur les marges des secteurs consommateurs d'énergie" if st["d1"] > 0 else " : soulagement pour l'inflation, pression sur les valeurs énergétiques"
            out.append((abs(st["z"] or 0) + 1, f"Le {nm} {sens} de {num(abs(st['d1']), '.1f')}% ({num(st['z'], '+.1f')}σ), à {fmt_price('cmd', st['last'])} $" + extra + "."))
            break

    gold, dxy = s("Or"), s("Dollar Index")
    if gold and dxy and y10:
        if gold["d1"] > 0.3 and dxy["d1"] > 0.1 and y10["d1"] > 0:
            out.append((1.2, "L'or résiste malgré la hausse du dollar et des taux : demande de protection (géopolitique, banques centrales)."))
        elif gold["d1"] < -0.7 and (dxy["d1"] > 0.2 or y10["d1"] > 0.03):
            out.append((1.2, "L'or recule, pénalisé par un dollar et/ou des taux réels en hausse."))
    if dxy and abs(dxy["d1"]) >= 0.4:
        out.append((abs(dxy["z"] or 0), f"Dollar Index {num(dxy['d1'], '+.1f')}% : " + ("un dollar fort resserre les conditions financières mondiales." if dxy["d1"] > 0 else "un dollar faible soutient les actifs risqués et les matières premières.")))

    for nm in ("S&P 500", "Nasdaq", "CAC 40"):
        st = s(nm)
        if not st:
            continue
        bits = []
        if st["ma200"]:
            bits.append(f"{num((st['last'] / st['ma200'] - 1) * 100, '+.1f')}% vs sa moyenne 200 j")
        bits.append(f"{num((st['last'] / st['hi'] - 1) * 100, '+.1f')}% sous son plus haut 52 sem." if st["last"] < st["hi"] else "à son plus haut 52 sem.")
        if st["d21"] is not None:
            bits.append(f"{num(st['d21'], '+.1f')}% sur 1 mois")
        pr = abs(st["z"] or 0) * 0.6 + (1.0 if nm == "S&P 500" else 0.5)
        out.append((pr, f"{nm} : " + ", ".join(bits) + "."))

    vix = s("VIX")
    if vix:
        zone = "stress" if vix["last"] > 30 else "tension" if vix["last"] > 20 else "complaisance" if vix["last"] < 13 else "niveau normal"
        out.append((0.8 + abs(vix["z"] or 0) * 0.5, f"VIX à {num(vix['last'], '.1f')} ({zone}, {vix['rank']:.0f}e centile sur 1 an)."))

    hyg = s("High yield HYG")
    eq = [d1(data, n) for n in EQUITY_CASH if d1(data, n) is not None]
    if hyg and eq and hyg["d1"] < -0.3 and sum(eq) / len(eq) < 0:
        out.append((1.8, "Le crédit high yield se tend en même temps que les actions : signal de prudence à surveiller."))

    btc, ndq = s("Bitcoin"), s("Nasdaq")
    if btc and abs(btc["d1"]) >= 3:
        accord = ""
        if ndq:
            accord = " en ligne avec le Nasdaq" if btc["d1"] * ndq["d1"] > 0 else " à contre-courant du Nasdaq"
        out.append((abs(btc["z"] or 0) * 0.7, f"Bitcoin {num(btc['d1'], '+.1f')}% sur 24 h{accord}."))

    out.sort(key=lambda x: -x[0])
    return [t for _, t in out[:6]]


# Seuil de mouvement du jour jugé notable même quand la volatilité habituelle de l'actif est élevée
# (en %, sauf taux en points de pourcentage). Un mouvement égal au seuil compte comme 2 écarts-types.
ABS_THRESHOLD = {"idx": 1.5, "fut": 1.5, "yield": 0.10, "fx4": 1.0, "fx2": 1.0, "cmd": 3.0, "vix": 10.0, "etf": 1.5, "crypto": 5.0}


def move_strength(v):
    """Force du mouvement du jour : max(|z|, mouvement / seuil absolu x 2)."""
    st = v["s"]
    z = abs(st["z"]) if st["z"] is not None else 0
    return max(z, abs(st["d1"]) / ABS_THRESHOLD.get(v["kind"], 2.0) * 2)


def notable_movers(data, threshold=1.8):
    return sorted(((move_strength(v), n, v) for n, v in data.items() if move_strength(v) >= threshold), key=lambda x: -x[0])


def unusual_moves(data, top=5, threshold=1.8):
    """Les mouvements du jour les plus marquants : écart à la volatilité récente (σ) ou ampleur absolue."""
    rows = notable_movers(data, threshold)
    lines = []
    for _, n, v in rows[:top]:
        st = v["s"]
        sigma = f" ({num(st['z'], '+.1f')}σ)" if st["z"] is not None else ""
        lines.append(f"• <b>{esc(n)}</b> {fmt_chg(v['kind'], st['d1'])}{sigma}, à {esc(fmt_price(v['kind'], st['last']))}")
    return lines


# ---------------------------------------------------------------------------
# Tableau de marché
# ---------------------------------------------------------------------------
def table_sections(data):
    ref = max((v["s"]["date"] for v in data.values()), default=None)
    sections = []
    for title, lst in GROUPS:
        rows = []
        for n, _, k in lst:
            if n not in data:
                rows.append(f"{n:<15}{'n.d.':>9}")
                continue
            st = data[n]["s"]
            mark = "⚡" if st["z"] is not None and abs(st["z"]) >= 2 else (f"({st['date']:%d/%m})" if ref and st["date"] < ref else "")
            rows.append(f"{n:<15}{fmt_price(k, st['last']):>9} {fmt_chg(k, st['d1']):>7} {fmt_chg(k, st['d5']):>7} {fmt_chg(k, st['d21']):>7} {mark}")
        sections.append((title, rows))
    head = f"{'':<15}{'':>9} {'1j':>7} {'1sem':>7} {'1mois':>7}"
    parts = []
    for title, rows in sections:
        body = [head] + rows
        parts.append(f"<b>{title}</b>\n<pre>{esc(chr(10).join(body))}</pre>")
    return parts


# ---------------------------------------------------------------------------
# Calendrier économique
# ---------------------------------------------------------------------------
FLAGS = {"USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵", "CNY": "🇨🇳", "CHF": "🇨🇭", "CAD": "🇨🇦", "AUD": "🇦🇺", "NZD": "🇳🇿"}


def fetch_calendar():
    try:
        r = requests.get(CALENDAR_URL, headers=UA, timeout=25)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] calendrier indisponible: {e}", file=sys.stderr)
        return []


def calendar_section(events, now=None):
    now = now or datetime.now(PARIS)
    today = now.date()
    todays, upcoming = [], []
    for e in events:
        try:
            dt = datetime.fromisoformat(e["date"]).astimezone(PARIS)
        except Exception:  # noqa: BLE001
            continue
        major = e.get("impact") == "High" or (e.get("impact") == "Medium" and e.get("country") in ("USD", "EUR"))
        if not major:
            continue
        if dt.date() == today:
            todays.append((dt, e))
        elif today < dt.date() <= today + timedelta(days=2) and e.get("impact") == "High":
            upcoming.append((dt, e))

    def line(dt, e, with_day=False):
        extra = []
        if e.get("forecast"):
            extra.append(f"prév. {esc(e['forecast'])}")
        if e.get("previous"):
            extra.append(f"préc. {esc(e['previous'])}")
        day = f"{JOURS[dt.weekday()][:3]}. " if with_day else ""
        return f"• {day}{dt:%H:%M} {FLAGS.get(e.get('country'), esc(e.get('country', '')))} {esc(e['title'])}" + (f" <i>({', '.join(extra)})</i>" if extra else "")

    lines = [line(dt, e) for dt, e in sorted(todays, key=lambda x: x[0])[:8]]
    if not lines:
        lines = ["• Aucune publication majeure aujourd'hui."]
    nxt = [line(dt, e, True) for dt, e in sorted(upcoming, key=lambda x: x[0])[:4]]
    txt = "<b>🗓️ Agenda du jour</b> <i>(heure de Paris)</i>\n" + "\n".join(lines)
    if nxt:
        txt += "\n<b>Dans les 2 jours</b>\n" + "\n".join(nxt)
    return txt


# ---------------------------------------------------------------------------
# Financial Times : quels articles valent la lecture
# ---------------------------------------------------------------------------
THEMES = {
    "Banques centrales": ["fed ", "federal reserve", "powell", "ecb", "lagarde", "bank of england", "boe", "bank of japan", "boj", "rate cut", "rate hike", "interest rate", "central bank", "fomc"],
    "Taux & obligations": ["treasury", "treasuries", "bond", "yield", "gilt", "bund", "debt", "deficit", "borrowing cost", "sovereign", "mortgage rate"],
    "Inflation & croissance": ["inflation", "cpi", "payroll", "jobs report", "unemployment", "recession", "gdp", "growth", "consumer spending", "stagflation"],
    "Énergie & matières premières": ["oil", "crude", "opec", "hormuz", "gas ", "lng", "energy", "gold", "copper", "commodit"],
    "Géopolitique & commerce": ["tariff", "trade war", "sanction", "iran", "russia", "ukraine", "china", "taiwan", "trump", "middle east", "election"],
    "Banques & crédit": ["bank", "private credit", "lender", "credit market", "default", "bankruptcy", "jpmorgan", "goldman", "morgan stanley", "bnp", "societe generale", "hsbc", "ubs", "blackrock", "private equity"],
    "Deals & M&A": ["acquisition", "acquire", "takeover", "buyout", "merger", "deal", "ipo", "listing", "stake", "bid for", "spac"],
    "Marchés actions": ["stocks", "equities", "wall street", "s&p 500", "nasdaq", "rally", "selloff", "sell-off", "earnings", "valuation", "bubble"],
    "Devises": ["dollar", "euro ", "yen", "sterling", "currency", "forex"],
    "IA & tech": ["openai", "nvidia", "artificial intelligence", " ai ", "chip", "data centre", "data center"],
}
THEME_WEIGHT = {"Banques centrales": 3.5, "Taux & obligations": 3, "Inflation & croissance": 3, "Énergie & matières premières": 2.5, "Géopolitique & commerce": 2.5,
                "Banques & crédit": 3, "Deals & M&A": 2.5, "Marchés actions": 2, "Devises": 2, "IA & tech": 1.5}
FEED_WEIGHT = {"markets": 3, "economy": 3, "lex": 3, "opinion": 2, "alphaville": 1.5, "companies": 2, "world": 0.5, "home": 1}
NOISE = re.compile(r"further reading|firstft|newsletter|podcast|crossword|grand prix|recipe|wine|travel|property|restaurant|football|cricket|golf|fashion|obituary|how to spend it|weekend|puzzle", re.I)
# actif qui bouge fort -> mots qui rendent un article plus pertinent aujourd'hui
MOVER_TERMS = {"Brent": ["oil", "crude", "opec", "hormuz", "energy", "tanker"], "WTI": ["oil", "crude", "opec", "tanker"], "Or": ["gold"], "US 10 ans": ["treasury", "yield", "bond"], "US 30 ans": ["treasury", "yield", "bond"],
               "Dollar Index": ["dollar"], "EUR/USD": ["euro", "dollar"], "USD/JPY": ["yen", "japan", "boj"], "VIX": ["selloff", "volatility", "stocks"], "Bitcoin": ["bitcoin", "crypto"],
               "Nikkei 225": ["japan", "nikkei", "yen"], "CAC 40": ["france", "french"], "DAX": ["german", "germany"], "Hang Seng": ["china", "hong kong"], "Nasdaq": ["tech", "nvidia", "ai"],
               "Gaz TTF": ["gas", "lng", "energy"], "Cuivre": ["copper", "china"]}


def fetch_ft(feeds=FT_FEEDS):
    """-> liste d'articles {title, desc, link, dt, feed} issus des flux RSS publics du FT."""
    items = {}
    for feed, url in feeds.items():
        try:
            r = requests.get(url, headers=UA, timeout=25)
            r.raise_for_status()
            for it in ET.fromstring(r.content).iter("item"):
                link = (it.findtext("link") or "").split("?")[0]
                if not link or link in items and FEED_WEIGHT[items[link]["feed"]] >= FEED_WEIGHT[feed]:
                    continue
                try:
                    dt = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
                except Exception:  # noqa: BLE001
                    dt = None
                items[link] = {"title": (it.findtext("title") or "").strip(), "desc": re.sub(r"<[^>]+>", "", it.findtext("description") or "").strip(),
                               "link": link, "dt": dt, "feed": feed}
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] flux FT {feed} indisponible: {type(e).__name__}", file=sys.stderr)
    return list(items.values())


def score_article(a, boost_terms, now):
    text = f" {a['title']} {a['desc']} ".lower()
    if NOISE.search(a["title"]):
        return -9, None
    score = FEED_WEIGHT.get(a["feed"], 1)
    themes = [(THEME_WEIGHT[t] + 0.3 * sum(k in text for k in kws), t) for t, kws in THEMES.items() if any(k in text for k in kws)]
    themes.sort(reverse=True)
    if themes:
        score += themes[0][0] + 0.5 * sum(w for w, _ in themes[1:3])
    if any(b in text for b in boost_terms):
        score += 3
    if a["dt"]:
        age = (now - a["dt"]).total_seconds() / 3600
        if age > 36:
            return -9, None
        score += 1.5 if age < 8 else (0.7 if age < 18 else 0)
    return score, (themes[0][1] if themes else None)


def ft_sections(articles, data, now=None):
    now = now or datetime.now(timezone.utc)
    boost = []
    movers = [(sc, n) for sc, n, _ in notable_movers(data)][:4]
    for _, n in movers:
        boost += MOVER_TERMS.get(n, [])
    scored = []
    for a in articles:
        sc, theme = score_article(a, boost, now)
        if sc >= 5:
            scored.append((sc, theme, a))
    scored.sort(key=lambda x: -x[0])

    def item(theme, a):
        desc = a["desc"][:150].rstrip() + ("…" if len(a["desc"]) > 150 else "")
        tag = f" <i>[{esc(theme)}]</i>" if theme else ""
        return f'• <a href="{esc(a["link"])}">{esc(a["title"])}</a>{tag}' + (f"\n  {esc(desc)}" if desc else "")

    main, per_feed, used = [], {}, set()
    for sc, theme, a in scored:
        if theme == "Deals & M&A" and len(main) >= 3:
            continue  # les deals ont leur propre rubrique
        if per_feed.get(a["feed"], 0) >= 2:
            continue
        main.append(item(theme, a))
        per_feed[a["feed"]] = per_feed.get(a["feed"], 0) + 1
        used.add(a["link"])
        if len(main) == 5:
            break
    deals = []
    for sc, theme, a in scored:
        if a["link"] in used:
            continue
        text = f" {a['title']} {a['desc']} ".lower()
        if any(k in text for k in THEMES["Deals & M&A"] + THEMES["Banques & crédit"]):
            deals.append(item(None, a))
            used.add(a["link"])
        if len(deals) == 2:
            break
    out = []
    if main:
        why = f" <i>(priorité aux sujets qui bougent : {esc(', '.join(n for _, n in movers[:3]))})</i>" if movers else ""
        out.append("<b>📰 FT — à lire aujourd'hui</b>" + why + "\n" + "\n".join(main))
    if deals:
        out.append("<b>💼 FT — deals & banques</b> <i>(utile pour les entretiens)</i>\n" + "\n".join(deals))
    return out


# ---------------------------------------------------------------------------
# Assemblage et envoi
# ---------------------------------------------------------------------------
def safe(fn, default, label):
    """Une rubrique qui plante ne doit jamais empêcher l'envoi du reste."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"[ERREUR] {label}: {type(e).__name__}: {e}", file=sys.stderr)
        return default


def build_sections(now=None, data=None, calendar=None, articles=None):
    now = now or datetime.now(PARIS)
    data = data if data is not None else safe(load_market, {}, "marchés")
    date_str = f"{JOURS[now.weekday()]} {now.day} {MOIS[now.month - 1]} {now.year}"
    sections = []

    head = f"📊 <b>Briefing macro — {date_str}</b>"
    if data:
        label, why = regime(data)
        head += f"\n🌡️ <b>Tonalité : {label}</b>\n<i>{esc(' · '.join(why))}</i>"
    else:
        head += "\n⚠️ Données de marché indisponibles (Yahoo Finance injoignable)."
    unusual = safe(lambda: unusual_moves(data), [], "mouvements inhabituels") if data else []
    if unusual:
        head += "\n\n<b>⚡ Mouvements inhabituels</b> <i>(σ = écart vs volatilité des 3 derniers mois)</i>\n" + "\n".join(unusual)
    sections.append(head)

    if data:
        lect = safe(lambda: readings(data), [], "lecture croisée")
        if lect:
            sections.append("<b>🧠 Lecture des marchés</b>\n" + "\n".join(f"• {esc(t)}" for t in lect))
        sections += safe(lambda: table_sections(data), [], "tableau")
        sections.append("<i>⚡ = mouvement ≥ 2σ · (jj/mm) = marché fermé, dernière clôture · pb = points de base</i>")

    cal = calendar if calendar is not None else safe(fetch_calendar, [], "calendrier")
    sections.append(safe(lambda: calendar_section(cal, now), "", "agenda"))
    arts = articles if articles is not None else safe(fetch_ft, [], "FT")
    sections += safe(lambda: ft_sections(arts, data or {}), [], "sélection FT")
    return [s for s in sections if s]


def chunk(sections, limit=3900):
    """Regroupe les rubriques en messages de moins de 4096 caractères (limite Telegram), sans couper une rubrique."""
    msgs, cur = [], ""
    for s in sections:
        if cur and len(cur) + len(s) + 2 > limit:
            msgs.append(cur)
            cur = s
        else:
            cur = f"{cur}\n\n{s}" if cur else s
    if cur:
        msgs.append(cur)
    return msgs


def send_telegram(messages):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    raw = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not raw:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant.")
    chat_ids = [c.strip() for c in raw.split(",") if c.strip()]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    failed = []
    for chat_id in chat_ids:
        try:
            for m in messages:
                r = requests.post(url, data={"chat_id": chat_id, "text": m, "parse_mode": "HTML", "disable_web_page_preview": "true"}, timeout=20)
                if not r.ok:  # repli en texte brut si le HTML est refusé
                    print(f"[WARN] Telegram HTML refusé ({r.status_code}): {r.text[:150]}", file=sys.stderr)
                    r = requests.post(url, data={"chat_id": chat_id, "text": re.sub(r"<[^>]+>", "", html.unescape(m)), "disable_web_page_preview": "true"}, timeout=20)
                r.raise_for_status()
            print(f"✅ {len(messages)} message(s) envoyé(s) à {chat_id}")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] Échec d'envoi à {chat_id}: {e}", file=sys.stderr)
            failed.append(chat_id)
    if len(failed) == len(chat_ids):
        raise RuntimeError(f"Échec d'envoi pour tous les destinataires: {failed}")


# ---------------------------------------------------------------------------
# Anti-doublon et créneau d'envoi
# ---------------------------------------------------------------------------
STATE_FILE = "last_sent.txt"


def today_paris():
    return datetime.now(PARIS).strftime("%Y-%m-%d")


def already_sent_today():
    try:
        with open(STATE_FILE) as f:
            return f.read().strip() == today_paris()
    except FileNotFoundError:
        return False


def mark_sent_today():
    with open(STATE_FILE, "w") as f:
        f.write(today_paris())


def in_send_window(now=None):
    """Les crons gratuits de GitHub arrivent avec 6 à 10 h de retard. L'ancien garde-fou (7h-10h) rejetait
    donc tous les passages : plus aucun briefing depuis fin août. Désormais : le premier passage de la journée
    après 7h part, quelle que soit l'heure, et l'anti-doublon évite un second envoi."""
    now = now or datetime.now(PARIS)
    if now.weekday() >= 5 and not SEND_WEEKENDS:
        return False
    return SEND_FROM_HOUR <= now.hour <= SEND_UNTIL_HOUR


if __name__ == "__main__":
    force = os.environ.get("FORCE_SEND") == "1"
    dry = os.environ.get("DRY_RUN") == "1"
    if not force and not dry:
        if already_sent_today():
            print("⏭️  Briefing déjà envoyé aujourd'hui (anti-doublon).")
            sys.exit(0)
        if not in_send_window():
            print(f"⏭️  Hors fenêtre d'envoi ({SEND_FROM_HOUR}h-{SEND_UNTIL_HOUR}h Paris, jours ouvrés) : {datetime.now(PARIS):%A %H:%M}.")
            sys.exit(0)
    messages = chunk(build_sections())
    for i, m in enumerate(messages, 1):
        print(f"\n===== MESSAGE {i}/{len(messages)} ({len(m)} caractères) =====\n{m}")
    if dry:
        print("\n(DRY_RUN : rien n'est envoyé)")
        sys.exit(0)
    send_telegram(messages)
    mark_sent_today()
    print("\n✅ Briefing envoyé.")

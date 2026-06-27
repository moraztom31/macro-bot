"""
Bot de briefing macro quotidien.
Récupère les prix des indices/forex/commos/taux/crypto et envoie
un résumé + une analyse écrite simple sur Telegram.
"""

import os
import sys
import requests
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Configuration des actifs suivis
# Format : nom affiché -> (ticker Yahoo Finance, catégorie)
# ---------------------------------------------------------------------------

ASSETS = {
    # Indices actions
    "S&P 500": ("^GSPC", "actions"),
    "Nasdaq": ("^IXIC", "actions"),
    "CAC 40": ("^FCHI", "actions"),
    "DAX": ("^GDAXI", "actions"),
    "Nikkei 225": ("^N225", "actions"),
    # Forex
    "EUR/USD": ("EURUSD=X", "forex"),
    "Dollar Index (DXY)": ("DX-Y.NYB", "forex"),
    # Matières premières
    "Or (once)": ("GC=F", "commo"),
    "Pétrole WTI": ("CL=F", "commo"),
    # Taux / obligations
    "Taux 10 ans US": ("^TNX", "taux"),
}

# Cryptos via CoinGecko (API publique gratuite, pas de clé requise)
CRYPTOS = {
    "Bitcoin": "bitcoin",
    "Ethereum": "ethereum",
}


def fetch_yfinance_data():
    """Récupère prix actuel + variation % pour chaque actif Yahoo Finance.
    Renvoie un dict: nom -> {"prix": float, "pct": float, "categorie": str} ou None si échec.
    """
    results = {}
    for name, (ticker, categorie) in ASSETS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if hist.empty or len(hist) < 2:
                print(f"[WARN] Pas assez de données pour {name} ({ticker})", file=sys.stderr)
                results[name] = None
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            pct = (last - prev) / prev * 100 if prev else 0.0
            results[name] = {"prix": last, "pct": pct, "categorie": categorie}
        except Exception as e:
            print(f"[WARN] Échec récupération {name} ({ticker}): {e}", file=sys.stderr)
            results[name] = None
    return results


def fetch_crypto_data():
    """Récupère prix + variation 24h pour les cryptos via CoinGecko."""
    results = {}
    ids = ",".join(CRYPTOS.values())
    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids}&vs_currencies=usd&include_24hr_change=true"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for name, cg_id in CRYPTOS.items():
            if cg_id in data:
                results[name] = {
                    "prix": data[cg_id]["usd"],
                    "pct": data[cg_id].get("usd_24h_change", 0.0),
                    "categorie": "crypto",
                }
            else:
                results[name] = None
    except Exception as e:
        print(f"[WARN] Échec récupération crypto: {e}", file=sys.stderr)
        for name in CRYPTOS:
            results[name] = None
    return results


def format_line(name, info):
    """Formate une ligne d'affichage pour un actif."""
    if info is None:
        return f"• {name} : donnée indisponible"
    prix = info["prix"]
    pct = info["pct"]
    emoji = "🟢" if pct > 0 else ("🔴" if pct < 0 else "⚪")
    # Format adapté selon catégorie
    if info["categorie"] == "taux":
        return f"{emoji} {name} : {prix:.2f}% ({pct:+.2f}%)"
    elif info["categorie"] == "forex" and prix < 10:
        return f"{emoji} {name} : {prix:.4f} ({pct:+.2f}%)"
    elif prix >= 1000:
        return f"{emoji} {name} : {prix:,.0f} ({pct:+.2f}%)"
    else:
        return f"{emoji} {name} : {prix:,.2f} ({pct:+.2f}%)"


def generate_analysis(all_data):
    """Génère une courte analyse textuelle basée sur des règles simples."""
    def pct_of(name):
        d = all_data.get(name)
        return d["pct"] if d else None

    phrases = []

    # --- Actions ---
    actions_pct = [pct_of(n) for n in ["S&P 500", "Nasdaq", "CAC 40", "DAX", "Nikkei 225"]]
    actions_pct = [p for p in actions_pct if p is not None]
    if actions_pct:
        avg_actions = sum(actions_pct) / len(actions_pct)
        if avg_actions > 0.5:
            phrases.append("Les marchés actions sont nettement haussiers aujourd'hui, signe d'un appétit pour le risque.")
        elif avg_actions > 0.1:
            phrases.append("Les marchés actions évoluent en légère hausse, dans une ambiance plutôt calme.")
        elif avg_actions < -0.5:
            phrases.append("Les marchés actions sont en net repli, traduisant une aversion au risque marquée.")
        elif avg_actions < -0.1:
            phrases.append("Les marchés actions sont légèrement dans le rouge.")
        else:
            phrases.append("Les marchés actions sont globalement stables, sans direction franche.")

    # --- Dollar / Forex ---
    dxy = pct_of("Dollar Index (DXY)")
    if dxy is not None:
        if dxy > 0.3:
            phrases.append("Le dollar se renforce nettement, ce qui pèse généralement sur les devises et matières premières libellées en USD.")
        elif dxy < -0.3:
            phrases.append("Le dollar s'affaiblit, ce qui peut soutenir l'or et les actifs risqués.")

    # --- Taux ---
    taux_us = pct_of("Taux 10 ans US")
    if taux_us is not None:
        if taux_us > 1.0:
            phrases.append("Les taux longs américains montent sensiblement, un facteur de pression potentielle sur les actions de croissance.")
        elif taux_us < -1.0:
            phrases.append("Les taux longs américains se détendent, ce qui est plutôt favorable aux actifs risqués.")

    # --- Or ---
    or_pct = pct_of("Or (once)")
    if or_pct is not None:
        if or_pct > 0.7:
            phrases.append("L'or progresse fortement, souvent le signe d'une recherche de valeurs refuges.")
        elif or_pct < -0.7:
            phrases.append("L'or recule nettement, cohérent avec un regain d'appétit pour le risque ou un dollar fort.")

    # --- Pétrole ---
    petrole_pct = pct_of("Pétrole WTI")
    if petrole_pct is not None and abs(petrole_pct) > 1.5:
        direction = "grimpe" if petrole_pct > 0 else "chute"
        phrases.append(f"Le pétrole {direction} fortement ({petrole_pct:+.1f}%), un mouvement à surveiller pour l'inflation et les coûts énergétiques.")

    # --- Crypto ---
    btc_pct = pct_of("Bitcoin")
    if btc_pct is not None and abs(btc_pct) > 3:
        direction = "s'envole" if btc_pct > 0 else "plonge"
        phrases.append(f"Le Bitcoin {direction} ({btc_pct:+.1f}% sur 24h), une volatilité typique des actifs crypto.")

    if not phrases:
        phrases.append("Journée calme sans mouvement macro significatif à signaler.")

    return " ".join(phrases)


def build_message():
    """Construit le message complet à envoyer."""
    yf_data = fetch_yfinance_data()
    crypto_data = fetch_crypto_data()
    all_data = {**yf_data, **crypto_data}

    date_str = datetime.now().strftime("%A %d %B %Y").capitalize()

    lines = [f"📊 *Briefing Macro — {date_str}*", ""]

    lines.append("*📈 Indices actions*")
    for name in ["S&P 500", "Nasdaq", "CAC 40", "DAX", "Nikkei 225"]:
        lines.append(format_line(name, all_data.get(name)))
    lines.append("")

    lines.append("*💱 Forex*")
    for name in ["EUR/USD", "Dollar Index (DXY)"]:
        lines.append(format_line(name, all_data.get(name)))
    lines.append("")

    lines.append("*🟡 Matières premières*")
    for name in ["Or (once)", "Pétrole WTI"]:
        lines.append(format_line(name, all_data.get(name)))
    lines.append("")

    lines.append("*🏦 Taux & obligations*")
    for name in ["Taux 10 ans US"]:
        lines.append(format_line(name, all_data.get(name)))
    lines.append("")

    lines.append("*₿ Crypto*")
    for name in ["Bitcoin", "Ethereum"]:
        lines.append(format_line(name, all_data.get(name)))
    lines.append("")

    lines.append("*🧠 Analyse du jour*")
    lines.append(generate_analysis(all_data))

    return "\n".join(lines)


def send_telegram_message(text):
    """Envoie le message via l'API Telegram Bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant dans les variables d'environnement."
        )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def is_right_time_slot():
    """Le workflow GitHub Actions est programmé sur 2 créneaux UTC (été/hiver)
    pour viser 7h45 heure française toute l'année. Cette fonction vérifie qu'on
    est bien dans la bonne fenêtre horaire locale, pour éviter un double envoi.
    Si lancé manuellement (workflow_dispatch) ou en local, on ignore ce filtre.
    """
    if os.environ.get("FORCE_SEND") == "1":
        return True
    now_paris = datetime.now(ZoneInfo("Europe/Paris"))
    return 7 <= now_paris.hour <= 8


if __name__ == "__main__":
    if not is_right_time_slot():
        print("⏭️  Hors créneau horaire cible (anti doublon été/hiver) — envoi annulé.")
        sys.exit(0)
    message = build_message()
    print(message)  # utile pour debug dans les logs GitHub Actions
    send_telegram_message(message)
    print("\n✅ Message envoyé avec succès.")

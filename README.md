# Macro Bot — briefing macro-financier quotidien

Bot Python qui envoie chaque jour ouvré, avant l'ouverture des marchés européens, un **briefing macro** sur Telegram :
état des marchés, mouvements inhabituels, agenda économique et sélection d'articles à lire.
Il tourne entièrement sur **GitHub Actions** (aucun serveur) et n'utilise **aucune API payante**.

## Fonctionnalités

| Rubrique | Contenu |
|---|---|
| **Tonalité du marché** | Score *risk-on / risk-off* transparent, avec les raisons chiffrées qui le justifient |
| **Mouvements inhabituels** | Variations mesurées en écarts-types (σ) par rapport à la volatilité des 3 derniers mois, avec des seuils absolus de secours par classe d'actifs |
| **Lecture des marchés** | Taux US et courbe 3 mois–10 ans, énergie, dollar, or, tendance des indices (moyenne 200 j, plus haut 52 semaines), VIX en centile, crédit high yield |
| **Tableau de bord** | Actions, futures, taux, changes, matières premières, volatilité, crypto (variation 1 jour, 1 semaine, 1 mois) |
| **Agenda économique** | Publications du jour et des 2 jours suivants, à l'heure de Paris |
| **Presse financière** | 5 articles classés par thème (banques centrales, taux, énergie, géopolitique…) et remontés quand ils expliquent un mouvement du jour, plus une rubrique deals & banques |

L'analyse est **calculée par règles** (statistiques et pondérations explicites), sans modèle de langage : chaque conclusion du briefing est traçable.

## Architecture

```
GitHub Actions (cron + déclenchement externe)
        │
        ▼
  macro_bot.py ──► Yahoo Finance (yfinance)      cours et historiques
              ├──► Flux RSS publics du FT         titres et résumés
              ├──► Calendrier économique (JSON)   événements macro
              │
              ├─ compute_stats()   variations 1j/1s/1m, z-score du jour
              ├─ regime()          score risk-on / risk-off
              ├─ readings()        lecture croisée des marchés
              ├─ score_article()   pertinence des articles
              ▼
        Telegram Bot API  (messages découpés sous la limite de 4096 caractères)
```

Choix de conception :

- **Résilience** : chaque rubrique est isolée (`safe()`). Si une source tombe, le reste du briefing part quand même.
- **Détection par σ** : un mouvement de 1 % n'a pas la même signification sur le Nikkei et sur le VIX. Le z-score compare chaque actif à sa propre volatilité récente.
- **Anti-doublon** : le fichier `last_sent.txt` mémorise le dernier envoi. Le premier passage de la journée après 7 h (Paris) envoie le briefing et les suivants sont ignorés. Cela absorbe les retards des crons gratuits de GitHub, qui peuvent atteindre plusieurs heures.
- **Concurrence maîtrisée** : un seul passage à la fois (`concurrency` du workflow), pour éviter les doubles envois.
- **Pas de week-end** : aucun envoi samedi et dimanche (paramétrable).

## Stack

Python 3.11 · `yfinance` · `requests` · GitHub Actions · Telegram Bot API

## Installation

1. **Fork ou clone** ce dépôt.
2. Crée un bot avec [@BotFather](https://t.me/BotFather) (`/newbot`) pour obtenir le token, puis récupère ton identifiant de chat en écrivant à ton bot.
3. Dans **Settings → Secrets and variables → Actions**, ajoute :
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID` (plusieurs identifiants possibles, séparés par des virgules)
4. Le workflow `Briefing Macro Quotidien` se déclenche automatiquement les jours ouvrés.

### Test en local

```bash
pip install -r requirements.txt
DRY_RUN=1 python macro_bot.py      # affiche le briefing sans l'envoyer
```

### Test sur GitHub

**Actions → Briefing Macro Quotidien → Run workflow**. Coche `dry_run` pour afficher le briefing dans les logs sans l'envoyer.

### Envoi à heure fixe (optionnel)

Pour recevoir le briefing à 7 h 30 précises, déclenche le workflow depuis un service de cron externe (par exemple cron-job.org) :

- `POST https://api.github.com/repos/<ton-compte>/macro-bot/actions/workflows/daily-briefing.yml/dispatches`
- Corps : `{"ref":"main"}`
- En-tête `Authorization: Bearer <PAT>`, avec un *fine-grained token* limité à ce dépôt (permission **Actions : Read and write**)

Les crons GitHub restent actifs en secours.

## Configuration

Tout se règle en haut de `macro_bot.py` :

- `GROUPS` : actifs suivis (nom, ticker Yahoo, format d'affichage)
- `SEND_FROM_HOUR`, `SEND_UNTIL_HOUR`, `SEND_WEEKENDS` : fenêtre d'envoi
- `ABS_THRESHOLD` : seuils absolus par classe d'actifs
- `THEMES`, `THEME_WEIGHT`, `FEED_WEIGHT`, `NOISE` : critères de sélection des articles

## Sécurité

Aucun secret n'est stocké dans le code : les identifiants Telegram sont fournis par les GitHub Secrets.

## Avertissement

Projet personnel à visée informative. Il ne constitue pas un conseil en investissement. Les données proviennent de sources publiques et peuvent être retardées ou incomplètes.

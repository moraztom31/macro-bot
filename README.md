# Bot de briefing macro (Telegram)

Un briefing envoyé chaque jour ouvré sur Telegram, par GitHub Actions :

- **Tonalité du marché** (risk-on / risk-off) avec les raisons chiffrées
- **Mouvements inhabituels** : mesurés en écarts-types (σ) par rapport à la volatilité des 3 derniers mois, avec des
  seuils absolus de secours (matières premières ≥ 3 %, indices ≥ 1,5 %, taux ≥ 10 pb...)
- **Lecture des marchés** : taux US et courbe 3 mois–10 ans, énergie, dollar, or, tendance des indices (moyenne 200 j,
  plus haut 52 semaines), VIX en centile, crédit high yield
- **Tableau** actions, futures, taux, changes, matières premières, volatilité, crypto (1 jour, 1 semaine, 1 mois)
- **Agenda économique** du jour (heure de Paris) et des 2 jours suivants
- **FT, à lire aujourd'hui** : les 5 articles les plus utiles parmi les flux RSS publics du Financial Times
  (titre et résumé, lien direct pour ton abonnement), classés par thème (banques centrales, taux, énergie, géopolitique...)
  et remontés quand ils expliquent un mouvement du jour. Une rubrique **deals & banques** (2 articles) pour les entretiens.

Aucune clé d'API payante. L'analyse est calculée par règles (pas de modèle de langage).

## Pourquoi le bot ne s'envoyait plus depuis fin août

Les crons gratuits de GitHub Actions arrivent avec 6 à 10 heures de retard. L'ancien garde-fou n'acceptait que 7h-10h
(Paris) : tous les passages étaient donc ignorés (« Hors créneau horaire cible »), tout en s'affichant en succès.
Désormais le **premier passage de la journée après 7h (jours ouvrés)** envoie le briefing, quelle que soit l'heure,
et `last_sent.txt` empêche un second envoi. Samedi et dimanche : rien (`SEND_WEEKENDS` dans `macro_bot.py`).

## Envoi à heure fixe (recommandé)

Pour recevoir le briefing à 7h30 au lieu de « quand GitHub veut », crée un job sur cron-job.org (gratuit) :

- URL : `https://api.github.com/repos/moraztom31/macro-bot/actions/workflows/daily-briefing.yml/dispatches`
- Méthode : POST, corps : `{"ref":"main"}`
- En-têtes : `Authorization: Bearer <PAT>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`
- Le PAT est un *fine-grained token* limité à ce repo, permission **Actions : Read and write**
- Horaire : 7h30 Europe/Paris, du lundi au vendredi

Les crons GitHub restent en secours si ce déclencheur échoue.

## Tester

- **Onglet Actions > Briefing Macro Quotidien > Run workflow** : coche `dry_run` pour afficher le briefing dans les logs
  sans l'envoyer ; décoche pour l'envoyer vraiment à Telegram (premier test conseillé pour vérifier le token).
- En local : `DRY_RUN=1 python macro_bot.py` (nécessite `pip install yfinance requests`).

## Réglages (`macro_bot.py`)

- `GROUPS` : actifs suivis (nom, ticker Yahoo, format)
- `SEND_FROM_HOUR`, `SEND_UNTIL_HOUR`, `SEND_WEEKENDS` : fenêtre d'envoi
- `THEMES`, `THEME_WEIGHT`, `FEED_WEIGHT`, `NOISE` : ce qui rend un article FT intéressant ou non
- `TELEGRAM_CHAT_ID` peut contenir plusieurs identifiants séparés par des virgules

## Secrets requis

`TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` (Settings > Secrets and variables > Actions).

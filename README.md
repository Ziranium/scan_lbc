# 🏠 LeBonCoin Property Scanner

**Analyse intelligente des annonces immobilières LeBonCoin avec IA, cache local et menu interactif.**

Un outil pour scanner, analyser et suivre les annonces de bien immobiliers locatifs sur LeBonCoin. Inclut l'extraction automatique des données (prix, loyer, rendements), analyse IA détaillée via Groq, et un système de cache pour éviter les re-scrapes inutiles.

---

## ✨ Fonctionnalités

- 🔍 **Scraping intelligent** : Extraction des annonces LeBonCoin avec retry automatique et délais adaptatifs
- 📊 **Données financières** : Prix d'achat, loyer mensuel, rendements brut/net calculés automatiquement
- 🤖 **Analyse IA** : Recommandations détaillées via Groq (llama-3.3-70b-versatile)
- 💾 **Cache local** : Stockage JSON persistant - pas de re-scrape si données en cache
- 📋 **Menu interactif** : Navigation facile avec tableaux formatés et légendes
- 👍 **Suivi utilisateur** : Marquez les annonces (intéressé/pas intéressé/hésitation)
- ⏱️ **Score et verdict** : Recommandation structurée (ACHETER/NEGOCIER/EVITER) avec notation

---

## 🚀 Installation

### Prérequis
- Python 3.8+
- pip

### Étapes

1. **Cloner le projet**
```bash
git clone https://github.com/yourusername/scan-lbc.git
cd scan-lbc
```

2. **Installer les dépendances**
```bash
pip install -r requirements.txt
```

3. **Configurer la clé API Groq** (optionnel pour l'analyse IA)
```bash
export GROQ_API_KEY="gsk_your_api_key_here"
```

---

## 📖 Usage

### Lancement rapide
```bash
# Avec cache existant (pas de scrape)
python3 scripts/interactive_scanner.py

# Scraper et mettre à jour le cache
# (Depuis le menu: tapez 's')
```

### Avec paramètres personnalisés
```bash
# Charger depuis le cache uniquement
python3 scripts/interactive_scanner.py --cache property_cache.json

# Avec analyse IA
GROQ_API_KEY=gsk_xxx python3 scripts/interactive_scanner.py --cache my_cache.json
```

---

## 🎯 Workflow

### Menu Principal
```
📋 LISTE DES ANNONCES (15 total)
───────────────────────────────────────────────────────────────────────────────────

  N°  Titre                                          Prix      Loyer  Rend  Status Analyse  Avis   Score  URL
  1.  Studio 25m² centre-ville parfait état       25000€      350€   16.8%  👍      ✅   ⚠️👍    6.5   https://...
  2.  T1 30m² calme proche transports             20000€      325€   19.5%         ⏳          5.2   https://...

Tapez le numéro de l'annonce (1-15) pour analyser
Ou entrez une commande:
  's' - Scraper les annonces et mettre a jour le cache
  'q' - Quitter

Choix: 
```

### Détail Annonce
```
📍 ANALYSE DÉTAILLÉE

📌 Titre: Studio 25m² centre-ville
💰 DONNÉES FINANCIÈRES:
  Prix d'achat: 25000€
  Loyer mensuel: 350€
  Rendement brut: 16.8%
  Rendement net: 14.2%

Options:
  1. Afficher analyse en cache
  2. Générer analyse IA (contenu complet)
  3. Modifier mon avis (👍/👎/🤔)
  4. Rafraîchir les données
  5. Retour

Choix:
```

---

## 🔧 Options

| Option | Défaut | Description |
|--------|--------|-------------|
| `--city` | Nantes | Localisation (coordonnées GPS incluses) |
| `--query` | loyer | Mot-clé de recherche |
| `--pages` | 20 | Nombre de pages à scraper |
| `--cache` | property_cache.json | Fichier de cache |
| `--debug` | False | Afficher logs détaillés |

---

## 💡 Exemples

### Exemple 1 : Scraper Nantes avec analyse IA
```bash
GROQ_API_KEY=gsk_xxx python3 scripts/interactive_scanner.py \
  --city "Nantes" \
  --query "loyer" \
  --pages 20 \
  --debug
```

Puis dans le menu: appuyez sur 's' pour scraper

### Exemple 2 : Charger et analyser en cache
```bash
# Charger le cache existant (aucun scrape)
python3 scripts/interactive_scanner.py --cache nantes_cache.json

# Sélectionnez une annonce (ex: tapez 5)
# Choisissez l'option 2 pour générer l'analyse IA
```

---

## 📊 Cache Local

Les données sont sauvegardées dans un fichier JSON (ex: `property_cache.json`):

```json
{
  "https://www.leboncoin.fr/ad/ventes_immobilieres/3110667700": {
    "url": "https://www.leboncoin.fr/ad/ventes_immobilieres/3110667700",
    "title": "Studio 25m² centre-ville",
    "price": 25000,
    "monthly_rent": 350,
    "annual_rent": 4200,
    "annual_charges": 600,
    "taxe_fonciere_annual": 200,
    "gross_yield_pct": 16.8,
    "net_yield_pct": 14.2,
    "analysis_ai": "...",
    "user_status": "👍"
  }
}
```

**Avantages:**
- ✅ Accès instantané aux annonces
- ✅ Pas de re-scrape LeBonCoin
- ✅ Historique des analyses IA
- ✅ Suivi de votre intérêt pour chaque bien

---

## 🎨 Légende du Menu

```
📊 ANALYSE  : ✅ = en cache    | ⏳ = non analysée
🎯 AVIS     : ✅🌟 = recommandé + excellent
            : ✅👍 = recommandé + bon
            : ⚠️⚠️ = neutre/à négocier
            : ❌❌ = à éviter
👤 STATUS   : 👍 = intéressé   | 👎 = pas intéressé | 🤔 = hésitation
```

---

## ⚙️ Analyse IA

Chaque annonce peut être analysée via Groq API (gratuit avec compte créé):

**Format de sortie structuré:**
```
VERDICT: [ACHETER|NEGOCIER|EVITER]
AVIS: [TRES_BONNE|BONNE|MOYENNE|MAUVAISE]
SCORE: X/10
```

**Contenu de l'analyse:**
1. Résumé du bien
2. Cohérence du prix
3. Points positifs
4. Points de vigilance
5. Analyse de rentabilité
6. Recommandation

---

## 🛠️ Scripts Disponibles

### `interactive_scanner.py` (PRINCIPAL)
Scanner interactif avec menu et cache local.

```bash
GROQ_API_KEY=xxx python3 scripts/interactive_scanner.py --pages 20
```

### `scan_lbc.py`
Scraper complet, exporte en CSV.

```bash
python3 scripts/scan_lbc.py --city "Nantes" --query "loyer" --pages 5 --out results.csv
```

### `analyze_property.py`
Analyse détaillée d'une seule annonce.

```bash
GROQ_API_KEY=xxx python3 scripts/analyze_property.py "https://www.leboncoin.fr/ad/..."
```

---

## ⚠️ Notes Importantes

### Rate Limiting LeBonCoin
- Délais adaptatifs: 2-3s entre requêtes
- Retries automatiques sur 403 (5-7s, 25-27s)
- User-Agent aléatoire pour chaque requête

### API Groq
- Gratuit (création de compte requise)
- llama-3.3-70b-versatile (modèle utilisé)
- ~1 crédit par analyse (~500 chars)

### Limitations
- Scrape uniquement catégorie "Ventes Immobilières"
- Loyer doit être détecté (patterns spécifiques)
- Rendement > 20% rejeté (détection de faux positifs)

---

## 📦 Dépendances

```
requests==2.31.0
beautifulsoup4==4.12.2
lxml==4.9.3
pandas==2.1.3
groq==0.4.1
```

Voir [requirements.txt](requirements.txt)

---

## 🐛 Troubleshooting

**"Cache vide. Utilisez l'option du menu pour scraper les annonces"**
- Solution: Tapez 's' dans le menu pour scraper

**"GROQ_API_KEY non définie"**
- Solution: `export GROQ_API_KEY="gsk_your_key"`

**"403 Forbidden sur LeBonCoin"**
- Normal: Le script réessaie automatiquement avec délais croissants
- Attendez quelques minutes si trop de requêtes

**Analyse IA vide**
- Vérifier: API key valide, réseau OK
- Vérifier les logs: `--debug`

---

## 📝 Licence

MIT - Libre d'utilisation

---

## 👨‍💻 Développement

Pour modifier/étendre:

1. Fork le projet
2. Créer une branche (`git checkout -b feature/AmazingFeature`)
3. Commit (`git commit -m 'Add AmazingFeature'`)
4. Push (`git push origin feature/AmazingFeature`)
5. Ouvrir une Pull Request

---

## 📞 Support

Pour les problèmes ou suggestions: [Ouvrir une issue](https://github.com/Ziranium/scan-lbc/issues)



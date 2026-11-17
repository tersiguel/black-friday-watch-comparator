# ⌚ Comparateur de Prix Black Friday — Montres Solaires Radio-Pilotées

Un comparateur de prix automatisé conçu pour suivre plusieurs modèles de **montres solaires radio-pilotées** (Casio Tough Solar Multi-Band 6, Citizen Eco-Drive Radio-Controlled, Seiko Solar Radio-Controlled...) en compétition pendant le Black Friday.

## ✨ Fonctionnalités

- **Multi-modèles en compétition** : Configure tes modèles candidats, leurs prix cibles et leurs prix publics officiels dans [`watches.yaml`](watches.yaml).
- **Double mode d'alimentation** :
  1. **N'importe quelle URL marchand** (Amazon, Ocarat, Montres & Co, Chrono24, Fnac, Cdiscount, Sakura Watches...) grâce à un moteur hybride 4 couches : `JSON-LD Schema.org` → `OpenGraph / Meta` → `Sélecteurs CSS & Codes Promo` → `Fallback Playwright Chromium`.
  2. **Découverte automatique par référence** : Recherche de nouvelles offres et deals sur **Dealabs** et **Idealo** à partir de la référence de chaque montre.
- **Anti-Fausse Promo & Score Black Friday (/100)** : Détecte automatiquement les prix barrés gonflés au-dessus du prix officiel et les fausses remises par rapport au plus bas historique.
- **Notifications Google Chrome (2 modes)** :
  1. **Web Push Chrome (même onglet fermé)** via `ntfy.sh` : ouvre `https://ntfy.sh/app` dans Chrome, abonne-toi à ton canal (défini par `ntfy_topic` dans `watches.yaml`) et autorise les notifications Chrome.
  2. **Notification native dans l'onglet du rapport HTML** : clique sur *« 🔔 Activer les notifications Chrome »* en haut du rapport.
- **Gratuit & 100 % Cloud via GitHub Actions** : Tourne toutes les 6 heures sans laisser ton PC allumé et publie le tableau de bord interactif sur **GitHub Pages** (`docs/index.html`).

---

## 🚀 Utilisation rapide

### 1. Lancer une analyse (ou tester en mode démo)

```bash
# Générer immédiatement le rapport avec les données de simulation Black Friday
python3 tracker.py run --demo

# Lancer le relevé réel sur toutes tes URLs et la découverte automatique
python3 tracker.py run
```

### 2. Ajouter n'importe quelle URL de montre en une commande

```bash
python3 tracker.py add-url \
  --watch casio-gwm5610u \
  --url "https://www.boulanger.com/ref/..." \
  --merchant "Boulanger"
```

### 3. Tester ta notification Google Chrome

```bash
python3 tracker.py test-notify
```

---

## ☁️ Activer l'automatisation GitHub Actions + GitHub Pages

1. Pousse ce dépôt sur ton compte GitHub.
2. Dans **Settings → Pages**, choisis **Deploy from a branch** → branche `main` → dossier `/docs`.
3. Ton rapport HTML sera accessible partout sur `https://<ton-pseudo>.github.io/<nom-du-repo>/`.
4. *(Optionnel)* Pour personnaliser ton canal secret `ntfy.sh`, modifie `ntfy_topic` dans `watches.yaml` ou ajoute un secret `NTFY_TOPIC` dans **Settings → Secrets and variables → Actions**.

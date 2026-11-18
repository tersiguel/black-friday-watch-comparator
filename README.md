# ⌚ KeepaWatch — Suivi Prix Montres (Neuf & Occasion, Frais Inclus)

Application de suivi d'évolution de prix inspirée de **Keepa**, dédiée aux références horlogères :

- **1 Fiche (Card) par référence produit** : photo studio, présentation courte, code EAN / ASIN / référence copiables et caractéristiques clés.
- **Graphique style Keepa à double courbe** :
  - **Courbe Prix Neuf** (tout frais compris)
  - **Courbe Prix Occasion** (tout frais compris)
  - Lignes pointillées des **seuils d'alerte Neuf & Occasion** et sélecteur de période (`7j`, `1 mois`, `3 mois`, `Tout`).
- **Suivi maîtrisé par l'utilisateur** : aucune page n'est ajoutée automatiquement sans votre accord. Vous ajoutez vos produits et vos URLs de pages produit directement sous le graphique.
- **Proposition de pages produit à la demande (`✨ Proposer des pages produit`)** : suggère des pages vérifiées à examiner et pré-remplir en un clic.
- **Calcul complet et pré-remplissage des frais (`Port + Frais du site + Douane`)** :
  - Lors de l'ajout d'une URL, l'application inspecte la page et pré-remplit les frais lorsqu'ils sont indiqués en clair sur le site ou issus d'un barème explicite (ex. livraison gratuite UE, frais Catawiki `9 % + 3 €`, protection Vinted, import Japon hors-UE `TVA 20 % + douane + frais transporteur`).
  - Si un frais n'est pas indiqué en clair, le champ reste libre pour votre saisie manuelle.
- **Formulaire de seuils de notification (Neuf & Occasion)** : déclenche une notification Chrome / Web Push (`ntfy.sh`) dès que le prix total passe sous votre seuil Neuf ou Occasion.

## 🚀 Commandes principales

```bash
# Mettre à jour les prix des URLs suivies et générer docs/index.html
python3 tracker.py run

# Lancer le serveur local interactif (sauvegarde directe dans watches.yaml + inspection live des URLs)
python3 tracker.py serve --port 8000

# Ajouter un produit en ligne de commande
python3 tracker.py add-watch --brand "Citizen" --name "Citizen CB1160-55W" --reference "CB1160-55W" --target-new 410 --target-used 310

# Ajouter une URL produit (avec auto-détection ou saisie des frais)
python3 tracker.py add-url --watch-id citizen-cb1160-55e --url "https://..." --condition new
```

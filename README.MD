
# G-EPI-300-MAR-3-1-projectweek-4

## Description

Plateforme web de jeux autour du cinéma développée pour le projet week Epitech PGE2 2025. Deux modes de jeu sont proposés :

- **Devine le film** : un génie qui doit trouver le film auquel on pense
- **BlindTest** : retrouvez le film à partir de sa bande-son.

Le backend est en **Python** (Flask) et le frontend en **React** (Vite).

---

## Prérequis

- Python 3.11
- pip
- Node.js et npm (pour le frontend)

---

## Installation et lancement du backend (Python)

1. Cloner le dépôt :
   ```bash
   git clone <url-du-repo>
   cd G-EPI-300-MAR-3-1-projectweek-4
   ```

2. Créer et activer un environnement virtuel Python :
   ```bash
   python -m venv venv
   # Sous Windows :
   venv\Scripts\activate
   # Sous Linux/Mac :
   source venv/bin/activate
   ```

3. Installer les dépendances :
   ```bash
   pip install -r requirements.txt
   ```

4. Lancer le backend :
   ```bash
   python backend/run_all.py
   ```

Le backend démarre sur le port 5000 (ou autre selon la configuration).

---

## Installation et lancement du frontend (React)

1. Aller dans le dossier `frontend` :
   ```bash
   cd frontend
   ```

2. Installer les dépendances :
   ```bash
   npm install
   ```

3. Lancer le serveur de développement React :
   ```bash
   npm run dev
   ```

L'application sera accessible sur [http://localhost:3000](http://localhost:3000).

---

## Auteurs

- Projet Epitech PGE2 - 2025

---

## Licence

Ce projet est sous licence Epitech.

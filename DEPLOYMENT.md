# Configuration Frontend-Backend

## Environnements

### Développement Local
- **Frontend**: `http://localhost:5173` (Vite dev server)
- **Backend**: `http://localhost:5000` (Python Flask)
- **Variable d'env**: `.env.development` utilise `VITE_API_URL=http://localhost:5000`

### Production (GitHub Pages)
- **Frontend**: `https://your-username.github.io/netfilm-chill.github.io/`
- **Backend**: À configurer avec votre URL de déploiement
- **Variable d'env**: `.env.production` - mettre à jour `VITE_API_URL` avec votre URL backend

## Instructions de Déploiement

### 1. Configuration du Backend
Le backend utilise maintenant CORS qui permet les requêtes cross-origin. Assurez-vous que:
- Les endpoints `/akinator`, `/moviegrid`, et `/blindtest` sont exposés sur le port 5000
- CORS est activé pour tous les domaines

### 2. Configuration du Frontend
Le frontend utilise les variables d'environnement Vite:
- **Développement**: Les requêtes sont proxifiées via Vite vers `localhost:5000`
- **Production**: Les requêtes vont directement à l'URL définie dans `.env.production`

### 3. Mise à jour de l'URL Backend
Avant de déployer en production, mettez à jour:
```
frontend/.env.production
VITE_API_URL=https://your-backend-url.com
```

### 4. Déployer le Frontend
```bash
cd frontend
npm install
npm run build
# Déployer le contenu de dist/ sur GitHub Pages
```

### 5. Déployer le Backend
Choisissez un service de déploiement (Render, Heroku, Railway, etc.) et configurez l'URL en conséquence.

import requests
import json
import time

# Remplace par ton Bearer token TMDB v4
TMDB_BEARER_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJhNDY5NDliMDczMjcxOWE1MTBhMjZmZDdjMGExYTNhZSIsIm5iZiI6MTc2ODIwODk5My4yOTIsInN1YiI6IjY5NjRiYTYxNWEwNTU3NGQwMWIzNTAwZiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.fCBrTPFCXQj0byoixe1sH8kEIANIjSmN0L0CjVGkMNM"

# Nombre de films/séries à extraire
NB_MOVIES = 10000

# Langue des résultats (français)
LANG = "fr-FR"

# Fichier de sortie
OUTPUT_FILE = "movies.json"

def get_tmdb_movies(bearer_token, nb_movies, lang="fr-FR"):
    movies = []
    page = 1
    headers = {"Authorization": f"Bearer {bearer_token}"}
    while len(movies) < nb_movies:
        url = f"https://api.themoviedb.org/3/discover/movie?language={lang}&sort_by=popularity.desc&page={page}"
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            print(f"Erreur TMDB: {r.status_code}")
            break
        data = r.json()
        for m in data.get("results", []):
            movie = {
                "title": m.get("title"),
                "year": m.get("release_date", "")[:4],
                "genre": None,  # Ajouté plus tard
                "director": None,  # Ajouté plus tard
                "main_actor": None,  # Ajouté plus tard
                "country": None  # Ajouté plus tard
            }
            movies.append(movie)
            if len(movies) >= nb_movies:
                break
        print(f"Page {page} : {len(movies)} films collectés...")
        page += 1
        time.sleep(0.25)  # Pour éviter d'être rate-limité
    return movies

def enrich_movie_details(movies, bearer_token, lang="fr-FR"):
    headers = {"Authorization": f"Bearer {bearer_token}"}
    for i, m in enumerate(movies):
        # Récupérer détails du film
        url = f"https://api.themoviedb.org/3/search/movie?language={lang}&query={requests.utils.quote(m['title'])}"
        r = requests.get(url, headers=headers)
        if r.status_code == 200 and r.json().get("results"):
            movie_id = r.json()["results"][0]["id"]
            # Détails
            details_url = f"https://api.themoviedb.org/3/movie/{movie_id}?language={lang}"
            credits_url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits?language={lang}"
            d = requests.get(details_url, headers=headers).json()
            c = requests.get(credits_url, headers=headers).json()
            # Genre
            if d.get("genres"): m["genre"] = d["genres"][0]["name"]
            # Pays
            if d.get("production_countries"): m["country"] = d["production_countries"][0]["name"]
            # Réalisateur
            if c.get("crew"):
                directors = [p["name"] for p in c["crew"] if p["job"] == "Director"]
                if directors: m["director"] = directors[0]
            # Acteur principal
            if c.get("cast"): m["main_actor"] = c["cast"][0]["name"]
        print(f"Enrichi {i+1}/{len(movies)} : {m['title']}")
        time.sleep(0.1)
    return movies

def main():
    print("Extraction des films populaires depuis TMDB...")
    movies = get_tmdb_movies(TMDB_BEARER_TOKEN, NB_MOVIES, LANG)
    print("Enrichissement des détails...")
    movies = enrich_movie_details(movies, TMDB_BEARER_TOKEN, LANG)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)
    print(f"Base sauvegardée dans {OUTPUT_FILE} ({len(movies)} films)")

if __name__ == "__main__":
    main()

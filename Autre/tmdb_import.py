import requests
import time

TMDB_API_KEY = ""  # Mets ta clé TMDB ici (ou charge-la depuis un fichier sécurisé)

# Attributs à extraire pour chaque film
ATTRS = ["title", "release_date", "genre_ids", "original_language", "overview", "popularity", "vote_average", "vote_count", "id"]

# Récupère la liste des genres (id -> nom)
def get_genres():
    url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=fr-FR"
    r = requests.get(url)
    genres = {g['id']: g['name'] for g in r.json().get('genres', [])}
    return genres

# Récupère les films populaires (ou par page)
def get_movies(pages=5):
    movies = []
    for page in range(1, pages+1):
        url = f"https://api.themoviedb.org/3/movie/popular?api_key={TMDB_API_KEY}&language=fr-FR&page={page}"
        r = requests.get(url)
        for m in r.json().get('results', []):
            movie = {k: m.get(k) for k in ATTRS}
            movies.append(movie)
        time.sleep(0.2)  # Pour éviter le rate limit
    return movies

# Enrichit chaque film avec les noms des genres
def enrich_movies(movies, genres):
    for m in movies:
        m['genres'] = [genres.get(gid, str(gid)) for gid in m.get('genre_ids', [])]
    return movies

if __name__ == "__main__":
    genres = get_genres()
    movies = get_movies(pages=10)  # Récupère 200 films populaires
    movies = enrich_movies(movies, genres)
    # Sauvegarde dans un fichier JSON
    import json
    with open("films_tmdb.json", "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)
    print(f"Exporté {len(movies)} films dans films_tmdb.json")

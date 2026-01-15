import os
import requests
from typing import List, Dict, Optional

_TMDB_BEARER = os.environ.get('TMDB_BEARER')
_TOKEN_FILE = os.path.join(os.path.dirname(__file__), '.tmdb_token')
if not _TMDB_BEARER and os.path.exists(_TOKEN_FILE):
    try:
        with open(_TOKEN_FILE, 'r', encoding='utf-8') as f:
            _TMDB_BEARER = f.read().strip()
    except Exception:
        _TMDB_BEARER = None

# If still not present, fall back to a hard-coded token (user provided)
if not _TMDB_BEARER:
    # NOTE: token is embedded per user request. Replace if you want to keep it secret.
    _TMDB_BEARER = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJhNDY5NDliMDczMjcxOWE1MTBhMjZmZDdjMGExYTNhZSIsIm5iZiI6MTc2ODIwODk5My4yOTIsInN1YiI6IjY5NjRiYTYxNWEwNTU3NGQwMWIzNTAwZiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.fCBrTPFCXQj0byoixe1sH8kEIANIjSmN0L0CjVGkMNM"

    # also persist for convenience
    try:
        with open(_TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(_TMDB_BEARER)
    except Exception:
        pass

API_BASE = 'https://api.themoviedb.org/3'
HEADERS = {'Authorization': f'Bearer {_TMDB_BEARER}', 'Accept': 'application/json'}

_GENRE_MAP = {}

def load_genres():
    global _GENRE_MAP
    try:
        r = requests.get(f'{API_BASE}/genre/movie/list', headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for g in data.get('genres', []):
                _GENRE_MAP[g['id']] = g['name']
    except Exception:
        _GENRE_MAP = {}

def short_movie_str(m: Dict) -> str:
    title = m.get('title') or m.get('original_title') or ''
    year = ''
    if m.get('release_date'):
        year = f" ({m.get('release_date')[:4]})"
    return f"{title}{year}"

def discover_movies(pages: int = 5) -> List[Dict]:
    # use popular movies endpoint as pool
    out = []
    per = max(1, pages)
    for p in range(1, per+1):
        try:
            r = requests.get(f'{API_BASE}/movie/popular?page={p}', headers=HEADERS, timeout=10)
            if r.status_code != 200:
                break
            data = r.json()
            for m in data.get('results', []):
                # fetch full details for each movie to provide richer fields
                details = get_details(m.get('id'))
                if details:
                    out.append(details)
                else:
                    out.append({
                        'id': m.get('id'),
                        'title': m.get('title'),
                        'original_title': m.get('original_title'),
                        'release_date': m.get('release_date'),
                        'genres': [{'id': gid, 'name': _GENRE_MAP.get(gid, '')} for gid in m.get('genre_ids', [])],
                        'popularity': m.get('popularity'),
                        'vote_average': m.get('vote_average'),
                    })
        except Exception:
            break
    return out

def get_details(movie_id: int) -> Dict:
    # append credits, keywords
    try:
        r = requests.get(f'{API_BASE}/movie/{movie_id}?append_to_response=credits,keywords,release_dates', headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()
        # normalize some fields similar to the sqlite version
        return data
    except Exception:
        return {}

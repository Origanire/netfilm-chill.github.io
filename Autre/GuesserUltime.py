#!/usr/bin/env python3
import argparse
import math
import json
import os
import random
import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple, Set, Any

# =========================
# SQLITE ACCESS
# =========================

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "movies.db")
_conn: Optional[sqlite3.Connection] = None

GENRE_MAP: Dict[int, str] = {}
DETAILS_CACHE: Dict[int, dict] = {}

def get_connection(db_path: str) -> sqlite3.Connection:
    """Crée une nouvelle connexion à la base de données avec optimisations SQLite (thread-safe)."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # OPTIMISATIONS pour vitesse maximale
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = 10000")
    return conn

def close_connection() -> None:
    """Ferme la connexion à la base de données."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None

def load_genres(conn: sqlite3.Connection) -> None:
    """Charge les genres depuis la base de données."""
    global GENRE_MAP
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name FROM genres")
        GENRE_MAP = {row["id"]: row["name"] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        GENRE_MAP = {}

def discover_movies(conn: sqlite3.Connection, pages: Optional[int] = None) -> List[dict]:
    """
    Charge les films avec leurs genres depuis les tables relationnelles.
    OPTIMISATION: 1 seule requête pour tous les genres au lieu de N requêtes.
    """
    cursor = conn.cursor()

    # OPTIMISATION MAJEURE: Charger tous les genres en UNE requête
    cursor.execute("SELECT movie_id, genre_id FROM movie_genres")
    genre_rows = cursor.fetchall()
    
    # Construire un dictionnaire movie_id -> [genre_ids]
    movie_genres_map: Dict[int, List[int]] = {}
    for row in genre_rows:
        mid = row["movie_id"]
        gid = row["genre_id"]
        if mid not in movie_genres_map:
            movie_genres_map[mid] = []
        movie_genres_map[mid].append(gid)

    # Charger les films
    if pages:
        limit = pages * 20
        cursor.execute(
            "SELECT * FROM movies ORDER BY popularity DESC LIMIT ?",
            (limit,),
        )
    else:
        cursor.execute("SELECT * FROM movies ORDER BY popularity DESC")

    movies: List[dict] = []
    rows = cursor.fetchall()
    
    for row in rows:
        movie = dict(row)
        movie_id = movie.get("id")
        # Utiliser le dictionnaire (instantané) au lieu de faire une requête SQL
        movie["genre_ids"] = movie_genres_map.get(movie_id, [])
        movies.append(movie)

    return movies

def get_details(conn: sqlite3.Connection, movie_id: int) -> dict:
    """
    Récupère les détails complets d'un film depuis la base de données.
    Cache agressif pour éviter des allers-retours SQLite.
    """
    if movie_id in DETAILS_CACHE:
        return DETAILS_CACHE[movie_id]

    cursor = conn.cursor()

    cursor.execute("SELECT * FROM movies WHERE id = ?", (movie_id,))
    row = cursor.fetchone()
    if row is None:
        return {}

    details = dict(row)

    # Genres
    cursor.execute(
        """
        SELECT g.id, g.name
        FROM movie_genres mg
        JOIN genres g ON mg.genre_id = g.id
        WHERE mg.movie_id = ?
        """,
        (movie_id,),
    )
    genre_rows = cursor.fetchall()
    details["genre_ids"] = [r["id"] for r in genre_rows]
    details["genres"] = [{"id": r["id"], "name": r["name"]} for r in genre_rows]

    # Keywords
    cursor.execute(
        """
        SELECT k.id, k.name
        FROM movie_keywords mk
        JOIN keywords k ON mk.keyword_id = k.id
        WHERE mk.movie_id = ?
        """,
        (movie_id,),
    )
    keyword_rows = cursor.fetchall()
    details["keywords"] = {
        "keywords": [{"id": r["id"], "name": r["name"]} for r in keyword_rows]
    }

    # Cast
    cursor.execute(
        """
        SELECT p.id, p.name, mc.character, mc.cast_order
        FROM movie_cast mc
        JOIN people p ON mc.person_id = p.id
        WHERE mc.movie_id = ?
        ORDER BY mc.cast_order
        """,
        (movie_id,),
    )
    cast_rows = cursor.fetchall()

    # Crew
    cursor.execute(
        """
        SELECT p.id, p.name, cr.job, cr.department
        FROM movie_crew cr
        JOIN people p ON cr.person_id = p.id
        WHERE cr.movie_id = ?
        """,
        (movie_id,),
    )
    crew_rows = cursor.fetchall()

    details["credits"] = {
        "cast": [
            {
                "id": r["id"],
                "name": r["name"],
                "character": r["character"],
                "order": r["cast_order"],
            }
            for r in cast_rows
        ],
        "crew": [
            {"id": r["id"], "name": r["name"], "job": r["job"], "department": r["department"]}
            for r in crew_rows
        ],
    }

    # Production countries (si présent)
    countries_str = details.get("countries")
    if countries_str:
        try:
            countries = json.loads(countries_str)
            details["production_countries"] = [{"iso_3166_1": c, "name": c} for c in countries]
        except Exception:
            details["production_countries"] = []
    else:
        details["production_countries"] = []

    # Collection
    if details.get("collection_id"):
        details["belongs_to_collection"] = {
            "id": details["collection_id"],
            "name": details.get("collection_name"),
        }

    DETAILS_CACHE[movie_id] = details
    return details


# =========================
# Utils
# =========================

def safe_year(release_date: Optional[str]) -> Optional[int]:
    if not release_date:
        return None
    try:
        return int(str(release_date)[:4])
    except ValueError:
        return None

def normalize_title(title: str) -> str:
    """
    Normalisation agressive (articles + ponctuation + casing).
    Exemple: "Marvel's The Avengers" -> "MARVELSTHEAVENGERS" puis article retiré -> "MARVELSTHEAVENGERS"
    et pour les tests de "starts_with", on retire les articles au début avant suppression.
    """
    t = str(title).strip()
    t = re.sub(r"^(the|a|an|le|la|les|l'|un|une|des)\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[^A-Za-z0-9]", "", t)
    return t.upper()

def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def movie_id(m: dict) -> Optional[int]:
    mid = m.get("id")
    if mid is None:
        return None
    try:
        return int(mid)
    except Exception:
        return None


# =========================
# Question model + quality scoring
# =========================

def entropy_split(yes: int, no: int) -> float:
    n = yes + no
    if n == 0:
        return 0.0

    def h(x: int) -> float:
        if x == 0:
            return 0.0
        p = x / n
        return -p * math.log2(p)

    return h(yes) + h(no)

def split_counts(candidates: List[dict], predicate: Callable[[dict], Optional[bool]]) -> Tuple[int, int, int]:
    yes = no = unk = 0
    for m in candidates:
        r = predicate(m)
        if r is True:
            yes += 1
        elif r is False:
            no += 1
        else:
            unk += 1
    return yes, no, unk

@dataclass(frozen=True)
class Question:
    key: str
    text: str
    predicate: Callable[[dict], Optional[bool]]
    # NOUVEAU: dépendances logiques
    requires: Optional[Set[str]] = None  # questions qui doivent avoir été posées
    excludes: Optional[Set[str]] = None  # questions qui excluent celle-ci

    def score(self, candidates: List[dict]) -> float:
        """
        Calcule le score de discrimination de cette question.
        OPTIMISATION: Échantillonne si trop de candidats pour gagner du temps.
        """
        # OPTIMISATION: Sur grande liste, échantillonner pour calculer plus vite
        sample = candidates
        if len(candidates) > 500:
            sample = candidates[:500]  # Prendre les 500 premiers (déjà triés par score)
        
        yes, no, unk = split_counts(sample, self.predicate)

        if (yes == 0 and unk == 0) or (no == 0 and unk == 0):
            return -1.0

        base = entropy_split(yes, no)

        n = len(sample)
        unk_ratio = (unk / n) if n else 1.0
        score = base - 0.35 * unk_ratio

        # boosters (garde l'esprit de ton code)
        if self.key.startswith(("director_", "dyn_director_")):
            score *= 1.5
        elif self.key.startswith(("franchise_",)):
            score *= 1.6  # Augmenté de 1.4 à 1.6 pour mieux détecter les franchises
        elif self.key.startswith(("char_",)):
            score *= 1.35
        elif self.key.startswith(("actor_", "dyn_actor_")):
            if 0 < yes < n:
                score *= 1.3
        elif self.key.startswith(("location_", "event_", "object_")):
            score *= 1.25
        elif self.key.startswith("joker_title_") and n <= 10:
            score *= 1.2

        return score


def choose_best_question(candidates: List[dict], questions: List[Question], asked: Set[str]) -> Optional[Question]:
    """
    Choisit la meilleure question de manière déterministe et RAPIDE.
    OPTIMISATION: Échantillonne si trop de questions pour éviter de tout scorer.
    """
    contradictions = {
        "big_budget": "small_budget",
        "small_budget": "big_budget",
        "runtime_lt_90": "runtime_ge_150",
        "runtime_ge_150": "runtime_lt_90",
        "is_animation": "is_live_action",
        "is_live_action": "is_animation",
        "is_saga": "is_standalone",
        "is_standalone": "is_saga",
        "after_1980": "before_1970",
        "after_2000": "before_1990",
        "after_2020": "before_2010",
    }

    jokers_used = sum(1 for q in asked if q.startswith("joker_title_"))

    # Filtrer les questions valides
    valid_questions = []
    for q in questions:
        if q.key in asked:
            continue
        if q.requires and not q.requires.issubset(asked):
            continue
        if q.excludes and q.excludes.intersection(asked):
            continue
        if q.key.startswith("joker_title_") and jokers_used >= 1:
            continue
        if q.key in contradictions and contradictions[q.key] in asked:
            continue
        valid_questions.append(q)
    
    if not valid_questions:
        return None
    
    # OPTIMISATION CRITIQUE: Si trop de questions, échantillonner pour scorer plus vite
    if len(valid_questions) > 150:
        # Prendre les 150 premières (déjà triées par priorité généralement)
        valid_questions = valid_questions[:150]

    scored: List[Tuple[Question, float]] = []
    for q in valid_questions:
        s = q.score(candidates)
        if s > 0:
            scored.append((q, s))

    if not scored:
        return None

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]


# =========================
# Predicates - ANNÉE
# =========================

def pred_after_year(year: int) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        y = safe_year(m.get("release_date"))
        if y is None:
            return None
        return y > year
    return p

def pred_before_year(year: int) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        y = safe_year(m.get("release_date"))
        if y is None:
            return None
        return y < year
    return p


# =========================
# Predicates - ULTRA-DISCRIMINANTS
# =========================

def pred_has_director(conn: sqlite3.Connection, director_name: str) -> Callable[[dict], Optional[bool]]:
    """Vérifie si un réalisateur spécifique a fait le film."""
    dn = director_name.lower()

    def p(m: dict) -> Optional[bool]:
        mid = movie_id(m)
        if mid is None:
            return None
        d = get_details(conn, mid)
        crew = d.get("credits", {}).get("crew", [])
        if not crew:
            return None
        directors = [c.get("name", "").lower() for c in crew if isinstance(c, dict) and c.get("job") == "Director"]
        return dn in directors
    return p

def pred_franchise_name(conn: sqlite3.Connection, franchise: str) -> Callable[[dict], Optional[bool]]:
    fn = franchise.lower()

    def p(m: dict) -> Optional[bool]:
        mid = movie_id(m)
        if mid is None:
            return None
        
        # D'abord vérifier le titre (souvent plus fiable)
        title = m.get("title", "")
        if fn in str(title).lower():
            return True
            
        # Ensuite vérifier la collection
        d = get_details(conn, mid)
        collection = d.get("belongs_to_collection")
        if collection:
            collection_name = str(collection.get("name", "")).lower()
            if fn in collection_name:
                return True
        
        # Si on n'a rien trouvé, vérifier les keywords
        keywords = d.get("keywords", {}).get("keywords", [])
        if isinstance(keywords, list):
            for kw in keywords:
                if isinstance(kw, dict):
                    kw_name = kw.get("name", "").lower()
                    if fn in kw_name:
                        return True
        
        # Si toujours rien, retourner False seulement si on a des données
        # Retourner None si on n'a aucune donnée pertinente
        if collection or keywords:
            return False
        return None
    return p

def pred_main_character_name(conn: sqlite3.Connection, char_keyword: str) -> Callable[[dict], Optional[bool]]:
    ck = char_keyword.lower()

    def p(m: dict) -> Optional[bool]:
        mid = movie_id(m)
        if mid is None:
            return None
        d = get_details(conn, mid)

        keywords = d.get("keywords", {}).get("keywords", [])
        if isinstance(keywords, list):
            names = [k.get("name", "").lower() for k in keywords if isinstance(k, dict)]
            if any(ck in kw for kw in names):
                return True

        cast = d.get("credits", {}).get("cast", [])
        if isinstance(cast, list):
            chars = [c.get("character", "").lower() for c in cast if isinstance(c, dict)]
            if any(ck in ch for ch in chars):
                return True

        return None
    return p


def pred_is_harry_potter(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    """Détection spécifique et robuste pour Harry Potter."""
    def p(m: dict) -> Optional[bool]:
        # Vérifier le titre en priorité
        title = str(m.get("title", "")).lower()
        if "harry potter" in title:
            return True
        
        mid = movie_id(m)
        if mid is None:
            return None
        
        d = get_details(conn, mid)
        
        # Vérifier la collection
        collection = d.get("belongs_to_collection")
        if collection:
            col_name = str(collection.get("name", "")).lower()
            if "harry potter" in col_name or "wizarding world" in col_name:
                return True
        
        # Vérifier les keywords
        keywords = d.get("keywords", {}).get("keywords", [])
        if isinstance(keywords, list):
            for kw in keywords:
                if isinstance(kw, dict):
                    kw_name = kw.get("name", "").lower()
                    if "harry potter" in kw_name or "hogwarts" in kw_name:
                        return True
        
        # Vérifier le cast pour les acteurs principaux
        cast = d.get("credits", {}).get("cast", [])
        if isinstance(cast, list):
            top_actors = [c.get("name", "").lower() for c in cast[:5] if isinstance(c, dict)]
            hp_actors = {"daniel radcliffe", "emma watson", "rupert grint"}
            # Si au moins 2 des 3 acteurs principaux sont présents
            matches = sum(1 for actor in hp_actors if any(actor in ta for ta in top_actors))
            if matches >= 2:
                return True
        
        return False
    return p


# =========================
# Predicates - TITRE (JOKERS)
# =========================

def pred_title_starts_with(letter: str) -> Callable[[dict], Optional[bool]]:
    l = str(letter).upper()

    def p(m: dict) -> Optional[bool]:
        title = m.get("title")
        if not title:
            return None
        nt = normalize_title(title)
        if not nt:
            return None
        return nt.startswith(l)
    return p

def pred_title_contains_word(word: str) -> Callable[[dict], Optional[bool]]:
    w = re.sub(r"\s+", " ", str(word)).strip().lower()

    def p(m: dict) -> Optional[bool]:
        title = m.get("title")
        if not title:
            return None
        return w in str(title).lower()
    return p


# =========================
# Predicates - GENRE
# =========================

def pred_has_genre(conn: sqlite3.Connection, name: str) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        gids = m.get("genre_ids")
        if isinstance(gids, list) and gids:
            names = [GENRE_MAP.get(int(gid)) for gid in gids if gid is not None]
            names = [n for n in names if n]
            if names:
                return name in names

        mid = movie_id(m)
        if mid is None:
            return None
        d = get_details(conn, mid)
        genres = d.get("genres", [])
        if not isinstance(genres, list):
            return None
        names = [g.get("name") for g in genres if isinstance(g, dict)]
        if not names:
            return None
        return name in names
    return p

def pred_is_animation(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    return pred_has_genre(conn, "Animation")

def pred_not_animation(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    base = pred_is_animation(conn)
    def p(m: dict) -> Optional[bool]:
        r = base(m)
        if r is None:
            return None
        return not r
    return p


# =========================
# Predicates - DURÉE
# =========================

def pred_runtime_lt(conn: sqlite3.Connection, minutes: int) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        runtime = m.get("runtime")
        if runtime is None:
            mid = movie_id(m)
            if mid is not None:
                runtime = get_details(conn, mid).get("runtime")
        if runtime is None:
            return None
        return int(runtime) < minutes
    return p

def pred_runtime_ge(conn: sqlite3.Connection, minutes: int) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        runtime = m.get("runtime")
        if runtime is None:
            mid = movie_id(m)
            if mid is not None:
                runtime = get_details(conn, mid).get("runtime")
        if runtime is None:
            return None
        return int(runtime) >= minutes
    return p

def pred_is_short(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    return pred_runtime_lt(conn, 45)

def pred_is_feature(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    return pred_runtime_ge(conn, 60)


# =========================
# Predicates - ORIGINE / LANGUE
# =========================

def pred_is_american(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        mid = movie_id(m)
        if mid is None:
            return None
        countries = get_details(conn, mid).get("production_countries", [])
        if not isinstance(countries, list):
            return None
        return any(c.get("iso_3166_1") == "US" for c in countries if isinstance(c, dict))
    return p

def pred_is_french(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        mid = movie_id(m)
        if mid is None:
            return None
        countries = get_details(conn, mid).get("production_countries", [])
        if not isinstance(countries, list):
            return None
        return any(c.get("iso_3166_1") == "FR" for c in countries if isinstance(c, dict))
    return p

def pred_is_european(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    EUROPEAN_CODES = {"GB", "FR", "DE", "IT", "ES", "NL", "BE", "CH", "AT", "SE", "NO", "DK", "FI", "PL", "CZ", "IE", "PT", "GR"}
    def p(m: dict) -> Optional[bool]:
        mid = movie_id(m)
        if mid is None:
            return None
        countries = get_details(conn, mid).get("production_countries", [])
        if not isinstance(countries, list):
            return None
        return any(c.get("iso_3166_1") in EUROPEAN_CODES for c in countries if isinstance(c, dict))
    return p

def pred_is_asian(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    ASIAN_CODES = {"JP", "KR", "CN", "TW", "HK", "TH", "IN", "ID", "MY", "SG", "PH"}
    def p(m: dict) -> Optional[bool]:
        mid = movie_id(m)
        if mid is None:
            return None
        countries = get_details(conn, mid).get("production_countries", [])
        if not isinstance(countries, list):
            return None
        return any(c.get("iso_3166_1") in ASIAN_CODES for c in countries if isinstance(c, dict))
    return p

def pred_language(lang_code: str) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        lang = m.get("original_language")
        if not lang:
            return None
        return str(lang) == lang_code
    return p


# =========================
# Predicates - POPULARITÉ / NOTES
# =========================

def pred_vote_average_ge(th: float) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        v = m.get("vote_average")
        if v is None:
            return None
        try:
            return float(v) >= th
        except Exception:
            return None
    return p

def pred_popularity_ge(th: float) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        v = m.get("popularity")
        if v is None:
            return None
        try:
            return float(v) >= th
        except Exception:
            return None
    return p

def pred_vote_count_ge(th: int) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        v = m.get("vote_count")
        if v is None:
            return None
        try:
            return int(v) >= th
        except Exception:
            return None
    return p


# =========================
# Predicates - BUDGET / REVENUS
# =========================

def pred_budget_ge(conn: sqlite3.Connection, th: int) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        budget = m.get("budget")
        if budget is None:
            mid = movie_id(m)
            if mid is not None:
                budget = get_details(conn, mid).get("budget")
        if budget in (None, 0):
            return None
        return int(budget) >= th
    return p

def pred_budget_lt(conn: sqlite3.Connection, th: int) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        budget = m.get("budget")
        if budget is None:
            mid = movie_id(m)
            if mid is not None:
                budget = get_details(conn, mid).get("budget")
        if budget in (None, 0):
            return None
        return int(budget) < th
    return p

def pred_revenue_ge(conn: sqlite3.Connection, th: int) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        revenue = m.get("revenue")
        if revenue is None:
            mid = movie_id(m)
            if mid is not None:
                revenue = get_details(conn, mid).get("revenue")
        if revenue in (None, 0):
            return None
        return int(revenue) >= th
    return p

def pred_is_indie(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        budget = m.get("budget")
        if budget is None:
            mid = movie_id(m)
            if mid is not None:
                budget = get_details(conn, mid).get("budget")
        if budget in (None, 0):
            return None
        return int(budget) < 5_000_000
    return p


# =========================
# Predicates - SAGA / COLLECTION
# =========================

def pred_is_saga(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        mid = movie_id(m)
        if mid is None:
            return None
        d = get_details(conn, mid)
        return d.get("belongs_to_collection") is not None
    return p

def pred_not_saga(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    base = pred_is_saga(conn)
    def p(m: dict) -> Optional[bool]:
        r = base(m)
        if r is None:
            return None
        return not r
    return p


# =========================
# Predicates - KEYWORDS
# =========================

def pred_keyword(conn: sqlite3.Connection, keyword: str) -> Callable[[dict], Optional[bool]]:
    k = keyword.lower()
    def p(m: dict) -> Optional[bool]:
        mid = movie_id(m)
        if mid is None:
            return None
        keywords = get_details(conn, mid).get("keywords", {}).get("keywords", [])
        if not isinstance(keywords, list):
            return None
        names = [kw.get("name", "").lower() for kw in keywords if isinstance(kw, dict)]
        return k in " ".join(names)
    return p

def pred_is_adaptation(conn: sqlite3.Connection) -> Callable[[dict], Optional[bool]]:
    p1 = pred_keyword(conn, "based on novel")
    p2 = pred_keyword(conn, "based on comic")
    p3 = pred_keyword(conn, "based on true story")
    def p(m: dict) -> Optional[bool]:
        r1, r2, r3 = p1(m), p2(m), p3(m)
        if r1 is True or r2 is True or r3 is True:
            return True
        if r1 is None and r2 is None and r3 is None:
            return None
        return False
    return p


# =========================
# Predicates - CLASSIFICATION
# =========================

def pred_is_adult() -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        adult = m.get("adult")
        if adult is None:
            return None
        return adult is True
    return p

def pred_actor_in_cast(conn: sqlite3.Connection, actor_name: str) -> Callable[[dict], Optional[bool]]:
    an = actor_name.lower()

    def p(m: dict) -> Optional[bool]:
        mid = movie_id(m)
        if mid is None:
            return None
        d = get_details(conn, mid)
        cast = d.get("credits", {}).get("cast", [])
        if not cast:
            return None
        actors = [c.get("name", "").lower() for c in cast if isinstance(c, dict)]
        return an in actors
    return p


# =========================
# Default questions (statiques) - VERSION AMÉLIORÉE
# =========================

def default_questions(conn: sqlite3.Connection) -> List[Question]:
    return [
        # TYPE / FORMAT
        Question("is_animation", "Est-ce que c'est un film d'animation ?", pred_is_animation(conn)),
        Question("is_live_action", "Est-ce que c'est un film en live-action ?", pred_not_animation(conn)),
        Question("is_short", "Est-ce que c'est un court-métrage ?", pred_is_short(conn)),
        Question("is_feature", "Est-ce que c'est un long-métrage ?", pred_is_feature(conn)),

        # ÉPOQUE / SORTIE
        Question("after_1980", "Est-ce que c'est sorti après 1980 ?", pred_after_year(1980)),
        Question("after_2000", "Est-ce que c'est sorti après 2000 ?", pred_after_year(2000)),
        Question("after_2020", "Est-ce que c'est sorti après 2020 ?", pred_after_year(2020)),

        # GENRES
        Question("genre_action", "Est-ce que c'est un film d'action ?", pred_has_genre(conn, "Action")),
        Question("genre_adventure", "Y a-t-il des voyages, quêtes ou explorations ?", pred_has_genre(conn, "Adventure")),
        Question("genre_comedy", "Est-ce que c'est une comédie ?", pred_has_genre(conn, "Comedy")),
        Question("genre_drama", "Est-ce principalement un drame (film émotionnel/sérieux) ?", pred_has_genre(conn, "Drama")),
        Question("genre_fantasy", "Y a-t-il de la magie ou du fantastique ?", pred_has_genre(conn, "Fantasy")),
        Question("genre_horror", "Est-ce que c'est un film d'horreur ?", pred_has_genre(conn, "Horror")),
        Question("genre_mystery", "Est-ce que c'est un film à mystère ?", pred_has_genre(conn, "Mystery")),
        Question("genre_romance", "Est-ce que c'est une romance ?", pred_has_genre(conn, "Romance")),
        Question("genre_scifi", "Y a-t-il de la SF (technologie futuriste, aliens, espace) ?", pred_has_genre(conn, "Science Fiction")),
        Question("genre_thriller", "Est-ce un film à suspense/mystère ?", pred_has_genre(conn, "Thriller")),
        Question("genre_crime", "Est-ce que c'est un film criminel ?", pred_has_genre(conn, "Crime")),
        Question("genre_family", "Est-ce que c'est un film familial ?", pred_has_genre(conn, "Family")),
        Question("genre_war", "Est-ce que c'est un film de guerre ?", pred_has_genre(conn, "War")),
        Question("genre_history", "Est-ce que c'est un film historique ?", pred_has_genre(conn, "History")),
        Question("genre_music", "Est-ce que la musique est centrale ?", pred_has_genre(conn, "Music")),
        Question("genre_documentary", "Est-ce que c'est un documentaire ?", pred_has_genre(conn, "Documentary")),

        # PUBLIC / ÂGE
        Question("is_adult", "Est-ce que c'est un film pour adultes ?", pred_is_adult()),

        # DURÉE
        Question("runtime_lt_90", "Est-ce que le film dure moins de 1h30 ?", pred_runtime_lt(conn, 90)),
        Question("runtime_ge_150", "Est-ce que le film dure plus de 2h30 ?", pred_runtime_ge(conn, 150)),

        # ORIGINE / LANGUE - AVEC EXCLUSIONS LOGIQUES
        Question("is_american", "Est-ce que c'est un film américain ?", pred_is_american(conn)),
        Question("is_french", "Est-ce que c'est un film français ?", pred_is_french(conn)),
        Question("is_european", "Est-ce que c'est un film européen ?", pred_is_european(conn)),
        Question("is_asian", "Est-ce que c'est un film asiatique ?", pred_is_asian(conn)),
        
        # Si langue anglaise confirmée, ne pas demander les autres langues
        Question("language_en", "La langue originale est-elle l'anglais ?", pred_language("en")),
        Question("language_fr", "La langue originale est-elle le français ?", pred_language("fr"), 
                excludes={"language_en"}),  # NOUVEAU: exclusion logique
        Question("language_ja", "La langue originale est-elle le japonais ?", pred_language("ja"),
                excludes={"language_en", "language_fr"}),  # NOUVEAU: exclusion logique
        Question("language_es", "La langue originale est-elle l'espagnol ?", pred_language("es"),
                excludes={"language_en", "language_fr", "language_ja"}),
        Question("language_de", "La langue originale est-elle l'allemand ?", pred_language("de"),
                excludes={"language_en", "language_fr", "language_ja", "language_es"}),

        # SUCCÈS / POPULARITÉ
        Question("popular", "Est-ce que c'est un film très populaire ?", pred_popularity_ge(50)),
        Question("very_popular", "Est-ce que c'est un film culte ou ultra connu ?", pred_popularity_ge(80)),

        # FINANCES - AVEC EXCLUSIONS LOGIQUES
        Question("big_budget", "Est-ce que le film a un gros budget ?", pred_budget_ge(conn, 50_000_000)),
        Question("small_budget", "Est-ce que le film a un petit budget ?", pred_budget_lt(conn, 10_000_000),
                excludes={"big_budget"}),  # NOUVEAU: si gros budget, ne pas demander petit budget
        Question("box_office_success", "Est-ce que le film a bien marché au box-office ?", pred_revenue_ge(conn, 100_000_000)),
        Question("is_indie", "Est-ce que c'est un film indépendant ?", pred_is_indie(conn),
                excludes={"big_budget"}),  # NOUVEAU: si gros budget, pas indé

        # FRANCHISE / ADAPTATION
        Question("is_saga", "Le film fait-il partie d'une série/franchise (avec suites/prequels) ?", pred_is_saga(conn)),
        Question("is_standalone", "Est-ce que c'est un film unique ?", pred_not_saga(conn)),
        Question("is_adaptation", "Est-ce que c'est une adaptation ?", pred_is_adaptation(conn)),
        Question("based_on_book", "Est-ce que c'est basé sur un livre ?", pred_keyword(conn, "based on novel")),
        Question("based_on_comic", "Est-ce que c'est basé sur un comic ?", pred_keyword(conn, "based on comic")),
        Question("based_on_true_story", "Est-ce que c'est basé sur une histoire vraie ?", pred_keyword(conn, "based on true story")),
        Question("superhero", "Est-ce que c'est un film de super-héros ?", pred_keyword(conn, "superhero")),

        # JOKERS TITRE
        Question("joker_title_a_d", "Le titre commence-t-il par A, B, C ou D ?",
                 lambda m: pred_title_starts_with("A")(m) or pred_title_starts_with("B")(m) or
                           pred_title_starts_with("C")(m) or pred_title_starts_with("D")(m)),
        Question("joker_title_e_h", "Le titre commence-t-il par E, F, G ou H ?",
                 lambda m: pred_title_starts_with("E")(m) or pred_title_starts_with("F")(m) or
                           pred_title_starts_with("G")(m) or pred_title_starts_with("H")(m)),
        Question("joker_title_i_l", "Le titre commence-t-il par I, J, K ou L ?",
                 lambda m: pred_title_starts_with("I")(m) or pred_title_starts_with("J")(m) or
                           pred_title_starts_with("K")(m) or pred_title_starts_with("L")(m)),
        Question("joker_title_m_p", "Le titre commence-t-il par M, N, O ou P ?",
                 lambda m: pred_title_starts_with("M")(m) or pred_title_starts_with("N")(m) or
                           pred_title_starts_with("O")(m) or pred_title_starts_with("P")(m)),
        Question("joker_title_q_t", "Le titre commence-t-il par Q, R, S ou T ?",
                 lambda m: pred_title_starts_with("Q")(m) or pred_title_starts_with("R")(m) or
                           pred_title_starts_with("S")(m) or pred_title_starts_with("T")(m)),
        Question("joker_title_u_z", "Le titre commence-t-il par U, V, W, X, Y ou Z ?",
                 lambda m: pred_title_starts_with("U")(m) or pred_title_starts_with("V")(m) or
                           pred_title_starts_with("W")(m) or pred_title_starts_with("X")(m) or
                           pred_title_starts_with("Y")(m) or pred_title_starts_with("Z")(m)),

        # RÉALISATEURS CÉLÈBRES
        Question("director_nolan", "Est-ce que c'est réalisé par Christopher Nolan ?", pred_has_director(conn, "Christopher Nolan")),
        Question("director_spielberg", "Est-ce que c'est réalisé par Steven Spielberg ?", pred_has_director(conn, "Steven Spielberg")),
        Question("director_tarantino", "Est-ce que c'est réalisé par Quentin Tarantino ?", pred_has_director(conn, "Quentin Tarantino")),
        Question("director_scorsese", "Est-ce que c'est réalisé par Martin Scorsese ?", pred_has_director(conn, "Martin Scorsese")),
        Question("director_fincher", "Est-ce que c'est réalisé par David Fincher ?", pred_has_director(conn, "David Fincher")),
        Question("director_cameron", "Est-ce que c'est réalisé par James Cameron ?", pred_has_director(conn, "James Cameron")),
        Question("director_jackson", "Est-ce que c'est réalisé par Peter Jackson ?", pred_has_director(conn, "Peter Jackson")),
        Question("director_ridley_scott", "Est-ce que c'est réalisé par Ridley Scott ?", pred_has_director(conn, "Ridley Scott")),
        Question("director_chris_columbus", "Est-ce que c'est réalisé par Chris Columbus ?", pred_has_director(conn, "Chris Columbus")),  # NOUVEAU: Harry Potter
        Question("director_david_yates", "Est-ce que c'est réalisé par David Yates ?", pred_has_director(conn, "David Yates")),  # NOUVEAU: Harry Potter

        # FRANCHISES POPULAIRES - QUESTIONS AMÉLIORÉES ET AJOUTS
        Question("franchise_marvel", "Est-ce un film Marvel (MCU) ?", pred_franchise_name(conn, "Marvel")),
        Question("franchise_star_wars", "Est-ce un film Star Wars ?", pred_franchise_name(conn, "Star Wars")),
        Question("franchise_harry_potter", "Est-ce un film Harry Potter ?", pred_is_harry_potter(conn)),  # AMÉLIORÉ avec fonction spécifique
        Question("franchise_wizarding_world", "Est-ce un film du Monde des Sorciers (Harry Potter/Fantastic Beasts) ?", pred_franchise_name(conn, "Wizarding World")),  # NOUVEAU
        Question("franchise_lord_rings", "Est-ce un film Le Seigneur des Anneaux ?", pred_franchise_name(conn, "Lord of the Rings")),
        Question("franchise_hobbit", "Est-ce un film Le Hobbit ?", pred_franchise_name(conn, "Hobbit")),  # NOUVEAU
        Question("franchise_batman", "Est-ce un film Batman ?", pred_franchise_name(conn, "Batman")),
        Question("franchise_bond", "Est-ce un film James Bond ?", pred_franchise_name(conn, "James Bond")),
        Question("franchise_jurassic", "Est-ce un film Jurassic Park/World ?", pred_franchise_name(conn, "Jurassic")),
        Question("franchise_fast_furious", "Est-ce un film Fast and Furious ?", pred_franchise_name(conn, "Fast")),
        Question("franchise_pirates", "Est-ce un film Pirates des Caraïbes ?", pred_franchise_name(conn, "Pirates of the Caribbean")),  # NOUVEAU
        Question("franchise_xmen", "Est-ce un film X-Men ?", pred_franchise_name(conn, "X-Men")),  # NOUVEAU
        Question("franchise_avengers", "Est-ce un film Avengers ?", pred_franchise_name(conn, "Avengers")),  # NOUVEAU
        Question("franchise_dc", "Est-ce un film DC Comics ?", pred_franchise_name(conn, "DC")),  # NOUVEAU

        # PERSONNAGES ICONIQUES
        Question("char_batman", "Le personnage principal est-il Batman ?", pred_main_character_name(conn, "Batman")),
        Question("char_superman", "Le personnage principal est-il Superman ?", pred_main_character_name(conn, "Superman")),
        Question("char_spider_man", "Le personnage principal est-il Spider-Man ?", pred_main_character_name(conn, "Spider")),
        Question("char_iron_man", "Le personnage principal est-il Iron Man ?", pred_main_character_name(conn, "Iron Man")),
        Question("char_captain_america", "Le personnage principal est-il Captain America ?", pred_main_character_name(conn, "Captain America")),
        Question("char_joker", "Le personnage principal est-il le Joker ?", pred_main_character_name(conn, "Joker")),
        Question("char_terminator", "Le personnage principal est-il le Terminator ?", pred_main_character_name(conn, "Terminator")),
        Question("char_harry_potter", "Le personnage principal est-il Harry Potter ?", pred_main_character_name(conn, "Harry Potter")),  # NOUVEAU
        Question("char_frodo", "Le personnage principal est-il Frodon/Frodo ?", pred_main_character_name(conn, "Frodo")),  # NOUVEAU
        Question("char_jack_sparrow", "Le personnage principal est-il Jack Sparrow ?", pred_main_character_name(conn, "Jack Sparrow")),  # NOUVEAU

        # ACTEURS CÉLÈBRES
        Question("actor_tom_hanks", "Est-ce que Tom Hanks joue dedans ?", pred_actor_in_cast(conn, "Tom Hanks")),
        Question("actor_leonardo_dicaprio", "Est-ce que Leonardo DiCaprio joue dedans ?", pred_actor_in_cast(conn, "Leonardo DiCaprio")),
        Question("actor_brad_pitt", "Est-ce que Brad Pitt joue dedans ?", pred_actor_in_cast(conn, "Brad Pitt")),
        Question("actor_meryl_streep", "Est-ce que Meryl Streep joue dedans ?", pred_actor_in_cast(conn, "Meryl Streep")),
        Question("actor_robert_de_niro", "Est-ce que Robert De Niro joue dedans ?", pred_actor_in_cast(conn, "Robert De Niro")),
        Question("actor_al_pacino", "Est-ce que Al Pacino joue dedans ?", pred_actor_in_cast(conn, "Al Pacino")),
        Question("actor_johnny_depp", "Est-ce que Johnny Depp joue dedans ?", pred_actor_in_cast(conn, "Johnny Depp")),
        Question("actor_will_smith", "Est-ce que Will Smith joue dedans ?", pred_actor_in_cast(conn, "Will Smith")),
        Question("actor_denzel_washington", "Est-ce que Denzel Washington joue dedans ?", pred_actor_in_cast(conn, "Denzel Washington")),
        Question("actor_morgan_freeman", "Est-ce que Morgan Freeman joue dedans ?", pred_actor_in_cast(conn, "Morgan Freeman")),
        Question("actor_samuel_l_jackson", "Est-ce que Samuel L. Jackson joue dedans ?", pred_actor_in_cast(conn, "Samuel L. Jackson")),
        Question("actor_scarlett_johansson", "Est-ce que Scarlett Johansson joue dedans ?", pred_actor_in_cast(conn, "Scarlett Johansson")),
        Question("actor_daniel_radcliffe", "Est-ce que Daniel Radcliffe joue dedans ?", pred_actor_in_cast(conn, "Daniel Radcliffe")),  # NOUVEAU: Harry Potter
        Question("actor_emma_watson", "Est-ce que Emma Watson joue dedans ?", pred_actor_in_cast(conn, "Emma Watson")),  # NOUVEAU: Harry Potter
        Question("actor_rupert_grint", "Est-ce que Rupert Grint joue dedans ?", pred_actor_in_cast(conn, "Rupert Grint")),  # NOUVEAU: Harry Potter
        Question("actor_alan_rickman", "Est-ce que Alan Rickman joue dedans ?", pred_actor_in_cast(conn, "Alan Rickman")),  # NOUVEAU: Harry Potter
        Question("actor_elijah_wood", "Est-ce que Elijah Wood joue dedans ?", pred_actor_in_cast(conn, "Elijah Wood")),  # NOUVEAU: LOTR
        Question("actor_orlando_bloom", "Est-ce que Orlando Bloom joue dedans ?", pred_actor_in_cast(conn, "Orlando Bloom")),  # NOUVEAU: LOTR/Pirates

        # NOUVEAUX THÈMES SPÉCIFIQUES
        Question("theme_school", "L'histoire se passe-t-elle dans une école ?", pred_keyword(conn, "school")),  # NOUVEAU: Harry Potter
        Question("theme_magic_school", "L'histoire se passe-t-elle dans une école de magie ?", pred_keyword(conn, "magic")),  # NOUVEAU: Harry Potter
        Question("theme_wizard", "Y a-t-il des sorciers/magiciens ?", pred_keyword(conn, "wizard")),  # NOUVEAU: Harry Potter
        Question("theme_prophecy", "Y a-t-il une prophétie importante ?", pred_keyword(conn, "prophecy")),  # NOUVEAU
        Question("theme_chosen_one", "Le héros est-il un élu/un choisi ?", pred_keyword(conn, "chosen one")),  # NOUVEAU
        Question("theme_good_vs_evil", "C'est une histoire du bien contre le mal ?", pred_keyword(conn, "good versus evil")),  # NOUVEAU
        Question("theme_friendship", "L'amitié est-elle un thème central ?", pred_keyword(conn, "friendship")),  # NOUVEAU
        Question("theme_coming_of_age", "C'est une histoire d'apprentissage/passage à l'âge adulte ?", pred_keyword(conn, "coming of age")),  # NOUVEAU
    ]


# =========================
# Build dynamic questions
# =========================

def build_dynamic_keyword_questions(
    conn: sqlite3.Connection,
    candidates: List[dict],
    asked: Set[str],
    top_k: int = 80,
) -> List[Question]:
    """
    Questions dynamiques basées sur les keywords les plus fréquents dans le pool.
    OPTIMISATION: Ne génère que si peu de candidats (sinon trop lent).
    """
    from collections import Counter
    
    # OPTIMISATION CRITIQUE: Ne pas générer si trop de candidats (trop lent)
    if len(candidates) > 100:
        return []

    keyword_counter: Counter = Counter()
    for m in candidates:
        mid = movie_id(m)
        if mid is None:
            continue
        kws = get_details(conn, mid).get("keywords", {}).get("keywords", [])
        if isinstance(kws, list):
            for kw in kws:
                if isinstance(kw, dict):
                    name = kw.get("name", "").strip().lower()
                    if name:
                        keyword_counter[name] += 1

    questions: List[Question] = []
    for kw, count in keyword_counter.most_common(top_k):
        if count < 2:
            continue
        key = f"dyn_keyword_{kw.replace(' ', '_')}"
        if key in asked:
            continue
        text = f"Le film contient-il le thème/keyword '{kw}' ?"
        questions.append(Question(key, text, pred_keyword(conn, kw)))

    return questions


def build_dynamic_questions(
    conn: sqlite3.Connection,
    candidates: List[dict],
    asked: Set[str],
    top_k: int = 60,
) -> List[Question]:
    """
    Questions dynamiques basées sur acteurs/réalisateurs fréquents dans le pool.
    OPTIMISATION: Ne génère que si peu de candidats (sinon trop lent).
    """
    from collections import Counter
    
    # OPTIMISATION CRITIQUE: Ne pas générer si trop de candidats (trop lent)
    if len(candidates) > 100:
        return []

    actor_counter: Counter = Counter()
    director_counter: Counter = Counter()

    for m in candidates:
        mid = movie_id(m)
        if mid is None:
            continue
        d = get_details(conn, mid)
        cast = d.get("credits", {}).get("cast", [])
        crew = d.get("credits", {}).get("crew", [])

        if isinstance(cast, list):
            for c in cast[:5]:
                if isinstance(c, dict):
                    name = c.get("name", "").strip()
                    if name:
                        actor_counter[name] += 1

        if isinstance(crew, list):
            for c in crew:
                if isinstance(c, dict) and c.get("job") == "Director":
                    name = c.get("name", "").strip()
                    if name:
                        director_counter[name] += 1

    questions: List[Question] = []

    for actor, count in actor_counter.most_common(top_k):
        if count < 2:
            continue
        key = f"dyn_actor_{actor.replace(' ', '_').lower()}"
        if key in asked:
            continue
        text = f"Est-ce que {actor} joue dedans ?"
        questions.append(Question(key, text, pred_actor_in_cast(conn, actor)))

    for director, count in director_counter.most_common(top_k):
        if count < 2:
            continue
        key = f"dyn_director_{director.replace(' ', '_').lower()}"
        if key in asked:
            continue
        text = f"Est-ce réalisé par {director} ?"
        questions.append(Question(key, text, pred_has_director(conn, director)))

    return questions


# =========================
# Engine state
# =========================

Answer = str

@dataclass
class EngineState:
    candidates: List[dict]
    asked: Set[str]
    scores: Dict[int, float]
    strikes: Dict[int, int]
    question_count: int
    guess_cooldown: int
    top_streak_mid: Optional[int]
    top_streak_len: int
    consecutive_guesses: int  # NOUVEAU: compteur de guesses consécutifs


def init_state(movies: List[dict]) -> EngineState:
    scores = {}
    for m in movies:
        mid = movie_id(m)
        if mid is not None:
            scores[mid] = 0.0
    return EngineState(
        candidates=movies,
        asked=set(),
        scores=scores,
        strikes={},
        question_count=0,
        guess_cooldown=0,
        top_streak_mid=None,
        top_streak_len=0,
        consecutive_guesses=0,  # NOUVEAU
    )


def snapshot_state(state: EngineState) -> EngineState:
    return EngineState(
        candidates=list(state.candidates),
        asked=set(state.asked),
        scores=dict(state.scores),
        strikes=dict(state.strikes),
        question_count=state.question_count,
        guess_cooldown=state.guess_cooldown,
        top_streak_mid=state.top_streak_mid,
        top_streak_len=state.top_streak_len,
        consecutive_guesses=state.consecutive_guesses,  # NOUVEAU
    )


def sort_candidates(state: EngineState) -> None:
    def key_func(m: dict) -> Tuple[float, float]:
        mid = movie_id(m)
        if mid is None:
            return (-1e9, 0.0)
        score = float(state.scores.get(mid, 0.0))
        pop = float(m.get("popularity", 0.0))
        return (-score, -pop)

    state.candidates.sort(key=key_func)


def update_state_with_answer(
    state: EngineState,
    q: Question,
    ans: Answer,
    max_strikes: int,
    debug_target_id: Optional[int] = None,
) -> None:
    """
    Ajuste les scores et retire les films qui accumulent trop de contradictions.
    NOUVEAU: Élimination DURE pour les questions de franchise (suppression immédiate des non-matchs)
    """
    # NOUVEAU: Pour les franchises, on fait une élimination DURE
    is_franchise_question = q.key.startswith("franchise_")
    
    if ans == "y":
        if is_franchise_question:
            # ÉLIMINATION DURE: on garde UNIQUEMENT les films qui matchent la franchise
            to_keep = []
            for m in state.candidates:
                mid = movie_id(m)
                if mid is None:
                    continue
                r = q.predicate(m)
                if r is True:
                    # C'est bien un film de la franchise confirmée
                    state.scores[mid] = state.scores.get(mid, 0.0) + 5.0  # Boost énorme
                    to_keep.append(m)
                elif r is None:
                    # On ne sait pas, on le garde avec une pénalité
                    state.scores[mid] = state.scores.get(mid, 0.0) - 1.0
                    to_keep.append(m)
                # Si r is False: on NE garde PAS le film (élimination dure)
            
            # Remplacer les candidats par ceux qui matchent
            state.candidates = to_keep
            
            # Nettoyer les scores des films éliminés
            remaining_ids = {movie_id(m) for m in state.candidates if movie_id(m) is not None}
            state.scores = {mid: score for mid, score in state.scores.items() if mid in remaining_ids}
            state.strikes = {mid: strikes for mid, strikes in state.strikes.items() if mid in remaining_ids}
        else:
            # Comportement normal pour les autres questions
            for m in state.candidates:
                mid = movie_id(m)
                if mid is None:
                    continue
                r = q.predicate(m)
                if r is True:
                    state.scores[mid] = state.scores.get(mid, 0.0) + 1.5
                elif r is False:
                    state.scores[mid] = state.scores.get(mid, 0.0) - 2.0
                    state.strikes[mid] = state.strikes.get(mid, 0) + 1
                else:
                    state.scores[mid] = state.scores.get(mid, 0.0) - 0.5

    elif ans == "n":
        if is_franchise_question:
            # ÉLIMINATION DURE: on retire TOUS les films qui matchent la franchise
            to_keep = []
            for m in state.candidates:
                mid = movie_id(m)
                if mid is None:
                    continue
                r = q.predicate(m)
                if r is False:
                    # Ce n'est PAS un film de cette franchise, on le garde
                    state.scores[mid] = state.scores.get(mid, 0.0) + 3.0
                    to_keep.append(m)
                elif r is None:
                    # On ne sait pas, on le garde avec un léger boost
                    state.scores[mid] = state.scores.get(mid, 0.0) + 0.5
                    to_keep.append(m)
                # Si r is True: on NE garde PAS le film (élimination dure)
            
            # Remplacer les candidats
            state.candidates = to_keep
            
            # Nettoyer les scores
            remaining_ids = {movie_id(m) for m in state.candidates if movie_id(m) is not None}
            state.scores = {mid: score for mid, score in state.scores.items() if mid in remaining_ids}
            state.strikes = {mid: strikes for mid, strikes in state.strikes.items() if mid in remaining_ids}
        else:
            # Comportement normal
            for m in state.candidates:
                mid = movie_id(m)
                if mid is None:
                    continue
                r = q.predicate(m)
                if r is False:
                    state.scores[mid] = state.scores.get(mid, 0.0) + 1.5
                elif r is True:
                    state.scores[mid] = state.scores.get(mid, 0.0) - 2.0
                    state.strikes[mid] = state.strikes.get(mid, 0) + 1
                else:
                    state.scores[mid] = state.scores.get(mid, 0.0) - 0.5

    elif ans == "py":
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is True:
                boost = 1.5 if is_franchise_question else 0.5
                state.scores[mid] = state.scores.get(mid, 0.0) + boost
            elif r is False:
                penalty = -2.0 if is_franchise_question else -0.75
                state.scores[mid] = state.scores.get(mid, 0.0) + penalty

    elif ans == "pn":
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is False:
                boost = 1.5 if is_franchise_question else 0.5
                state.scores[mid] = state.scores.get(mid, 0.0) + boost
            elif r is True:
                penalty = -2.0 if is_franchise_question else -0.75
                state.scores[mid] = state.scores.get(mid, 0.0) + penalty

    elif ans == "?":
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is None:
                state.scores[mid] = state.scores.get(mid, 0.0) + 0.2

    # Élimination par strikes (sauf si c'était une question de franchise, déjà géré)
    if not is_franchise_question:
        to_remove = []
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            if state.strikes.get(mid, 0) >= max_strikes:
                to_remove.append(mid)

        if to_remove:
            state.candidates = [m for m in state.candidates if movie_id(m) not in to_remove]
            for mid in to_remove:
                state.scores.pop(mid, None)
                state.strikes.pop(mid, None)

    sort_candidates(state)

    if debug_target_id is not None and debug_target_id in state.scores:
        print(
            f"[DEBUG] Film cible {debug_target_id}: score={state.scores[debug_target_id]:.2f}, strikes={state.strikes.get(debug_target_id, 0)}"
        )


# =========================
# Display helpers
# =========================

def short_movie_str(m: dict) -> str:
    title = str(m.get("title") or "N/A")
    y = safe_year(m.get("release_date"))
    year = str(y) if y is not None else "N/A"
    return f"{title} ({year})"

def print_top(state: EngineState, limit: int = 10) -> None:
    for m in state.candidates[:limit]:
        mid = movie_id(m)
        sc = state.scores.get(mid, 0.0) if mid is not None else 0.0
        st = state.strikes.get(mid, 0) if mid is not None else 0
        print(f"- {short_movie_str(m)} | score={sc:.2f} | strikes={st}")
    if len(state.candidates) > limit:
        print(f"... +{len(state.candidates) - limit} autres")


# =========================
# Convergence: mode "guess" + prune
# =========================

def score_of(state: EngineState, m: dict) -> float:
    mid = movie_id(m)
    if mid is None:
        return -1e9
    return float(state.scores.get(mid, 0.0))

def should_enter_guess_mode(state: EngineState) -> bool:
    """
    Détermine intelligemment quand deviner.
    AMÉLIORATION: Plus agressif et intelligent.
    """
    # Si très peu de candidats
    if len(state.candidates) <= 5:
        return True
    
    # Si candidats faibles et domination claire
    if len(state.candidates) <= 20:
        if len(state.candidates) >= 2:
            s1 = score_of(state, state.candidates[0])
            s2 = score_of(state, state.candidates[1])
            if (s1 - s2) >= 1.5:  # Top domine avec 1.5+ pts
                return True
        else:
            return True
    
    # Si candidats moyens et domination forte
    if len(state.candidates) <= 50:
        if len(state.candidates) >= 2:
            s1 = score_of(state, state.candidates[0])
            s2 = score_of(state, state.candidates[1])
            if (s1 - s2) >= 2.5:  # Top domine avec 2.5+ pts
                return True
    
    # Si streak longue (même film #1 pendant longtemps)
    if state.top_streak_len >= 5:
        return True
    
    return False

def ask_yes_no(prompt: str) -> bool:
    ans = input(prompt).strip().lower()
    while ans not in ("y", "n"):
        ans = input(prompt).strip().lower()
    return ans == "y"

def eliminate_movie(state: EngineState, mid: int) -> None:
    # suppression dure: on retire du pool immédiatement
    state.candidates = [m for m in state.candidates if movie_id(m) != mid]
    state.scores.pop(mid, None)
    state.strikes.pop(mid, None)

def read_answer() -> Answer:
    """
    y  : oui
    n  : non
    ?  : je ne sais pas
    py : probablement oui
    pn : probablement non
    u  : undo (retour en arrière)
    """
    ans = input("Réponds (y/n/?/py/pn/u) : ").strip().lower()
    while ans not in ("y", "n", "?", "py", "pn", "u"):
        ans = input("Réponds (y/n/?/py/pn/u) : ").strip().lower()
    return ans


# NOUVEAU: Fonction pour poser des questions discriminantes ciblées
def get_discriminating_questions(
    conn: sqlite3.Connection,
    candidates: List[dict],
    asked: Set[str],
    count: int = 5,
) -> List[Question]:
    """
    Génère des questions discriminantes basées sur les candidats actuels.
    Utilisé quand on a trop de guesses consécutifs ratés.
    MODIFICATION: Sélection déterministe des meilleures questions (pas d'aléatoire).
    """
    all_questions = default_questions(conn)
    dyn_kw = build_dynamic_keyword_questions(conn, candidates, asked, top_k=50)
    dyn_people = build_dynamic_questions(conn, candidates, asked, top_k=40)
    
    available = [q for q in all_questions + dyn_kw + dyn_people if q.key not in asked]
    
    # Trier par score de discrimination
    scored = [(q, q.score(candidates)) for q in available]
    scored = [(q, s) for q, s in scored if s > 0.1]  # Garder seulement les questions utiles
    scored.sort(key=lambda x: x[1], reverse=True)
    
    # MODIFICATION: Prendre directement les N meilleures questions (pas d'aléatoire)
    return [q for q, _ in scored[:count]]


# =========================
# Main loop
# =========================

def main() -> int:
    parser = argparse.ArgumentParser(description="Akinator de films (SQLite) - version tolérante/score AMÉLIORÉE.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Chemin vers movies.db")
    parser.add_argument("--pages", type=int, default=0, help="Limiter le nombre de films (pages*20). 0=all")
    parser.add_argument("--max-strikes", type=int, default=3, help="Contradictions avant élimination d'un film")
    parser.add_argument("--top-streak-questions", type=int, default=3, help="Si le même film reste #1 pendant N questions, proposer un guess")
    parser.add_argument("--guess-cooldown", type=int, default=1, help="Après un guess raté, forcer au moins N questions avant de reguesser (évite les guesses en chaîne)")
    parser.add_argument("--max-consecutive-guesses", type=int, default=4, help="Maximum de guesses consécutifs avant de forcer des questions ciblées")
    parser.add_argument("--debug-target-id", type=int, default=0, help="ID du film à tracer (0=off)")
    args = parser.parse_args()

    db_path = args.db
    pages = args.pages if args.pages > 0 else None
    max_strikes = max(1, int(args.max_strikes))
    top_streak_questions = max(2, int(args.top_streak_questions))
    max_consecutive_guesses = max(2, int(args.max_consecutive_guesses))  # NOUVEAU
    debug_target_id = args.debug_target_id if args.debug_target_id > 0 else None

    print("╔════════════════════════════════════════════════════════╗")
    print("║         AKINATOR DE FILMS - ULTRA RAPIDE 🚀           ║")
    print("╚════════════════════════════════════════════════════════╝")
    print()
    print("Pense à un film populaire, et je vais essayer de le deviner.")
    print("Réponses: y/n/?/py/pn, et u pour annuler la dernière réponse.")
    print()

    conn = None
    try:
        print("⏳ Initialisation de la base de données...", end='', flush=True)
        conn = get_connection(db_path)
        
        # OPTIMISATION: Créer des index pour accélérer les requêtes
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_movie_genres_movie ON movie_genres(movie_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_movie_cast_movie ON movie_cast(movie_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_movie_crew_movie ON movie_crew(movie_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_movie_keywords_movie ON movie_keywords(movie_id)")
        except:
            pass  # Index déjà existants
        
        load_genres(conn)
        print(" ✓")

        print("⏳ Chargement des films...", end='', flush=True)
        movies = discover_movies(conn, pages=pages)
        print(f" ✓ {len(movies)} films chargés")
        print()

        questions = default_questions(conn)

        state = init_state(movies)
        sort_candidates(state)
        state.top_streak_mid = movie_id(state.candidates[0]) if state.candidates else None
        state.top_streak_len = 0

        history: List[EngineState] = []

        while True:
            if not state.candidates:
                print("Aucun candidat restant (trop de contradictions).")
                print("Astuce: utilise '?' ou 'py/pn' quand tu es incertain.")
                return 0

            # affichage du top quand il reste peu
            if len(state.candidates) <= 7:
                print(f"\nIl ne reste que {len(state.candidates)} candidats:")
                print_top(state, limit=7)
                print()

            # condition de victoire (top très dominant ou 1 restant)
            if len(state.candidates) == 1:
                print()
                print("J'AI TROUVÉ :", short_movie_str(state.candidates[0]))
                print(f"Questions: {state.question_count}")
                return 0

            # NOUVEAU: Si trop de guesses consécutifs ratés, forcer des questions discriminantes
            if state.consecutive_guesses >= max_consecutive_guesses:
                print("\n[Mode questions ciblées activé - je cherche de nouvelles pistes...]")
                targeted_questions = get_discriminating_questions(conn, state.candidates, state.asked, count=3)
                
                for tq in targeted_questions:
                    if state.consecutive_guesses < max_consecutive_guesses:
                        break
                        
                    yes, no, unk = split_counts(state.candidates, tq.predicate)
                    print(f"\nQuestion #{state.question_count + 1}: {tq.text}")
                    ans = read_answer()

                    if ans == "u":
                        if not history:
                            print("Impossible: aucun historique.")
                            print()
                            continue
                        state = history.pop()
                        print("OK, retour en arrière effectué.")
                        print(f"Candidats: {len(state.candidates)}")
                        print()
                        continue

                    history.append(snapshot_state(state))
                    state.asked.add(tq.key)
                    state.question_count += 1
                    state.consecutive_guesses = 0  # Reset du compteur après une vraie question

                    update_state_with_answer(state, tq, ans, max_strikes=max_strikes, debug_target_id=debug_target_id)
                    print(f"Restants: {len(state.candidates)}")
                    print()
            
            # OPTIMISATION: Vérifier si on devrait guess AVANT de générer les questions
            should_guess = False
            if len(state.candidates) <= 50 and len(state.candidates) >= 2:
                s1 = score_of(state, state.candidates[0])
                s2 = score_of(state, state.candidates[1])
                if (s1 - s2) >= 2.0:
                    should_guess = True
            
            # Si on devrait guess, le faire maintenant (pas besoin de questions)
            if should_guess and state.guess_cooldown == 0:
                top = state.candidates[0]
                guess = short_movie_str(top)
                if ask_yes_no(f"Je pense que c'est: {guess}. C'est ça ? (y/n) : "):
                    print("\nJ'AI TROUVÉ :", guess)
                    print(f"Questions: {state.question_count}")
                    return 0
                else:
                    mid = movie_id(top)
                    if mid is not None:
                        eliminate_movie(state, mid)
                    sort_candidates(state)
                    state.guess_cooldown = args.guess_cooldown
                    state.top_streak_mid = movie_id(state.candidates[0]) if state.candidates else None
                    state.top_streak_len = 0
                    state.consecutive_guesses += 1
                    print("OK, je continue.\n")
                    continue
            
            dyn_kw = build_dynamic_keyword_questions(conn, state.candidates, state.asked, top_k=80)
            dyn_people = build_dynamic_questions(conn, state.candidates, state.asked, top_k=60)
            merged_questions = dyn_kw + dyn_people + questions

            q = choose_best_question(state.candidates, merged_questions, state.asked)
            
            # Si plus de questions ou mode guess
            if q is None or (should_enter_guess_mode(state) and state.guess_cooldown == 0):
                top = state.candidates[0]
                guess = short_movie_str(top)
                if ask_yes_no(f"Je pense que c'est: {guess}. C'est ça ? (y/n) : "):
                    print("\nJ'AI TROUVÉ :", guess)
                    print(f"Questions: {state.question_count}")
                    return 0
                else:
                    mid = movie_id(top)
                    if mid is not None:
                        eliminate_movie(state, mid)
                    sort_candidates(state)
                    state.guess_cooldown = args.guess_cooldown
                    state.top_streak_mid = movie_id(state.candidates[0]) if state.candidates else None
                    state.top_streak_len = 0
                    state.consecutive_guesses += 1
                    print("OK, je continue.\n")
                    continue

            yes, no, unk = split_counts(state.candidates, q.predicate)
            print(f"Question #{state.question_count + 1}: {q.text}")
            ans = read_answer()

            if ans == "u":
                if not history:
                    print("Impossible: aucun historique.")
                    print()
                    continue
                state = history.pop()
                print("OK, retour en arrière effectué.")
                print(f"Candidats: {len(state.candidates)}")
                print()
                continue

            history.append(snapshot_state(state))

            state.asked.add(q.key)
            state.question_count += 1
            state.consecutive_guesses = 0

            if state.guess_cooldown > 0:
                state.guess_cooldown -= 1

            update_state_with_answer(
                state,
                q,
                ans,
                max_strikes=max_strikes,
                debug_target_id=debug_target_id,
            )

            print(f"Restants: {len(state.candidates)}")

            top = state.candidates[0]
            mid = movie_id(top)

            if mid is not None:
                if state.top_streak_mid == mid:
                    state.top_streak_len += 1
                else:
                    state.top_streak_mid = mid
                    state.top_streak_len = 1

                if state.top_streak_len >= 7 and state.guess_cooldown == 0:
                    guess = short_movie_str(top)
                    if ask_yes_no(f"Le même film est #1 depuis un moment. Je pense que c'est: {guess}. C'est ça ? (y/n) : "):
                        print("\nJ'AI TROUVÉ :", guess)
                        print(f"Questions: {state.question_count}")
                        return 0
                    else:
                        eliminate_movie(state, mid)
                        sort_candidates(state)
                        state.guess_cooldown = args.guess_cooldown
                        state.top_streak_mid = movie_id(state.candidates[0]) if state.candidates else None
                        state.top_streak_len = 0
                        state.consecutive_guesses += 1  # NOUVEAU: incrémenter le compteur
                        print("OK, je continue.\n")
                        continue
            print()


    finally:
        close_connection()

if __name__ == "__main__":
    raise SystemExit(main())
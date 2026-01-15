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
    """Obtient ou crée la connexion à la base de données avec optimisations SQLite."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(db_path)
        _conn.row_factory = sqlite3.Row
        # OPTIMISATIONS pour vitesse maximale
        _conn.execute("PRAGMA synchronous = OFF")
        _conn.execute("PRAGMA journal_mode = MEMORY")
        _conn.execute("PRAGMA temp_store = MEMORY")
        _conn.execute("PRAGMA cache_size = 10000")
    return _conn

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
        # PRIORITÉ 1: Questions de VALIDATION du TOP candidat (ULTRA prioritaires)
        if self.key.startswith("validate_"):
            score *= 50.0  # ULTRA BOOST pour valider/éliminer le #1 rapidement
        # PRIORITÉ 2: Questions de langue (posées EN PREMIER)
        elif self.key.startswith("language_"):
            score *= 100.0  # MEGA BOOST pour forcer les questions de langue en premier
        elif self.key.startswith(("director_", "dyn_director_")):
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


def get_question_type(q: Question) -> str:
    """Détecte le type d'une question pour tracking de diversité."""
    if q.key.startswith("validate_"):
        return "validation"  # NOUVEAU: Questions de validation du TOP
    elif q.key.startswith("language_"):
        return "language"
    elif q.key.startswith(("actor_", "dyn_actor_")):
        return "actor"
    elif q.key.startswith(("director_", "dyn_director_")):
        return "director"
    elif q.key.startswith("genre_"):
        return "genre"
    elif q.key.startswith(("franchise_", "char_")):
        return "franchise"
    elif q.key.startswith(("year_", "decade_", "after_", "before_")):
        return "date"
    elif q.key.startswith("dyn_keyword_"):
        return "keyword"
    elif q.key.startswith("runtime_"):
        return "runtime"
    elif q.key.startswith("joker_title_"):
        return "title"
    elif q.key.startswith(("big_budget", "small_budget", "box_office", "is_indie")):
        return "finance"
    elif q.key.startswith(("popular", "very_popular")):
        return "popularity"
    elif q.key.startswith(("is_saga", "is_standalone", "is_adaptation", "based_on_", "superhero")):
        return "meta"  # Méta-info sur le film
    elif q.key.startswith(("is_american", "is_french", "is_european", "is_asian")):
        return "origin"
    elif q.key.startswith(("is_animation", "is_live_action", "is_short", "is_feature")):
        return "format"
    elif q.key.startswith("theme_"):
        return "theme"  # Séparer theme de keyword
    else:
        return "other"


def count_recent_type(state: 'EngineState', q_type: str, window: int = 5) -> int:
    """Compte combien de questions du même type dans les N dernières."""
    if not state.recent_question_types:
        return 0
    
    recent = state.recent_question_types[-window:]  # Dernières N questions
    return recent.count(q_type)


def should_diversify(state: 'EngineState', q: Question, max_consecutive: int = 2) -> bool:
    """
    Retourne True si on devrait éviter cette question pour diversifier.
    AMÉLIORATION: Max 2 consécutives (au lieu de 3) pour plus de variété.
    """
    q_type = get_question_type(q)
    
    # Exceptions: TOUJOURS autoriser ces types (prioritaires)
    if q_type in ["language", "validation"]:
        return False  # JAMAIS pénaliser langue et validation
    
    # Compter les questions récentes du même type
    consecutive_count = count_recent_type(state, q_type, window=max_consecutive)
    
    # Si on a déjà posé max_consecutive questions de ce type → diversifier
    if consecutive_count >= max_consecutive:
        return True
    
    # NOUVEAU: Aussi vérifier la diversité globale des 5 dernières questions
    if len(state.recent_question_types) >= 5:
        last_5 = state.recent_question_types[-5:]
        unique_types = len(set(last_5))
        
        # Si moins de 3 types différents dans les 5 dernières → encourager diversité
        if unique_types < 3 and last_5.count(q_type) >= 2:
            return True
    
    return False


def choose_best_question(candidates: List[dict], questions: List[Question], asked: Set[str], 
                         is_first_question: bool = False, state: Optional['EngineState'] = None) -> Optional[Question]:
    """
    Choisit la meilleure question de manière déterministe et RAPIDE.
    OPTIMISATION: Échantillonne si trop de questions pour éviter de tout scorer.
    AMÉLIORATION: Ajoute de l'aléatoire sur la première question.
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
        # NOUVEAU: Vérifier si on doit pénaliser pour diversité
        s = q.score(candidates)
        if s > 0:
            # Pénaliser FORTEMENT si trop de questions du même type récemment
            if state and should_diversify(state, q, max_consecutive=2):
                s *= 0.01  # Pénalité EXTRÊME (99% de réduction) pour forcer variété
            
            scored.append((q, s))

    if not scored:
        return None

    scored.sort(key=lambda x: x[1], reverse=True)
    
    # AMÉLIORATION: Aléatoire sur la première question (top 5 au lieu de toujours la #1)
    if is_first_question and len(scored) >= 5:
        # Choisir aléatoirement parmi les 5 meilleures questions
        top_5 = scored[:5]
        return random.choice(top_5)[0]
    
    return scored[0][0]


# =========================
# Predicates - ANNÉE
# =========================

def pred_after_year(year: int) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        y = safe_year(m.get("release_date"))
        if y is None:
            return None
        return y >= year
    return p

def pred_before_year(year: int) -> Callable[[dict], Optional[bool]]:
    def p(m: dict) -> Optional[bool]:
        y = safe_year(m.get("release_date"))
        if y is None:
            return None
        return y < year
    return p

def pred_exact_year(year: int) -> Callable[[dict], Optional[bool]]:
    """Vérifie si le film est sorti exactement cette année."""
    def p(m: dict) -> Optional[bool]:
        y = safe_year(m.get("release_date"))
        if y is None:
            return None
        return y == year
    return p

def pred_decade(start_year: int) -> Callable[[dict], Optional[bool]]:
    """Vérifie si le film est sorti dans une décennie (ex: 1980-1989)."""
    def p(m: dict) -> Optional[bool]:
        y = safe_year(m.get("release_date"))
        if y is None:
            return None
        return start_year <= y < (start_year + 10)
    return p

def pred_year_range(start: int, end: int) -> Callable[[dict], Optional[bool]]:
    """Vérifie si le film est sorti dans une plage d'années."""
    def p(m: dict) -> Optional[bool]:
        y = safe_year(m.get("release_date"))
        if y is None:
            return None
        return start <= y <= end
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

        # ÉPOQUE / SORTIE - DÉCENNIES PRÉCISES
        Question("decade_1970s", "Est-ce que c'est sorti dans les années 1970 (1970-1979) ?", pred_decade(1970)),
        Question("decade_1980s", "Est-ce que c'est sorti dans les années 1980 (1980-1989) ?", pred_decade(1980)),
        Question("decade_1990s", "Est-ce que c'est sorti dans les années 1990 (1990-1999) ?", pred_decade(1990)),
        Question("decade_2000s", "Est-ce que c'est sorti dans les années 2000 (2000-2009) ?", pred_decade(2000)),
        Question("decade_2010s", "Est-ce que c'est sorti dans les années 2010 (2010-2019) ?", pred_decade(2010)),
        Question("decade_2020s", "Est-ce que c'est sorti dans les années 2020+ (2020-2029) ?", pred_decade(2020)),
        
        # PÉRIODES LARGES (toujours utiles pour affiner)
        Question("before_2000", "Est-ce que c'est sorti avant 2000 ?", pred_before_year(2000)),
        Question("after_2010", "Est-ce que c'est sorti en 2010 ou après ?", pred_after_year(2010)),

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
        
        # LANGUE ORIGINALE - EXCLUSION MUTUELLE TOTALE
        # Dès qu'on répond "oui" à une langue, toutes les autres sont exclues
        Question("language_en", "La langue originale est-elle l'anglais ?", pred_language("en")),
        Question("language_fr", "La langue originale est-elle le français ?", pred_language("fr")),
        Question("language_ja", "La langue originale est-elle le japonais ?", pred_language("ja")),
        Question("language_es", "La langue originale est-elle l'espagnol ?", pred_language("es")),
        Question("language_de", "La langue originale est-elle l'allemand ?", pred_language("de")),
        Question("language_it", "La langue originale est-elle l'italien ?", pred_language("it")),
        Question("language_ko", "La langue originale est-elle le coréen ?", pred_language("ko")),
        Question("language_zh", "La langue originale est-elle le chinois ?", pred_language("zh")),

        # SUCCÈS / POPULARITÉ
        Question("popular", "Est-ce que c'est un film très populaire ?", pred_popularity_ge(50)),
        Question("very_popular", "Est-ce que c'est un film culte ou ultra connu ?", pred_popularity_ge(80)),

        # FINANCES - AVEC EXCLUSIONS LOGIQUES
        Question("big_budget", "Est-ce que le film a un gros budget (plus de 50 000 000) ?", pred_budget_ge(conn, 50_000_000)),
        Question("small_budget", "Est-ce que le film a un petit budget (moins de 10 000 000) ?", pred_budget_lt(conn, 10_000_000),
                excludes={"big_budget"}),  # NOUVEAU: si gros budget, ne pas demander petit budget
        Question("box_office_success", "Est-ce que le film a bien marché au box-office (plus de 100 000 000 de revenu) ?", pred_revenue_ge(conn, 100_000_000)),
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

def build_top_validation_questions(
    conn: sqlite3.Connection,
    candidates: List[dict],
    asked: Set[str],
) -> List[Question]:
    """
    NOUVEAU: Génère des questions SPÉCIFIQUES au film #1 pour le valider/éliminer rapidement.
    
    Stratégie: Au lieu d'éliminer 149 autres films, on pose des questions sur le #1:
    - Si réponse OUI → Le #1 se confirme
    - Si réponse NON → Le #1 est ÉLIMINÉ immédiatement !
    
    Beaucoup plus rapide !
    """
    if len(candidates) < 50 or len(candidates) > 200:
        return []  # Seulement quand 50-200 candidats
    
    top = candidates[0]
    mid = movie_id(top)
    if mid is None:
        return []
    
    questions: List[Question] = []
    details = get_details(conn, mid)
    
    # 1. ACTEURS PRINCIPAUX du film #1
    cast = details.get("credits", {}).get("cast", [])
    if isinstance(cast, list):
        for actor in cast[:5]:  # Top 5 acteurs
            if isinstance(actor, dict):
                name = actor.get("name", "").strip()
                if name:
                    key = f"validate_actor_{name.replace(' ', '_').lower()}"
                    if key not in asked:
                        text = f"[VALIDATION #1] Est-ce que {name} joue dedans ?"
                        questions.append(Question(key, text, pred_actor_in_cast(conn, name)))
    
    # 2. RÉALISATEUR du film #1
    crew = details.get("credits", {}).get("crew", [])
    if isinstance(crew, list):
        for person in crew:
            if isinstance(person, dict) and person.get("job") == "Director":
                name = person.get("name", "").strip()
                if name:
                    key = f"validate_director_{name.replace(' ', '_').lower()}"
                    if key not in asked:
                        text = f"[VALIDATION #1] Est-ce réalisé par {name} ?"
                        questions.append(Question(key, text, pred_has_director(conn, name)))
                    break
    
    # 3. KEYWORDS SPÉCIFIQUES du film #1
    keywords = details.get("keywords", {}).get("keywords", [])
    if isinstance(keywords, list):
        for kw in keywords[:10]:  # Top 10 keywords
            if isinstance(kw, dict):
                name = kw.get("name", "").strip().lower()
                if name:
                    key = f"validate_keyword_{name.replace(' ', '_')}"
                    if key not in asked:
                        text = f"[VALIDATION #1] Le film contient-il '{name}' ?"
                        questions.append(Question(key, text, pred_keyword(conn, name)))
    
    # 4. ANNÉE EXACTE du film #1
    year = safe_year(top.get("release_date"))
    if year:
        key = f"validate_year_{year}"
        if key not in asked:
            text = f"[VALIDATION #1] Est-ce sorti en {year} ?"
            questions.append(Question(key, text, pred_exact_year(year)))
    
    # 5. TITRE du film #1 (première lettre)
    title = str(top.get("title", "")).strip()
    if title:
        first_letter = title[0].upper()
        key = f"validate_title_{first_letter}"
        if key not in asked:
            text = f"[VALIDATION #1] Le titre commence-t-il par '{first_letter}' ?"
            questions.append(Question(key, text, pred_title_starts_with(first_letter)))
    
    return questions[:15]  # Max 15 questions de validation


def build_dynamic_keyword_questions(
    conn: sqlite3.Connection,
    candidates: List[dict],
    asked: Set[str],
    top_k: int = 80,
) -> List[Question]:
    """
    Questions dynamiques basées sur les keywords les plus fréquents dans le pool.
    STRICT MODE: Génère BEAUCOUP plus de questions pour affiner.
    """
    from collections import Counter
    
    # STRICT MODE: Générer même avec plus de candidats
    if len(candidates) > 200:  # Augmenté de 100 à 200
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
    
    # STRICT MODE: Augmenter top_k si peu de candidats
    actual_top_k = top_k
    if len(candidates) <= 10:
        actual_top_k = 200  # Beaucoup plus de questions
    elif len(candidates) <= 30:
        actual_top_k = 150
    elif len(candidates) <= 50:
        actual_top_k = 120
    
    for kw, count in keyword_counter.most_common(actual_top_k):
        # STRICT MODE: Accepter même 1 seul film avec ce keyword (au lieu de 2)
        if count < 1:
            continue
        key = f"dyn_keyword_{kw.replace(' ', '_')}"
        if key in asked:
            continue
        text = f"Le film contient-il le thème/keyword '{kw}' ?"
        questions.append(Question(key, text, pred_keyword(conn, kw)))

    return questions


def detect_dominant_language(candidates: List[dict]) -> Optional[str]:
    """
    Détecte la langue originale dominante parmi les candidats.
    Retourne le code langue (en, fr, ja, es, etc.) ou None si mixte.
    """
    from collections import Counter
    
    if not candidates:
        return None
    
    lang_counter: Counter = Counter()
    for m in candidates:
        lang = m.get("original_language", "")
        if lang:
            lang_counter[lang] += 1
    
    if not lang_counter:
        return None
    
    # Si une langue représente 70%+ des candidats, c'est la langue dominante
    total = len(candidates)
    most_common_lang, count = lang_counter.most_common(1)[0]
    
    if count / total >= 0.70:
        return most_common_lang
    
    return None  # Trop mixte


# =========================
# ACTEURS CÉLÈBRES (par décennie + par pays) — utilisé pour questions dynamiques
# =========================

ACTORS_BY_DECADE_EN = {
    1960: [
        "Sean Connery", "Paul Newman", "Steve McQueen", "Clint Eastwood", "Marlon Brando",
        "Sidney Poitier", "Audrey Hepburn", "Elizabeth Taylor", "Julie Andrews", "Cary Grant",
        "Peter O'Toole", "Henry Fonda"
    ],
    1970: [
        "Al Pacino", "Robert De Niro", "Jack Nicholson", "Dustin Hoffman", "Gene Hackman",
        "Donald Sutherland", "Harrison Ford", "Sylvester Stallone", "Diane Keaton", "Jane Fonda",
        "Faye Dunaway", "Goldie Hawn", "John Cazale", "Burt Reynolds", "Christopher Walken"
    ],
    1980: [
        "Tom Cruise", "Arnold Schwarzenegger", "Sylvester Stallone", "Harrison Ford", "Eddie Murphy",
        "Michael J. Fox", "Bruce Willis", "Mel Gibson", "Meryl Streep", "Sigourney Weaver",
        "Michelle Pfeiffer", "Whoopi Goldberg", "Bill Murray", "Kevin Costner", "Sean Penn"
    ],
    1990: [
        "Leonardo DiCaprio", "Brad Pitt", "Tom Hanks", "Johnny Depp", "Will Smith",
        "Morgan Freeman", "Keanu Reeves", "Denzel Washington", "Julia Roberts", "Sandra Bullock",
        "Nicole Kidman", "Jodie Foster", "Matt Damon", "Jim Carrey", "Samuel L. Jackson"
    ],
    2000: [
        "Tom Cruise", "Leonardo DiCaprio", "Brad Pitt", "Johnny Depp", "Christian Bale",
        "George Clooney", "Russell Crowe", "Matt Damon", "Angelina Jolie", "Natalie Portman",
        "Cate Blanchett", "Keira Knightley", "Hugh Jackman", "Daniel Craig", "Sean Penn"
    ],
    2010: [
        "Robert Downey Jr.", "Leonardo DiCaprio", "Chris Hemsworth", "Chris Evans", "Ryan Gosling",
        "Brad Pitt", "Dwayne Johnson", "Joaquin Phoenix", "Scarlett Johansson", "Jennifer Lawrence",
        "Emma Stone", "Margot Robbie", "Amy Adams", "Christian Bale", "Benedict Cumberbatch"
    ],
    2020: [
        "Timothée Chalamet", "Zendaya", "Florence Pugh", "Anya Taylor-Joy", "Austin Butler",
        "Cillian Murphy", "Margot Robbie", "Robert Pattinson", "Pedro Pascal", "Ryan Gosling",
        "Jenna Ortega", "Paul Mescal", "Barry Keoghan", "Sydney Sweeney", "Jason Momoa"
    ],
}

ACTORS_FR = [
    "Jean Gabin", "Alain Delon", "Jean-Paul Belmondo", "Gérard Depardieu", "Louis de Funès",
    "Jean Reno", "Omar Sy", "Vincent Cassel", "Marion Cotillard", "Catherine Deneuve",
    "Isabelle Adjani", "Brigitte Bardot", "Juliette Binoche", "Michel Piccoli", "Patrick Dewaere",
    "Daniel Auteuil", "Yves Montand", "Jean Dujardin", "François Cluzet", "Bourvil",
    "Sophie Marceau", "Michel Serrault", "Jean-Pierre Léaud", "Romain Duris", "Gaspard Ulliel"
]

ACTORS_ES = [
    "Antonio Banderas", "Penélope Cruz", "Javier Bardem", "Fernando Rey", "Carmen Maura",
    "Victoria Abril", "Eduard Fernández", "Jordi Mollà", "Paz Vega", "Álex González",
    "Luis Tosar", "Maribel Verdú", "Sergi López", "Antonio de la Torre",
    "Raúl Arévalo", "Inma Cuesta", "Karra Elejalde", "Emma Suárez", "Najwa Nimri",
    "Mario Casas", "Blanca Portillo", "José Sacristán", "Imanol Arias", "Ana Torrent"
]

ACTORS_DE = [
    "Bruno Ganz", "Christoph Waltz", "Diane Kruger", "Til Schweiger",
    "Moritz Bleibtreu", "Nina Hoss", "Daniel Brühl", "Jürgen Prochnow", "August Diehl",
    "Hannah Herzsprung", "Sebastian Koch", "Heiner Lauterbach", "Lars Eidinger", "Maria Schrader",
    "Ulrich Mühe", "Sibel Kekilli", "Volker Bruch", "Barbara Sukowa",
    "Klaus Kinski", "Romy Schneider", "Brigitte Helm", "Tom Schilling", "Matthias Schweighöfer"
]

ACTORS_JA = [
    "Toshiro Mifune", "Takashi Shimura", "Ken Watanabe", "Issey Ogata", "Hiroyuki Sanada",
    "Rinko Kikuchi", "Tadanobu Asano", "Koji Yakusho", "Takeshi Kitano", "Yû Aoi",
    "Shin'ichi Tsutsumi", "Satomi Ishihara", "Masami Nagasawa", "Kankurō Nakamura",
    "Kazuki Kitamura", "Ayase Haruka", "Sho Sakurai", "Masahiro Motoki", "Yôsuke Eguchi",
    "Ryō Yoshizawa", "Kento Yamazaki", "Suzu Hirose", "Fumiyo Kohinata", "Shota Sometani"
]

ACTORS_IT = [
    "Marcello Mastroianni", "Sophia Loren", "Vittorio Gassman", "Alberto Sordi", "Gina Lollobrigida",
    "Monica Bellucci", "Claudia Cardinale", "Totò", "Roberto Benigni", "Pierfrancesco Favino",
    "Isabella Rossellini", "Raoul Bova", "Sergio Castellitto", "Asia Argento", "Stefania Sandrelli",
    "Valeria Golino", "Franco Nero", "Bud Spencer", "Terence Hill", "Giancarlo Giannini",
    "Elio Germano", "Toni Servillo", "Silvana Mangano", "Luigi Lo Cascio", "Riccardo Scamarcio"
]


def get_decade_from_year(year: Optional[int]) -> Optional[int]:
    if year is None:
        return None
    return (year // 10) * 10


def detect_dominant_decade(candidates: List[dict]) -> Optional[int]:
    """Décennie dominante si elle représente >= 70% des candidats."""
    from collections import Counter

    if not candidates:
        return None

    decade_counter: Counter = Counter()
    for m in candidates:
        year = safe_year(m.get("release_date"))
        decade = get_decade_from_year(year)
        if decade is not None:
            decade_counter[decade] += 1

    if not decade_counter:
        return None

    total = len(candidates)
    most_common_decade, count = decade_counter.most_common(1)[0]
    if count / total >= 0.70:
        return most_common_decade
    return None


def get_relevant_actors(dominant_language: Optional[str], dominant_decade: Optional[int]) -> List[str]:
    """Réduit le bruit: pour 'en' filtre par décennie, pour autres langues liste pays."""
    if dominant_language is None:
        return ACTORS_BY_DECADE_EN.get(2020, [])

    if dominant_language == "en":
        if dominant_decade is None or dominant_decade < 1960:
            return ACTORS_BY_DECADE_EN.get(2020, [])
        if dominant_decade in ACTORS_BY_DECADE_EN:
            return ACTORS_BY_DECADE_EN[dominant_decade]
        available = sorted(ACTORS_BY_DECADE_EN.keys())
        closest = min(available, key=lambda x: abs(x - dominant_decade))
        return ACTORS_BY_DECADE_EN[closest]

    if dominant_language == "fr":
        return ACTORS_FR
    if dominant_language == "es":
        return ACTORS_ES
    if dominant_language == "de":
        return ACTORS_DE
    if dominant_language == "ja":
        return ACTORS_JA
    if dominant_language == "it":
        return ACTORS_IT

    return ACTORS_BY_DECADE_EN.get(2020, [])


# Mapping acteurs célèbres → nationalité (code langue)
# Cette liste sera enrichie au fur et à mesure
ACTOR_NATIONALITY = {
    # Acteurs américains/anglais (en)
    "leonardo dicaprio": "en",
    "brad pitt": "en",
    "tom hanks": "en",
    "robert downey jr.": "en",
    "scarlett johansson": "en",
    "jennifer lawrence": "en",
    "tom cruise": "en",
    "will smith": "en",
    "denzel washington": "en",
    "morgan freeman": "en",
    "samuel l. jackson": "en",
    "christian bale": "en",
    "matt damon": "en",
    "mark wahlberg": "en",
    "johnny depp": "en",
    "angelina jolie": "en",
    "sandra bullock": "en",
    "julia roberts": "en",
    "meryl streep": "en",
    "kate winslet": "en",
    "cate blanchett": "en",
    "hugh jackman": "en",
    "chris hemsworth": "en",
    "chris evans": "en",
    "chris pratt": "en",
    "robert pattinson": "en",
    "emma watson": "en",
    "daniel radcliffe": "en",
    "rupert grint": "en",
    "harrison ford": "en",
    "mark hamill": "en",
    "carrie fisher": "en",
    "natalie portman": "en",
    "ewan mcgregor": "en",
    "ian mckellen": "en",
    "patrick stewart": "en",
    "ben affleck": "en",
    "ryan gosling": "en",
    "ryan reynolds": "en",
    "keanu reeves": "en",
    "charlize theron": "en",
    "michael fassbender": "en",
    "james mcavoy": "en",
    "benedict cumberbatch": "en",
    "tom hiddleston": "en",
    "eddie redmayne": "en",
    
    # Acteurs français (fr)
    "marion cotillard": "fr",
    "omar sy": "fr",
    "jean reno": "fr",
    "gérard depardieu": "fr",
    "vincent cassel": "fr",
    "jean dujardin": "fr",
    "audrey tautou": "fr",
    "léa seydoux": "fr",
    "sophie marceau": "fr",
    "isabelle huppert": "fr",
    "juliette binoche": "fr",
    "lambert wilson": "fr",
    "mathieu amalric": "fr",
    "romain duris": "fr",
    "gad elmaleh": "fr",
    "dany boon": "fr",
    "françois cluzet": "fr",
    "benoît magimel": "fr",
    "audrey dana": "fr",
    
    # Acteurs espagnols (es)
    "penélope cruz": "es",
    "javier bardem": "es",
    "antonio banderas": "es",
    "ricardo darín": "es",
    "adrián suar": "es",
    "guillermo campra": "es",
    "dani martín": "es",
    
    # Acteurs japonais (ja)
    "ken watanabe": "ja",
    "rinko kikuchi": "ja",
    "toshiro mifune": "ja",
    "mari natsuki": "ja",
    
    # Acteurs allemands (de)
    "diane kruger": "de",
    "til schweiger": "de",
    "daniel brühl": "de",
    "christoph waltz": "de",
    
    # Acteurs italiens (it)
    "sophia loren": "it",
    "marcello mastroianni": "it",
    "roberto benigni": "it",
    "monica bellucci": "it",
    "damiano russo": "it",
}


def should_include_actor(actor_name: str, dominant_language: Optional[str], relevant_actor_set: Optional[Set[str]] = None) -> bool:
    """
    Détermine si on doit poser une question sur cet acteur.

    Règles:
    - Si relevant_actor_set est fourni (mode "réduction de bruit"), on garde uniquement les acteurs dans ce set.
    - Sinon, on filtre par langue dominante via ACTOR_NATIONALITY (si connu).
    - Si la langue est mixte ou inconnue, on accepte.
    """
    if relevant_actor_set is not None:
        return actor_name in relevant_actor_set

    if dominant_language is None:
        return True

    actor_lower = actor_name.lower().strip()
    actor_lang = ACTOR_NATIONALITY.get(actor_lower)

    if actor_lang is None:
        return True  # Acteur inconnu, on garde par défaut

    return actor_lang == dominant_language


def build_dynamic_questions(
    conn: sqlite3.Connection,
    candidates: List[dict],
    asked: Set[str],
    top_k: int = 60,
) -> List[Question]:
    """
    Questions dynamiques basées sur acteurs/réalisateurs fréquents dans le pool.
    SMART MODE: Filtre les acteurs selon la langue dominante des candidats.
    """
    from collections import Counter
    
    # STRICT MODE: Générer même avec plus de candidats
    if len(candidates) > 200:  # Augmenté de 100 à 200
        return []

    # NOUVEAU: Détecter la langue dominante
    dominant_language = detect_dominant_language(candidates)
    dominant_decade = detect_dominant_decade(candidates)
    relevant_actor_set = set(get_relevant_actors(dominant_language, dominant_decade))
    
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
            # STRICT MODE: Regarder TOUS les acteurs (pas juste top 5)
            max_actors = 15 if len(candidates) <= 20 else 10
            for c in cast[:max_actors]:
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
    
    # STRICT MODE: Augmenter top_k si peu de candidats
    actual_top_k = top_k
    if len(candidates) <= 10:
        actual_top_k = 150
    elif len(candidates) <= 30:
        actual_top_k = 120
    elif len(candidates) <= 50:
        actual_top_k = 100

    # NOUVEAU: Filtrer les acteurs selon la langue dominante
    for actor, count in actor_counter.most_common(actual_top_k):
        # STRICT MODE: Accepter même 1 seul film (au lieu de 2)
        if count < 1:
            continue
        
        # SMART FILTER: Vérifier si l'acteur correspond à la langue dominante
        if not should_include_actor(actor, dominant_language, relevant_actor_set):
            continue  # Skip cet acteur s'il ne correspond pas
        
        key = f"dyn_actor_{actor.replace(' ', '_').lower()}"
        if key in asked:
            continue
        text = f"Est-ce que {actor} joue dedans ?"
        questions.append(Question(key, text, pred_actor_in_cast(conn, actor)))

    for director, count in director_counter.most_common(actual_top_k):
        if count < 1:  # STRICT MODE: 1 au lieu de 2
            continue
        key = f"dyn_director_{director.replace(' ', '_').lower()}"
        if key in asked:
            continue
        text = f"Est-ce réalisé par {director} ?"
        questions.append(Question(key, text, pred_has_director(conn, director)))

    return questions


def build_dynamic_year_questions(
    candidates: List[dict],
    asked: Set[str],
) -> List[Question]:
    """
    STRICT MODE: Génère des questions d'années spécifiques pour TOUS les candidats.
    Plus on a peu de candidats, plus on génère de questions précises.
    """
    from collections import Counter
    
    # STRICT MODE: Générer jusqu'à 100 candidats (au lieu de 50)
    if len(candidates) > 100 or len(candidates) < 2:
        return []
    
    year_counter: Counter = Counter()
    
    for m in candidates:
        y = safe_year(m.get("release_date"))
        if y is not None:
            year_counter[y] += 1
    
    questions: List[Question] = []
    
    # STRICT MODE: Générer pour toutes les années (même avec 1 seul film)
    max_questions = 20 if len(candidates) <= 10 else 15
    
    for year, count in year_counter.most_common(max_questions):
        # STRICT MODE: Même 1 seul film suffit (au lieu de 2)
        if count < 1:
            continue
        
        key = f"year_{year}"
        if key in asked:
            continue
        
        text = f"Est-ce que c'est sorti en {year} ?"
        questions.append(Question(key, text, pred_exact_year(year)))
    
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
    recent_question_types: List[str]  # NOUVEAU: historique des types récents (max 5)


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
        recent_question_types=[],  # NOUVEAU
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
        recent_question_types=list(state.recent_question_types),  # NOUVEAU
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
    NOUVEAU: Élimination DURE pour toutes les caractéristiques mutuellement exclusives
    """
    # NOUVEAU: Identification des questions à élimination DURE
    # Ce sont des questions où la réponse est binaire/mutuellement exclusive
    
    hard_elimination_prefixes = [
        "franchise_",      # Franchises (Marvel, Star Wars, etc.)
        "language_",       # Langues (en, fr, ja, etc.)
        "director_",       # Réalisateurs spécifiques (Nolan, Spielberg, etc.)
        "joker_title_",    # Première lettre du titre (A-D, E-H, etc.)
        "char_",           # Personnages principaux (Batman, Harry Potter, etc.)
        "decade_",         # NOUVEAU: Décennies (1980s, 1990s, etc.)
        "year_",           # NOUVEAU: Années spécifiques (2010, 2015, etc.)
    ]
    
    hard_elimination_keys = {
        "is_animation",     # Animation vs Live-action
        "is_live_action",
        "is_short",         # Court-métrage vs Long-métrage
        "is_feature",
        "runtime_lt_90",    # Durée du film
        "runtime_ge_150",
        "before_2000",      # Dates de sortie larges
        "after_2010",
        "is_saga",          # Franchise vs Standalone
        "is_standalone",
        "big_budget",       # Budget
        "small_budget",
        "is_american",      # Pays d'origine
        "is_french",
        "is_european",
        "is_asian",
    }
    
    # Vérifier si c'est une question à élimination dure
    is_hard_elimination = (
        q.key in hard_elimination_keys or
        any(q.key.startswith(prefix) for prefix in hard_elimination_prefixes)
    )
    
    if ans == "y":
        # ÉLIMINATION IMMÉDIATE sur TOUTES les questions "y"
        to_keep = []
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is True:
                # Film correspond → GARDER avec boost
                state.scores[mid] = state.scores.get(mid, 0.0) + 5.0
                to_keep.append(m)
            elif r is None:
                # Données manquantes → GARDER avec pénalité
                state.scores[mid] = state.scores.get(mid, 0.0) - 1.0
                to_keep.append(m)
            # Si r is False → ÉLIMINER (ne pas ajouter à to_keep)
        
        state.candidates = to_keep
        remaining_ids = {movie_id(m) for m in state.candidates if movie_id(m) is not None}
        state.scores = {mid: score for mid, score in state.scores.items() if mid in remaining_ids}
        state.strikes = {mid: strikes for mid, strikes in state.strikes.items() if mid in remaining_ids}

    elif ans == "n":
        # ÉLIMINATION IMMÉDIATE sur TOUTES les questions "n"
        to_keep = []
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is False:
                # Film ne correspond pas → GARDER avec boost
                state.scores[mid] = state.scores.get(mid, 0.0) + 3.0
                to_keep.append(m)
            elif r is None:
                # Données manquantes → GARDER avec boost léger
                state.scores[mid] = state.scores.get(mid, 0.0) + 0.5
                to_keep.append(m)
            # Si r is True → ÉLIMINER (ne pas ajouter à to_keep)
        
        state.candidates = to_keep
        remaining_ids = {movie_id(m) for m in state.candidates if movie_id(m) is not None}
        state.scores = {mid: score for mid, score in state.scores.items() if mid in remaining_ids}
        state.strikes = {mid: strikes for mid, strikes in state.strikes.items() if mid in remaining_ids}

    elif ans == "py":
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is True:
                boost = 1.5 if is_hard_elimination else 0.5
                state.scores[mid] = state.scores.get(mid, 0.0) + boost
            elif r is False:
                penalty = -2.0 if is_hard_elimination else -0.75
                state.scores[mid] = state.scores.get(mid, 0.0) + penalty

    elif ans == "pn":
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is False:
                boost = 1.5 if is_hard_elimination else 0.5
                state.scores[mid] = state.scores.get(mid, 0.0) + boost
            elif r is True:
                penalty = -2.0 if is_hard_elimination else -0.75
                state.scores[mid] = state.scores.get(mid, 0.0) + penalty

    elif ans == "?":
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is None:
                state.scores[mid] = state.scores.get(mid, 0.0) + 0.2

    # Élimination par strikes (sauf si c'était une question à élimination dure, déjà géré)
    if not is_hard_elimination:
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
    RÈGLES STRICTES - Guess UNIQUEMENT dans 3 cas:
    1. Un seul candidat restant
    2. Score du #1 est 2x supérieur au #2
    3. Le même film est #1 pendant 10 questions d'affilée
    """
    # CAS 1: Un seul candidat
    if len(state.candidates) == 1:
        return True
    
    # CAS 2: Score 2x supérieur au #2
    if len(state.candidates) >= 2:
        s1 = score_of(state, state.candidates[0])
        s2 = score_of(state, state.candidates[1])
        
        # Le #1 doit avoir un score 2x supérieur au #2
        if s2 > 0 and (s1 / s2) >= 2.0:
            return True
        # Cas spécial: #2 négatif mais #1 très positif
        elif s2 <= 0 and s1 >= 10.0:
            return True
    
    # CAS 3: Streak de 10 questions minimum
    if state.top_streak_len >= 10:
        return True
    
    # Sinon: PAS DE GUESS, continuer les questions
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
    parser.add_argument("--guess-cooldown", type=int, default=2, help="Après un guess raté, forcer au moins N questions avant de reguesser (évite les guesses en chaîne)")
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
                    
                    # CORRECTION: Décrémenter le cooldown aussi ici
                    if state.guess_cooldown > 0:
                        state.guess_cooldown -= 1

                    update_state_with_answer(state, tq, ans, max_strikes=max_strikes, debug_target_id=debug_target_id)
                    print(f"Restants: {len(state.candidates)}")
                    print()
            
            # STRICT MODE: Vérifier UNIQUEMENT les 3 règles strictes
            # Pas de guess prématuré basé sur le nombre de candidats
            
            # Si on entre en mode guess (selon les 3 règles strictes) ET pas de cooldown
            if should_enter_guess_mode(state) and state.guess_cooldown == 0:
                top = state.candidates[0]
                guess = short_movie_str(top)
                
                # Afficher la raison du guess
                if len(state.candidates) == 1:
                    print(f"\n✅ UN SEUL CANDIDAT RESTANT!")
                elif len(state.candidates) >= 2:
                    s1 = score_of(state, state.candidates[0])
                    s2 = score_of(state, state.candidates[1])
                    if s2 > 0:
                        ratio = s1 / s2
                        print(f"\n💯 DOMINATION 2X (Ratio: {ratio:.1f}x)")
                    else:
                        print(f"\n💯 DOMINATION ABSOLUE (Score #1: {s1:.1f})")
                elif state.top_streak_len >= 10:
                    print(f"\n🔥 STREAK DE {state.top_streak_len} QUESTIONS!")
                
                if ask_yes_no(f"Je pense que c'est: {guess}. C'est ça ? (y/n) : "):
                    print("\n✅ J'AI TROUVÉ :", guess)
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
                    print("OK, je continue avec plus de questions.\n")
                    continue
            
            # Seulement maintenant on génère les questions (si on n'a pas guess)
            dyn_kw = build_dynamic_keyword_questions(conn, state.candidates, state.asked, top_k=80)
            dyn_people = build_dynamic_questions(conn, state.candidates, state.asked, top_k=60)
            dyn_years = build_dynamic_year_questions(state.candidates, state.asked)
            
            # NOUVEAU: Questions de VALIDATION du TOP candidat (priorité élevée)
            validation_questions = build_top_validation_questions(conn, state.candidates, state.asked)
            
            # STRATÉGIE: Mettre les questions de validation EN PREMIER pour boost naturel
            merged_questions = validation_questions + dyn_kw + dyn_people + dyn_years + questions

            # AMÉLIORATION: Ajouter de l'aléatoire sur la première question
            is_first = (state.question_count == 0)
            q = choose_best_question(state.candidates, merged_questions, state.asked, is_first_question=is_first, state=state)
            
            # STRICT MODE: Si plus de questions disponibles ET plusieurs candidats
            if q is None:
                if len(state.candidates) == 1:
                    # Un seul candidat: guess automatique
                    print("\n✅ UN SEUL CANDIDAT RESTANT!")
                    print("J'AI TROUVÉ :", short_movie_str(state.candidates[0]))
                    print(f"Questions: {state.question_count}")
                    return 0
                else:
                    # Plusieurs candidats mais plus de questions
                    print(f"\n⚠️ Plus de questions automatiques disponibles.")
                    print(f"Il reste {len(state.candidates)} candidats. Voici le top 5:")
                    print_top(state, limit=min(5, len(state.candidates)))
                    print()
                    
                    # Forcer l'utilisateur à éliminer manuellement
                    choice = input("Tape le numéro du film correct (1-5) ou 'e' pour éliminer le #1 et continuer : ").strip().lower()
                    
                    if choice in ['1', '2', '3', '4', '5']:
                        idx = int(choice) - 1
                        if idx < len(state.candidates):
                            print("\n✅ J'AI TROUVÉ :", short_movie_str(state.candidates[idx]))
                            print(f"Questions: {state.question_count}")
                            return 0
                    elif choice == 'e':
                        # Éliminer le #1 et continuer
                        top = state.candidates[0]
                        mid = movie_id(top)
                        if mid is not None:
                            eliminate_movie(state, mid)
                        sort_candidates(state)
                        print(f"OK, {short_movie_str(top)} éliminé. Il reste {len(state.candidates)} candidats.\n")
                        continue
                    else:
                        print("Choix invalide, je continue.\n")
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
            
            # NOUVEAU: Tracker le type de question pour diversité
            q_type = get_question_type(q)
            state.recent_question_types.append(q_type)
            # Garder seulement les 10 dernières pour économiser mémoire
            if len(state.recent_question_types) > 10:
                state.recent_question_types = state.recent_question_types[-10:]
            
            # NOUVEAU: Si on répond "oui" à une question de langue, exclure TOUTES les autres
            if ans == "y" and q.key.startswith("language_"):
                all_languages = {"language_en", "language_fr", "language_ja", "language_es", 
                               "language_de", "language_it", "language_ko", "language_zh"}
                # Ajouter toutes les autres langues à "asked" pour les exclure
                for lang in all_languages:
                    if lang != q.key:  # Sauf celle qu'on vient de confirmer
                        state.asked.add(lang)
                print(f"   [Langue confirmée: {q.key.replace('language_', '')} - Autres langues exclues]")
            
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

                if state.top_streak_len >= 9 and state.guess_cooldown == 0:
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
                        state.consecutive_guesses += 1
                        print("OK, je continue.\n")
                        continue
            print()

    finally:
        close_connection()

if __name__ == "__main__":
    raise SystemExit(main())



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

        # ÉPOQUE / SORTIE - DÉCENNIES PRÉCISES
        Question("decade_1970s", "Est-ce que c'est sorti dans les années 1970 (1970-1979) ?", pred_decade(1970)),
        Question("decade_1980s", "Est-ce que c'est sorti dans les années 1980 (1980-1989) ?", pred_decade(1980)),
        Question("decade_1990s", "Est-ce que c'est sorti dans les années 1990 (1990-1999) ?", pred_decade(1990)),
        Question("decade_2000s", "Est-ce que c'est sorti dans les années 2000 (2000-2009) ?", pred_decade(2000)),
        Question("decade_2010s", "Est-ce que c'est sorti dans les années 2010 (2010-2019) ?", pred_decade(2010)),
        Question("decade_2020s", "Est-ce que c'est sorti dans les années 2020+ (2020-2029) ?", pred_decade(2020)),
        
        # PÉRIODES LARGES (toujours utiles pour affiner)
        Question("before_2000", "Est-ce que c'est sorti avant 2000 ?", pred_before_year(2000)),
        Question("after_2010", "Est-ce que c'est sorti en 2010 ou après ?", pred_after_year(2010)),

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
        
        # LANGUE ORIGINALE - EXCLUSION MUTUELLE TOTALE
        # Dès qu'on répond "oui" à une langue, toutes les autres sont exclues
        Question("language_en", "La langue originale est-elle l'anglais ?", pred_language("en")),
        Question("language_fr", "La langue originale est-elle le français ?", pred_language("fr")),
        Question("language_ja", "La langue originale est-elle le japonais ?", pred_language("ja")),
        Question("language_es", "La langue originale est-elle l'espagnol ?", pred_language("es")),
        Question("language_de", "La langue originale est-elle l'allemand ?", pred_language("de")),
        Question("language_it", "La langue originale est-elle l'italien ?", pred_language("it")),
        Question("language_ko", "La langue originale est-elle le coréen ?", pred_language("ko")),
        Question("language_zh", "La langue originale est-elle le chinois ?", pred_language("zh")),

        # SUCCÈS / POPULARITÉ
        Question("popular", "Est-ce que c'est un film très populaire ?", pred_popularity_ge(50)),
        Question("very_popular", "Est-ce que c'est un film culte ou ultra connu ?", pred_popularity_ge(80)),

        # FINANCES - AVEC EXCLUSIONS LOGIQUES
        Question("big_budget", "Est-ce que le film a un gros budget (plus de 50 000 000) ?", pred_budget_ge(conn, 50_000_000)),
        Question("small_budget", "Est-ce que le film a un petit budget (moins de 10 000 000) ?", pred_budget_lt(conn, 10_000_000),
                excludes={"big_budget"}),  # NOUVEAU: si gros budget, ne pas demander petit budget
        Question("box_office_success", "Est-ce que le film a bien marché au box-office (plus de 100 000 000 de revenu) ?", pred_revenue_ge(conn, 100_000_000)),
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

def build_top_validation_questions(
    conn: sqlite3.Connection,
    candidates: List[dict],
    asked: Set[str],
) -> List[Question]:
    """
    NOUVEAU: Génère des questions SPÉCIFIQUES au film #1 pour le valider/éliminer rapidement.
    
    Stratégie: Au lieu d'éliminer 149 autres films, on pose des questions sur le #1:
    - Si réponse OUI → Le #1 se confirme
    - Si réponse NON → Le #1 est ÉLIMINÉ immédiatement !
    
    Beaucoup plus rapide !
    """
    if len(candidates) < 50 or len(candidates) > 200:
        return []  # Seulement quand 50-200 candidats
    
    top = candidates[0]
    mid = movie_id(top)
    if mid is None:
        return []
    
    questions: List[Question] = []
    details = get_details(conn, mid)
    
    # 1. ACTEURS PRINCIPAUX du film #1
    cast = details.get("credits", {}).get("cast", [])
    if isinstance(cast, list):
        for actor in cast[:5]:  # Top 5 acteurs
            if isinstance(actor, dict):
                name = actor.get("name", "").strip()
                if name:
                    key = f"validate_actor_{name.replace(' ', '_').lower()}"
                    if key not in asked:
                        text = f"[VALIDATION #1] Est-ce que {name} joue dedans ?"
                        questions.append(Question(key, text, pred_actor_in_cast(conn, name)))
    
    # 2. RÉALISATEUR du film #1
    crew = details.get("credits", {}).get("crew", [])
    if isinstance(crew, list):
        for person in crew:
            if isinstance(person, dict) and person.get("job") == "Director":
                name = person.get("name", "").strip()
                if name:
                    key = f"validate_director_{name.replace(' ', '_').lower()}"
                    if key not in asked:
                        text = f"[VALIDATION #1] Est-ce réalisé par {name} ?"
                        questions.append(Question(key, text, pred_has_director(conn, name)))
                    break
    
    # 3. KEYWORDS SPÉCIFIQUES du film #1
    keywords = details.get("keywords", {}).get("keywords", [])
    if isinstance(keywords, list):
        for kw in keywords[:10]:  # Top 10 keywords
            if isinstance(kw, dict):
                name = kw.get("name", "").strip().lower()
                if name:
                    key = f"validate_keyword_{name.replace(' ', '_')}"
                    if key not in asked:
                        text = f"[VALIDATION #1] Le film contient-il '{name}' ?"
                        questions.append(Question(key, text, pred_keyword(conn, name)))
    
    # 4. ANNÉE EXACTE du film #1
    year = safe_year(top.get("release_date"))
    if year:
        key = f"validate_year_{year}"
        if key not in asked:
            text = f"[VALIDATION #1] Est-ce sorti en {year} ?"
            questions.append(Question(key, text, pred_exact_year(year)))
    
    # 5. TITRE du film #1 (première lettre)
    title = str(top.get("title", "")).strip()
    if title:
        first_letter = title[0].upper()
        key = f"validate_title_{first_letter}"
        if key not in asked:
            text = f"[VALIDATION #1] Le titre commence-t-il par '{first_letter}' ?"
            questions.append(Question(key, text, pred_title_starts_with(first_letter)))
    
    return questions[:15]  # Max 15 questions de validation


def build_dynamic_keyword_questions(
    conn: sqlite3.Connection,
    candidates: List[dict],
    asked: Set[str],
    top_k: int = 80,
) -> List[Question]:
    """
    Questions dynamiques basées sur les keywords les plus fréquents dans le pool.
    STRICT MODE: Génère BEAUCOUP plus de questions pour affiner.
    """
    from collections import Counter
    
    # STRICT MODE: Générer même avec plus de candidats
    if len(candidates) > 200:  # Augmenté de 100 à 200
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
    
    # STRICT MODE: Augmenter top_k si peu de candidats
    actual_top_k = top_k
    if len(candidates) <= 10:
        actual_top_k = 200  # Beaucoup plus de questions
    elif len(candidates) <= 30:
        actual_top_k = 150
    elif len(candidates) <= 50:
        actual_top_k = 120
    
    for kw, count in keyword_counter.most_common(actual_top_k):
        # STRICT MODE: Accepter même 1 seul film avec ce keyword (au lieu de 2)
        if count < 1:
            continue
        key = f"dyn_keyword_{kw.replace(' ', '_')}"
        if key in asked:
            continue
        text = f"Le film contient-il le thème/keyword '{kw}' ?"
        questions.append(Question(key, text, pred_keyword(conn, kw)))

    return questions


def detect_dominant_language(candidates: List[dict]) -> Optional[str]:
    """
    Détecte la langue originale dominante parmi les candidats.
    Retourne le code langue (en, fr, ja, es, etc.) ou None si mixte.
    """
    from collections import Counter
    
    if not candidates:
        return None
    
    lang_counter: Counter = Counter()
    for m in candidates:
        lang = m.get("original_language", "")
        if lang:
            lang_counter[lang] += 1
    
    if not lang_counter:
        return None
    
    # Si une langue représente 70%+ des candidats, c'est la langue dominante
    total = len(candidates)
    most_common_lang, count = lang_counter.most_common(1)[0]
    
    if count / total >= 0.70:
        return most_common_lang
    
    return None  # Trop mixte


# =========================
# ACTEURS CÉLÈBRES (par décennie + par pays) — utilisé pour questions dynamiques
# =========================

ACTORS_BY_DECADE_EN = {
    1960: [
        "Sean Connery", "Paul Newman", "Steve McQueen", "Clint Eastwood", "Marlon Brando",
        "Sidney Poitier", "Audrey Hepburn", "Elizabeth Taylor", "Julie Andrews", "Cary Grant",
        "Peter O'Toole", "Henry Fonda"
    ],
    1970: [
        "Al Pacino", "Robert De Niro", "Jack Nicholson", "Dustin Hoffman", "Gene Hackman",
        "Donald Sutherland", "Harrison Ford", "Sylvester Stallone", "Diane Keaton", "Jane Fonda",
        "Faye Dunaway", "Goldie Hawn", "John Cazale", "Burt Reynolds", "Christopher Walken"
    ],
    1980: [
        "Tom Cruise", "Arnold Schwarzenegger", "Sylvester Stallone", "Harrison Ford", "Eddie Murphy",
        "Michael J. Fox", "Bruce Willis", "Mel Gibson", "Meryl Streep", "Sigourney Weaver",
        "Michelle Pfeiffer", "Whoopi Goldberg", "Bill Murray", "Kevin Costner", "Sean Penn"
    ],
    1990: [
        "Leonardo DiCaprio", "Brad Pitt", "Tom Hanks", "Johnny Depp", "Will Smith",
        "Morgan Freeman", "Keanu Reeves", "Denzel Washington", "Julia Roberts", "Sandra Bullock",
        "Nicole Kidman", "Jodie Foster", "Matt Damon", "Jim Carrey", "Samuel L. Jackson"
    ],
    2000: [
        "Tom Cruise", "Leonardo DiCaprio", "Brad Pitt", "Johnny Depp", "Christian Bale",
        "George Clooney", "Russell Crowe", "Matt Damon", "Angelina Jolie", "Natalie Portman",
        "Cate Blanchett", "Keira Knightley", "Hugh Jackman", "Daniel Craig", "Sean Penn"
    ],
    2010: [
        "Robert Downey Jr.", "Leonardo DiCaprio", "Chris Hemsworth", "Chris Evans", "Ryan Gosling",
        "Brad Pitt", "Dwayne Johnson", "Joaquin Phoenix", "Scarlett Johansson", "Jennifer Lawrence",
        "Emma Stone", "Margot Robbie", "Amy Adams", "Christian Bale", "Benedict Cumberbatch"
    ],
    2020: [
        "Timothée Chalamet", "Zendaya", "Florence Pugh", "Anya Taylor-Joy", "Austin Butler",
        "Cillian Murphy", "Margot Robbie", "Robert Pattinson", "Pedro Pascal", "Ryan Gosling",
        "Jenna Ortega", "Paul Mescal", "Barry Keoghan", "Sydney Sweeney", "Jason Momoa"
    ],
}

ACTORS_FR = [
    "Jean Gabin", "Alain Delon", "Jean-Paul Belmondo", "Gérard Depardieu", "Louis de Funès",
    "Jean Reno", "Omar Sy", "Vincent Cassel", "Marion Cotillard", "Catherine Deneuve",
    "Isabelle Adjani", "Brigitte Bardot", "Juliette Binoche", "Michel Piccoli", "Patrick Dewaere",
    "Daniel Auteuil", "Yves Montand", "Jean Dujardin", "François Cluzet", "Bourvil",
    "Sophie Marceau", "Michel Serrault", "Jean-Pierre Léaud", "Romain Duris", "Gaspard Ulliel"
]

ACTORS_ES = [
    "Antonio Banderas", "Penélope Cruz", "Javier Bardem", "Fernando Rey", "Carmen Maura",
    "Victoria Abril", "Eduard Fernández", "Jordi Mollà", "Paz Vega", "Álex González",
    "Luis Tosar", "Maribel Verdú", "Sergi López", "Antonio de la Torre",
    "Raúl Arévalo", "Inma Cuesta", "Karra Elejalde", "Emma Suárez", "Najwa Nimri",
    "Mario Casas", "Blanca Portillo", "José Sacristán", "Imanol Arias", "Ana Torrent"
]

ACTORS_DE = [
    "Bruno Ganz", "Christoph Waltz", "Diane Kruger", "Til Schweiger",
    "Moritz Bleibtreu", "Nina Hoss", "Daniel Brühl", "Jürgen Prochnow", "August Diehl",
    "Hannah Herzsprung", "Sebastian Koch", "Heiner Lauterbach", "Lars Eidinger", "Maria Schrader",
    "Ulrich Mühe", "Sibel Kekilli", "Volker Bruch", "Barbara Sukowa",
    "Klaus Kinski", "Romy Schneider", "Brigitte Helm", "Tom Schilling", "Matthias Schweighöfer"
]

ACTORS_JA = [
    "Toshiro Mifune", "Takashi Shimura", "Ken Watanabe", "Issey Ogata", "Hiroyuki Sanada",
    "Rinko Kikuchi", "Tadanobu Asano", "Koji Yakusho", "Takeshi Kitano", "Yû Aoi",
    "Shin'ichi Tsutsumi", "Satomi Ishihara", "Masami Nagasawa", "Kankurō Nakamura",
    "Kazuki Kitamura", "Ayase Haruka", "Sho Sakurai", "Masahiro Motoki", "Yôsuke Eguchi",
    "Ryō Yoshizawa", "Kento Yamazaki", "Suzu Hirose", "Fumiyo Kohinata", "Shota Sometani"
]

ACTORS_IT = [
    "Marcello Mastroianni", "Sophia Loren", "Vittorio Gassman", "Alberto Sordi", "Gina Lollobrigida",
    "Monica Bellucci", "Claudia Cardinale", "Totò", "Roberto Benigni", "Pierfrancesco Favino",
    "Isabella Rossellini", "Raoul Bova", "Sergio Castellitto", "Asia Argento", "Stefania Sandrelli",
    "Valeria Golino", "Franco Nero", "Bud Spencer", "Terence Hill", "Giancarlo Giannini",
    "Elio Germano", "Toni Servillo", "Silvana Mangano", "Luigi Lo Cascio", "Riccardo Scamarcio"
]


def get_decade_from_year(year: Optional[int]) -> Optional[int]:
    if year is None:
        return None
    return (year // 10) * 10


def detect_dominant_decade(candidates: List[dict]) -> Optional[int]:
    """Décennie dominante si elle représente >= 70% des candidats."""
    from collections import Counter

    if not candidates:
        return None

    decade_counter: Counter = Counter()
    for m in candidates:
        year = safe_year(m.get("release_date"))
        decade = get_decade_from_year(year)
        if decade is not None:
            decade_counter[decade] += 1

    if not decade_counter:
        return None

    total = len(candidates)
    most_common_decade, count = decade_counter.most_common(1)[0]
    if count / total >= 0.70:
        return most_common_decade
    return None


def get_relevant_actors(dominant_language: Optional[str], dominant_decade: Optional[int]) -> List[str]:
    """Réduit le bruit: pour 'en' filtre par décennie, pour autres langues liste pays."""
    if dominant_language is None:
        return ACTORS_BY_DECADE_EN.get(2020, [])

    if dominant_language == "en":
        if dominant_decade is None or dominant_decade < 1960:
            return ACTORS_BY_DECADE_EN.get(2020, [])
        if dominant_decade in ACTORS_BY_DECADE_EN:
            return ACTORS_BY_DECADE_EN[dominant_decade]
        available = sorted(ACTORS_BY_DECADE_EN.keys())
        closest = min(available, key=lambda x: abs(x - dominant_decade))
        return ACTORS_BY_DECADE_EN[closest]

    if dominant_language == "fr":
        return ACTORS_FR
    if dominant_language == "es":
        return ACTORS_ES
    if dominant_language == "de":
        return ACTORS_DE
    if dominant_language == "ja":
        return ACTORS_JA
    if dominant_language == "it":
        return ACTORS_IT

    return ACTORS_BY_DECADE_EN.get(2020, [])


# Mapping acteurs célèbres → nationalité (code langue)
# Cette liste sera enrichie au fur et à mesure
ACTOR_NATIONALITY = {
    # Acteurs américains/anglais (en)
    "leonardo dicaprio": "en",
    "brad pitt": "en",
    "tom hanks": "en",
    "robert downey jr.": "en",
    "scarlett johansson": "en",
    "jennifer lawrence": "en",
    "tom cruise": "en",
    "will smith": "en",
    "denzel washington": "en",
    "morgan freeman": "en",
    "samuel l. jackson": "en",
    "christian bale": "en",
    "matt damon": "en",
    "mark wahlberg": "en",
    "johnny depp": "en",
    "angelina jolie": "en",
    "sandra bullock": "en",
    "julia roberts": "en",
    "meryl streep": "en",
    "kate winslet": "en",
    "cate blanchett": "en",
    "hugh jackman": "en",
    "chris hemsworth": "en",
    "chris evans": "en",
    "chris pratt": "en",
    "robert pattinson": "en",
    "emma watson": "en",
    "daniel radcliffe": "en",
    "rupert grint": "en",
    "harrison ford": "en",
    "mark hamill": "en",
    "carrie fisher": "en",
    "natalie portman": "en",
    "ewan mcgregor": "en",
    "ian mckellen": "en",
    "patrick stewart": "en",
    "ben affleck": "en",
    "ryan gosling": "en",
    "ryan reynolds": "en",
    "keanu reeves": "en",
    "charlize theron": "en",
    "michael fassbender": "en",
    "james mcavoy": "en",
    "benedict cumberbatch": "en",
    "tom hiddleston": "en",
    "eddie redmayne": "en",
    
    # Acteurs français (fr)
    "marion cotillard": "fr",
    "omar sy": "fr",
    "jean reno": "fr",
    "gérard depardieu": "fr",
    "vincent cassel": "fr",
    "jean dujardin": "fr",
    "audrey tautou": "fr",
    "léa seydoux": "fr",
    "sophie marceau": "fr",
    "isabelle huppert": "fr",
    "juliette binoche": "fr",
    "lambert wilson": "fr",
    "mathieu amalric": "fr",
    "romain duris": "fr",
    "gad elmaleh": "fr",
    "dany boon": "fr",
    "françois cluzet": "fr",
    "benoît magimel": "fr",
    "audrey dana": "fr",
    
    # Acteurs espagnols (es)
    "penélope cruz": "es",
    "javier bardem": "es",
    "antonio banderas": "es",
    "ricardo darín": "es",
    "adrián suar": "es",
    "guillermo campra": "es",
    "dani martín": "es",
    
    # Acteurs japonais (ja)
    "ken watanabe": "ja",
    "rinko kikuchi": "ja",
    "toshiro mifune": "ja",
    "mari natsuki": "ja",
    
    # Acteurs allemands (de)
    "diane kruger": "de",
    "til schweiger": "de",
    "daniel brühl": "de",
    "christoph waltz": "de",
    
    # Acteurs italiens (it)
    "sophia loren": "it",
    "marcello mastroianni": "it",
    "roberto benigni": "it",
    "monica bellucci": "it",
    "damiano russo": "it",
}


def should_include_actor(actor_name: str, dominant_language: Optional[str], relevant_actor_set: Optional[Set[str]] = None) -> bool:
    """
    Détermine si on doit poser une question sur cet acteur.

    Règles:
    - Si relevant_actor_set est fourni (mode "réduction de bruit"), on garde uniquement les acteurs dans ce set.
    - Sinon, on filtre par langue dominante via ACTOR_NATIONALITY (si connu).
    - Si la langue est mixte ou inconnue, on accepte.
    """
    if relevant_actor_set is not None:
        return actor_name in relevant_actor_set

    if dominant_language is None:
        return True

    actor_lower = actor_name.lower().strip()
    actor_lang = ACTOR_NATIONALITY.get(actor_lower)

    if actor_lang is None:
        return True  # Acteur inconnu, on garde par défaut

    return actor_lang == dominant_language


def build_dynamic_questions(
    conn: sqlite3.Connection,
    candidates: List[dict],
    asked: Set[str],
    top_k: int = 60,
) -> List[Question]:
    """
    Questions dynamiques basées sur acteurs/réalisateurs fréquents dans le pool.
    SMART MODE: Filtre les acteurs selon la langue dominante des candidats.
    """
    from collections import Counter
    
    # STRICT MODE: Générer même avec plus de candidats
    if len(candidates) > 200:  # Augmenté de 100 à 200
        return []

    # NOUVEAU: Détecter la langue dominante
    dominant_language = detect_dominant_language(candidates)
    dominant_decade = detect_dominant_decade(candidates)
    relevant_actor_set = set(get_relevant_actors(dominant_language, dominant_decade))
    
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
            # STRICT MODE: Regarder TOUS les acteurs (pas juste top 5)
            max_actors = 15 if len(candidates) <= 20 else 10
            for c in cast[:max_actors]:
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
    
    # STRICT MODE: Augmenter top_k si peu de candidats
    actual_top_k = top_k
    if len(candidates) <= 10:
        actual_top_k = 150
    elif len(candidates) <= 30:
        actual_top_k = 120
    elif len(candidates) <= 50:
        actual_top_k = 100

    # NOUVEAU: Filtrer les acteurs selon la langue dominante
    for actor, count in actor_counter.most_common(actual_top_k):
        # STRICT MODE: Accepter même 1 seul film (au lieu de 2)
        if count < 1:
            continue
        
        # SMART FILTER: Vérifier si l'acteur correspond à la langue dominante
        if not should_include_actor(actor, dominant_language, relevant_actor_set):
            continue  # Skip cet acteur s'il ne correspond pas
        
        key = f"dyn_actor_{actor.replace(' ', '_').lower()}"
        if key in asked:
            continue
        text = f"Est-ce que {actor} joue dedans ?"
        questions.append(Question(key, text, pred_actor_in_cast(conn, actor)))

    for director, count in director_counter.most_common(actual_top_k):
        if count < 1:  # STRICT MODE: 1 au lieu de 2
            continue
        key = f"dyn_director_{director.replace(' ', '_').lower()}"
        if key in asked:
            continue
        text = f"Est-ce réalisé par {director} ?"
        questions.append(Question(key, text, pred_has_director(conn, director)))

    return questions


def build_dynamic_year_questions(
    candidates: List[dict],
    asked: Set[str],
) -> List[Question]:
    """
    STRICT MODE: Génère des questions d'années spécifiques pour TOUS les candidats.
    Plus on a peu de candidats, plus on génère de questions précises.
    """
    from collections import Counter
    
    # STRICT MODE: Générer jusqu'à 100 candidats (au lieu de 50)
    if len(candidates) > 100 or len(candidates) < 2:
        return []
    
    year_counter: Counter = Counter()
    
    for m in candidates:
        y = safe_year(m.get("release_date"))
        if y is not None:
            year_counter[y] += 1
    
    questions: List[Question] = []
    
    # STRICT MODE: Générer pour toutes les années (même avec 1 seul film)
    max_questions = 20 if len(candidates) <= 10 else 15
    
    for year, count in year_counter.most_common(max_questions):
        # STRICT MODE: Même 1 seul film suffit (au lieu de 2)
        if count < 1:
            continue
        
        key = f"year_{year}"
        if key in asked:
            continue
        
        text = f"Est-ce que c'est sorti en {year} ?"
        questions.append(Question(key, text, pred_exact_year(year)))
    
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
    recent_question_types: List[str]  # NOUVEAU: historique des types récents (max 5)


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
        recent_question_types=[],  # NOUVEAU
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
        recent_question_types=list(state.recent_question_types),  # NOUVEAU
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
    NOUVEAU: Élimination DURE pour toutes les caractéristiques mutuellement exclusives
    """
    # NOUVEAU: Identification des questions à élimination DURE
    # Ce sont des questions où la réponse est binaire/mutuellement exclusive
    
    hard_elimination_prefixes = [
        "franchise_",      # Franchises (Marvel, Star Wars, etc.)
        "language_",       # Langues (en, fr, ja, etc.)
        "director_",       # Réalisateurs spécifiques (Nolan, Spielberg, etc.)
        "joker_title_",    # Première lettre du titre (A-D, E-H, etc.)
        "char_",           # Personnages principaux (Batman, Harry Potter, etc.)
        "decade_",         # NOUVEAU: Décennies (1980s, 1990s, etc.)
        "year_",           # NOUVEAU: Années spécifiques (2010, 2015, etc.)
    ]
    
    hard_elimination_keys = {
        "is_animation",     # Animation vs Live-action
        "is_live_action",
        "is_short",         # Court-métrage vs Long-métrage
        "is_feature",
        "runtime_lt_90",    # Durée du film
        "runtime_ge_150",
        "before_2000",      # Dates de sortie larges
        "after_2010",
        "is_saga",          # Franchise vs Standalone
        "is_standalone",
        "big_budget",       # Budget
        "small_budget",
        "is_american",      # Pays d'origine
        "is_french",
        "is_european",
        "is_asian",
    }
    
    # Vérifier si c'est une question à élimination dure
    is_hard_elimination = (
        q.key in hard_elimination_keys or
        any(q.key.startswith(prefix) for prefix in hard_elimination_prefixes)
    )
    
    if ans == "y":
        # ÉLIMINATION IMMÉDIATE sur TOUTES les questions "y"
        to_keep = []
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is True:
                # Film correspond → GARDER avec boost
                state.scores[mid] = state.scores.get(mid, 0.0) + 5.0
                to_keep.append(m)
            elif r is None:
                # Données manquantes → GARDER avec pénalité
                state.scores[mid] = state.scores.get(mid, 0.0) - 1.0
                to_keep.append(m)
            # Si r is False → ÉLIMINER (ne pas ajouter à to_keep)
        
        state.candidates = to_keep
        remaining_ids = {movie_id(m) for m in state.candidates if movie_id(m) is not None}
        state.scores = {mid: score for mid, score in state.scores.items() if mid in remaining_ids}
        state.strikes = {mid: strikes for mid, strikes in state.strikes.items() if mid in remaining_ids}

    elif ans == "n":
        # ÉLIMINATION IMMÉDIATE sur TOUTES les questions "n"
        to_keep = []
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is False:
                # Film ne correspond pas → GARDER avec boost
                state.scores[mid] = state.scores.get(mid, 0.0) + 3.0
                to_keep.append(m)
            elif r is None:
                # Données manquantes → GARDER avec boost léger
                state.scores[mid] = state.scores.get(mid, 0.0) + 0.5
                to_keep.append(m)
            # Si r is True → ÉLIMINER (ne pas ajouter à to_keep)
        
        state.candidates = to_keep
        remaining_ids = {movie_id(m) for m in state.candidates if movie_id(m) is not None}
        state.scores = {mid: score for mid, score in state.scores.items() if mid in remaining_ids}
        state.strikes = {mid: strikes for mid, strikes in state.strikes.items() if mid in remaining_ids}

    elif ans == "py":
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is True:
                boost = 1.5 if is_hard_elimination else 0.5
                state.scores[mid] = state.scores.get(mid, 0.0) + boost
            elif r is False:
                penalty = -2.0 if is_hard_elimination else -0.75
                state.scores[mid] = state.scores.get(mid, 0.0) + penalty

    elif ans == "pn":
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is False:
                boost = 1.5 if is_hard_elimination else 0.5
                state.scores[mid] = state.scores.get(mid, 0.0) + boost
            elif r is True:
                penalty = -2.0 if is_hard_elimination else -0.75
                state.scores[mid] = state.scores.get(mid, 0.0) + penalty

    elif ans == "?":
        for m in state.candidates:
            mid = movie_id(m)
            if mid is None:
                continue
            r = q.predicate(m)
            if r is None:
                state.scores[mid] = state.scores.get(mid, 0.0) + 0.2

    # Élimination par strikes (sauf si c'était une question à élimination dure, déjà géré)
    if not is_hard_elimination:
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
    RÈGLES STRICTES - Guess UNIQUEMENT dans 3 cas:
    1. Un seul candidat restant
    2. Score du #1 est 2x supérieur au #2
    3. Le même film est #1 pendant 10 questions d'affilée
    """
    # CAS 1: Un seul candidat
    if len(state.candidates) == 1:
        return True
    
    # CAS 2: Score 2x supérieur au #2
    if len(state.candidates) >= 2:
        s1 = score_of(state, state.candidates[0])
        s2 = score_of(state, state.candidates[1])
        
        # Le #1 doit avoir un score 2x supérieur au #2
        if s2 > 0 and (s1 / s2) >= 2.0:
            return True
        # Cas spécial: #2 négatif mais #1 très positif
        elif s2 <= 0 and s1 >= 10.0:
            return True
    
    # CAS 3: Streak de 10 questions minimum
    if state.top_streak_len >= 10:
        return True
    
    # Sinon: PAS DE GUESS, continuer les questions
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
    parser.add_argument("--guess-cooldown", type=int, default=2, help="Après un guess raté, forcer au moins N questions avant de reguesser (évite les guesses en chaîne)")
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
                    
                    # CORRECTION: Décrémenter le cooldown aussi ici
                    if state.guess_cooldown > 0:
                        state.guess_cooldown -= 1

                    update_state_with_answer(state, tq, ans, max_strikes=max_strikes, debug_target_id=debug_target_id)
                    print(f"Restants: {len(state.candidates)}")
                    print()
            
            # STRICT MODE: Vérifier UNIQUEMENT les 3 règles strictes
            # Pas de guess prématuré basé sur le nombre de candidats
            
            # Si on entre en mode guess (selon les 3 règles strictes) ET pas de cooldown
            if should_enter_guess_mode(state) and state.guess_cooldown == 0:
                top = state.candidates[0]
                guess = short_movie_str(top)
                
                # Afficher la raison du guess
                if len(state.candidates) == 1:
                    print(f"\n✅ UN SEUL CANDIDAT RESTANT!")
                elif len(state.candidates) >= 2:
                    s1 = score_of(state, state.candidates[0])
                    s2 = score_of(state, state.candidates[1])
                    if s2 > 0:
                        ratio = s1 / s2
                        print(f"\n💯 DOMINATION 2X (Ratio: {ratio:.1f}x)")
                    else:
                        print(f"\n💯 DOMINATION ABSOLUE (Score #1: {s1:.1f})")
                elif state.top_streak_len >= 10:
                    print(f"\n🔥 STREAK DE {state.top_streak_len} QUESTIONS!")
                
                if ask_yes_no(f"Je pense que c'est: {guess}. C'est ça ? (y/n) : "):
                    print("\n✅ J'AI TROUVÉ :", guess)
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
                    print("OK, je continue avec plus de questions.\n")
                    continue
            
            # Seulement maintenant on génère les questions (si on n'a pas guess)
            dyn_kw = build_dynamic_keyword_questions(conn, state.candidates, state.asked, top_k=80)
            dyn_people = build_dynamic_questions(conn, state.candidates, state.asked, top_k=60)
            dyn_years = build_dynamic_year_questions(state.candidates, state.asked)
            
            # NOUVEAU: Questions de VALIDATION du TOP candidat (priorité élevée)
            validation_questions = build_top_validation_questions(conn, state.candidates, state.asked)
            
            # STRATÉGIE: Mettre les questions de validation EN PREMIER pour boost naturel
            merged_questions = validation_questions + dyn_kw + dyn_people + dyn_years + questions

            # AMÉLIORATION: Ajouter de l'aléatoire sur la première question
            is_first = (state.question_count == 0)
            q = choose_best_question(state.candidates, merged_questions, state.asked, is_first_question=is_first, state=state)
            
            # STRICT MODE: Si plus de questions disponibles ET plusieurs candidats
            if q is None:
                if len(state.candidates) == 1:
                    # Un seul candidat: guess automatique
                    print("\n✅ UN SEUL CANDIDAT RESTANT!")
                    print("J'AI TROUVÉ :", short_movie_str(state.candidates[0]))
                    print(f"Questions: {state.question_count}")
                    return 0
                else:
                    # Plusieurs candidats mais plus de questions
                    print(f"\n⚠️ Plus de questions automatiques disponibles.")
                    print(f"Il reste {len(state.candidates)} candidats. Voici le top 5:")
                    print_top(state, limit=min(5, len(state.candidates)))
                    print()
                    
                    # Forcer l'utilisateur à éliminer manuellement
                    choice = input("Tape le numéro du film correct (1-5) ou 'e' pour éliminer le #1 et continuer : ").strip().lower()
                    
                    if choice in ['1', '2', '3', '4', '5']:
                        idx = int(choice) - 1
                        if idx < len(state.candidates):
                            print("\n✅ J'AI TROUVÉ :", short_movie_str(state.candidates[idx]))
                            print(f"Questions: {state.question_count}")
                            return 0
                    elif choice == 'e':
                        # Éliminer le #1 et continuer
                        top = state.candidates[0]
                        mid = movie_id(top)
                        if mid is not None:
                            eliminate_movie(state, mid)
                        sort_candidates(state)
                        print(f"OK, {short_movie_str(top)} éliminé. Il reste {len(state.candidates)} candidats.\n")
                        continue
                    else:
                        print("Choix invalide, je continue.\n")
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
            
            # NOUVEAU: Tracker le type de question pour diversité
            q_type = get_question_type(q)
            state.recent_question_types.append(q_type)
            # Garder seulement les 10 dernières pour économiser mémoire
            if len(state.recent_question_types) > 10:
                state.recent_question_types = state.recent_question_types[-10:]
            
            # NOUVEAU: Si on répond "oui" à une question de langue, exclure TOUTES les autres
            if ans == "y" and q.key.startswith("language_"):
                all_languages = {"language_en", "language_fr", "language_ja", "language_es", 
                               "language_de", "language_it", "language_ko", "language_zh"}
                # Ajouter toutes les autres langues à "asked" pour les exclure
                for lang in all_languages:
                    if lang != q.key:  # Sauf celle qu'on vient de confirmer
                        state.asked.add(lang)
                print(f"   [Langue confirmée: {q.key.replace('language_', '')} - Autres langues exclues]")
            
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

                if state.top_streak_len >= 9 and state.guess_cooldown == 0:
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
                        state.consecutive_guesses += 1
                        print("OK, je continue.\n")
                        continue
            print()

    finally:
        close_connection()

if __name__ == "__main__":
    raise SystemExit(main())

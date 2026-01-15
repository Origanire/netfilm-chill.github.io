#!/usr/bin/env python3
import json
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional

DB_PATH = Path("movies.db")


def connect_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError("Base de données movies.db introuvable")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (name,),
    )
    return cur.fetchone() is not None


def get_movie_candidates(conn: sqlite3.Connection, title: str, limit: int = 10) -> List[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, release_date, popularity
        FROM movies
        WHERE title LIKE ?
        ORDER BY popularity DESC
        LIMIT ?
        """,
        (f"%{title}%", limit),
    )
    return cur.fetchall()


def pretty_print_kv(title: str, kv: List[tuple]) -> None:
    print(f"\n=== {title} ===")
    if not kv:
        print("(vide)")
        return

    key_width = max(len(k) for k, _ in kv)
    for k, v in kv:
        if v is None:
            v_str = "NULL"
        elif isinstance(v, (dict, list)):
            v_str = json.dumps(v, ensure_ascii=False, indent=2)
        else:
            v_str = str(v)
        print(f"{k:<{key_width}} : {v_str}")


def fetch_all_movie_columns(conn: sqlite3.Connection, movie_id: int) -> List[tuple]:
    """
    Récupère TOUTES les colonnes de la table movies (sans supposer le schéma).
    """
    cur = conn.cursor()

    # Colonnes dynamiques
    cur.execute("PRAGMA table_info(movies)")
    cols = [r["name"] for r in cur.fetchall()]
    if not cols:
        return []

    cur.execute(f"SELECT {', '.join(cols)} FROM movies WHERE id = ?", (movie_id,))
    row = cur.fetchone()
    if row is None:
        return []

    kv = []
    for c in cols:
        kv.append((c, row[c]))
    return kv


def fetch_genres(conn: sqlite3.Connection, movie_id: int) -> Optional[List[str]]:
    if not (table_exists(conn, "movie_genres") and table_exists(conn, "genres")):
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT g.name
        FROM movie_genres mg
        JOIN genres g ON g.id = mg.genre_id
        WHERE mg.movie_id = ?
        ORDER BY g.name
        """,
        (movie_id,),
    )
    return [r["name"] for r in cur.fetchall()]


def fetch_keywords(conn: sqlite3.Connection, movie_id: int) -> Optional[List[str]]:
    if not (table_exists(conn, "movie_keywords") and table_exists(conn, "keywords")):
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT k.name
        FROM movie_keywords mk
        JOIN keywords k ON k.id = mk.keyword_id
        WHERE mk.movie_id = ?
        ORDER BY k.name
        """,
        (movie_id,),
    )
    return [r["name"] for r in cur.fetchall()]


def fetch_cast(conn: sqlite3.Connection, movie_id: int, limit: int = 30) -> Optional[List[dict]]:
    if not (table_exists(conn, "movie_cast") and table_exists(conn, "people")):
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.name, mc.character, mc.cast_order
        FROM movie_cast mc
        JOIN people p ON p.id = mc.person_id
        WHERE mc.movie_id = ?
        ORDER BY mc.cast_order
        LIMIT ?
        """,
        (movie_id, limit),
    )
    return [{"name": r["name"], "character": r["character"], "order": r["cast_order"]} for r in cur.fetchall()]


def fetch_crew(conn: sqlite3.Connection, movie_id: int, limit: int = 50) -> Optional[List[dict]]:
    if not (table_exists(conn, "movie_crew") and table_exists(conn, "people")):
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.name, cr.job, cr.department
        FROM movie_crew cr
        JOIN people p ON p.id = cr.person_id
        WHERE cr.movie_id = ?
        LIMIT ?
        """,
        (movie_id, limit),
    )
    return [{"name": r["name"], "job": r["job"], "department": r["department"]} for r in cur.fetchall()]


def parse_countries_from_movies_row(kv: List[tuple]) -> Optional[List[str]]:
    # tente de détecter une colonne "countries" stockée en JSON
    for k, v in kv:
        if k.lower() in ("countries", "production_countries") and v:
            if isinstance(v, str):
                try:
                    data = json.loads(v)
                    if isinstance(data, list):
                        # liste d'ISO ou liste d'objets
                        out = []
                        for x in data:
                            if isinstance(x, str):
                                out.append(x)
                            elif isinstance(x, dict):
                                out.append(x.get("iso_3166_1") or x.get("name") or str(x))
                            else:
                                out.append(str(x))
                        return out
                except Exception:
                    return [v]
            return [str(v)]
    return None


def print_full_movie_profile(conn: sqlite3.Connection, movie_id: int) -> None:
    base_kv = fetch_all_movie_columns(conn, movie_id)
    if not base_kv:
        print("Film introuvable (id invalide ?).")
        return

    pretty_print_kv("MOVIES (toutes les colonnes)", base_kv)

    countries = parse_countries_from_movies_row(base_kv)
    if countries is not None:
        pretty_print_kv("COUNTRIES (déduit)", [("countries", countries)])

    genres = fetch_genres(conn, movie_id)
    if genres is not None:
        pretty_print_kv("GENRES", [("genres", genres)])

    keywords = fetch_keywords(conn, movie_id)
    if keywords is not None:
        pretty_print_kv("KEYWORDS", [("keywords", keywords)])

    cast = fetch_cast(conn, movie_id)
    if cast is not None:
        pretty_print_kv("CAST (top)", [("cast", cast)])

    crew = fetch_crew(conn, movie_id)
    if crew is not None:
        # petit tri lisible: Directors en haut si présent
        crew_sorted = sorted(
            crew,
            key=lambda x: (0 if (x.get("job") or "").lower() == "director" else 1, (x.get("department") or ""), (x.get("job") or ""), (x.get("name") or "")),
        )
        pretty_print_kv("CREW (top)", [("crew", crew_sorted)])


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python search_movie.py \"titre\"")
        print("  python search_movie.py --id <movie_id>")
        return 1

    conn = connect_db()
    try:
        if sys.argv[1] == "--id":
            if len(sys.argv) < 3:
                print("Usage: python search_movie.py --id <movie_id>")
                return 1
            movie_id = int(sys.argv[2])
            print_full_movie_profile(conn, movie_id)
            return 0

        title = " ".join(sys.argv[1:])
        results = get_movie_candidates(conn, title)

        if not results:
            print("Aucun film trouvé.")
            return 0

        print(f"{len(results)} film(s) trouvé(s):\n")
        for row in results:
            print(f"- id={row['id']} | {row['title']} ({row['release_date'] or 'N/A'}) | popularité: {row['popularity']}")

        if len(results) == 1:
            print_full_movie_profile(conn, int(results[0]["id"]))
            return 0

        # Si plusieurs films, on force le choix (sans interaction compliquée)
        print("\nChoisis un id à afficher:")
        chosen = input("> id = ").strip()
        if not chosen:
            return 0
        movie_id = int(chosen)
        print_full_movie_profile(conn, movie_id)
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

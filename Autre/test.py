#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Akinator-like CLI pour films (utilise l'API TMDB via `Guesser.py`).

Algorithme:
- Précharge un pool restreint de films (par défaut 200) depuis /discover (popularité).
- Récupère `details`, `credits` et `keywords` pour chaque film (cache mémoire).
- Génère des attributs (genres, décennies, acteurs fréquents, réalisateurs fréquents, keywords fréquents, langue).
- À chaque tour, choisit la question qui maximise le gain d'information (entropie) pour scinder l'ensemble candidat.
- Continue jusqu'à avoir 1-3 candidats puis propose une ou plusieurs réponses.

Usage:
  set TMDB_TOKEN=...   (Windows)
  python backend/test.py

Note: diminuer `POOL_SIZE` si vous atteignez les limites d'API.
"""

from __future__ import annotations

import math
import os
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from Guesser import (
    make_session,
    discover_movies,
    movie_details,
    movie_credits,
    movie_keywords,
    genre_list,
    TMDBError,
)


POOL_SIZE = 200
MIN_FREQ_ACTOR = 3
MIN_FREQ_DIRECTOR = 2
MIN_FREQ_KEYWORD = 3
MAX_QUESTIONS = 20


def safe_input(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def fetch_pool(session, language: str = "fr-FR", pool_size: int = POOL_SIZE) -> List[Dict[str, Any]]:
    per_page = 20
    pages = max(1, math.ceil(pool_size / per_page))
    movies: List[Dict[str, Any]] = []
    seen: Set[int] = set()

    for page in range(1, pages + 1):
        try:
            payload = discover_movies(session, page=page, language=language, include_adult=False, sort_by="popularity.desc")
        except TMDBError as e:
            log(f"Erreur discover page {page}: {e}")
            break

        results = payload.get("results") or []
        for r in results:
            mid = r.get("id")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            movies.append(r)
            if len(movies) >= pool_size:
                break
        if len(movies) >= pool_size:
            break
        time.sleep(0.08)

    return movies


def enrich_movies(session, raw_movies: List[Dict[str, Any]], language: str = "fr-FR") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(raw_movies):
        mid = int(item.get("id"))
        try:
            details = movie_details(session, mid, language=language)
            kwp = movie_keywords(session, mid)
            crp = movie_credits(session, mid)
        except TMDBError as e:
            log(f"Skipped {mid}: {e}")
            continue

        genres = [g.get("id") for g in (details.get("genres") or []) if g.get("id")]
        year = None
        rd = details.get("release_date")
        if rd and len(rd) >= 4 and rd[:4].isdigit():
            year = int(rd[:4])

        keywords = [k.get("name") for k in (kwp.get("keywords") or []) if k.get("name")]

        cast = crp.get("cast") or []
        cast.sort(key=lambda x: int(x.get("order", 9999)))
        top_cast = [c.get("name") for c in cast[:8] if c.get("name")]

        crew = crp.get("crew") or []
        directors = [c.get("name") for c in crew if c.get("job") == "Director" and c.get("name")]

        movie = {
            "id": mid,
            "title": details.get("title") or item.get("title"),
            "year": year,
            "genres": genres,
            "language": details.get("original_language"),
            "keywords": keywords,
            "cast": top_cast,
            "directors": directors,
            "adult": bool(details.get("adult", False)),
            "popularity": details.get("popularity", item.get("popularity")),
        }
        out.append(movie)
        # small throttle
        time.sleep(0.06)

    return out


def decade_label(year: Optional[int]) -> Optional[str]:
    if not year:
        return None
    d = (year // 10) * 10
    return f"{d}s"


def build_attributes(movies: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Collect frequencies
    actor_counter = Counter()
    director_counter = Counter()
    keyword_counter = Counter()
    genre_counter = Counter()
    lang_counter = Counter()
    decade_counter = Counter()

    for m in movies:
        for a in m.get("cast", []):
            actor_counter[a] += 1
        for d in m.get("directors", []):
            director_counter[d] += 1
        for k in m.get("keywords", []):
            keyword_counter[k] += 1
        for gid in m.get("genres", []):
            genre_counter[gid] += 1
        if m.get("language"):
            lang_counter[m["language"]] += 1
        dec = decade_label(m.get("year"))
        if dec:
            decade_counter[dec] += 1

    attrs = {
        "genres": sorted([(gid, c) for gid, c in genre_counter.items() if c >= 1], key=lambda x: -x[1]),
        "actors": sorted([(a, c) for a, c in actor_counter.items() if c >= MIN_FREQ_ACTOR], key=lambda x: -x[1]),
        "directors": sorted([(d, c) for d, c in director_counter.items() if c >= MIN_FREQ_DIRECTOR], key=lambda x: -x[1]),
        "keywords": sorted([(k, c) for k, c in keyword_counter.items() if c >= MIN_FREQ_KEYWORD], key=lambda x: -x[1]),
        "languages": sorted([(l, c) for l, c in lang_counter.items() if c >= 1], key=lambda x: -x[1]),
        "decades": sorted([(dec, c) for dec, c in decade_counter.items() if c >= 1], key=lambda x: -x[1]),
    }

    return attrs


def entropy_uniform(n: int) -> float:
    if n <= 1:
        return 0.0
    return math.log2(n)


def information_gain(N: int, n_yes: int) -> float:
    if N <= 1:
        return 0.0
    n_no = N - n_yes
    if n_yes == 0 or n_no == 0:
        return 0.0
    before = entropy_uniform(N)
    after = (n_yes / N) * entropy_uniform(n_yes) + (n_no / N) * entropy_uniform(n_no)
    return before - after


def pick_best_question(candidates: List[Dict[str, Any]], attrs: Dict[str, Any], asked: Set[Tuple[str, Any]]) -> Optional[Tuple[str, Any, float]]:
    N = len(candidates)
    if N <= 1:
        return None

    best = None
    best_score = 0.0

    # Genres (by id)
    for gid, _ in attrs["genres"]:
        key = ("genre", gid)
        if key in asked:
            continue
        n_yes = sum(1 for m in candidates if gid in (m.get("genres") or []))
        score = information_gain(N, n_yes)
        if score > best_score:
            best_score = score
            best = ("genre", gid, score)

    # Actors
    for a, _ in attrs["actors"]:
        key = ("actor", a)
        if key in asked:
            continue
        n_yes = sum(1 for m in candidates if a in (m.get("cast") or []))
        score = information_gain(N, n_yes)
        if score > best_score:
            best_score = score
            best = ("actor", a, score)

    # Directors
    for d, _ in attrs["directors"]:
        key = ("director", d)
        if key in asked:
            continue
        n_yes = sum(1 for m in candidates if d in (m.get("directors") or []))
        score = information_gain(N, n_yes)
        if score > best_score:
            best_score = score
            best = ("director", d, score)

    # Keywords
    for k, _ in attrs["keywords"]:
        key = ("keyword", k)
        if key in asked:
            continue
        n_yes = sum(1 for m in candidates if k in (m.get("keywords") or []))
        score = information_gain(N, n_yes)
        if score > best_score:
            best_score = score
            best = ("keyword", k, score)

    # Decades
    for dec, _ in attrs["decades"]:
        key = ("decade", dec)
        if key in asked:
            continue
        n_yes = sum(1 for m in candidates if decade_label(m.get("year")) == dec)
        score = information_gain(N, n_yes)
        if score > best_score:
            best_score = score
            best = ("decade", dec, score)

    # Languages
    for l, _ in attrs["languages"]:
        key = ("language", l)
        if key in asked:
            continue
        n_yes = sum(1 for m in candidates if m.get("language") == l)
        score = information_gain(N, n_yes)
        if score > best_score:
            best_score = score
            best = ("language", l, score)

    return best


def ask_text(qtype: str, value: Any, genres_map: Dict[int, str]) -> str:
    if qtype == "genre":
        # value may be an int id or a readable label (e.g. 'Action')
        try:
            name = genres_map.get(int(value), str(value))
        except Exception:
            name = str(value)
        return f"Est-ce que le film est du genre '{name}' ? (o/n) "
    if qtype == "year":
        try:
            y = int(value)
            return f"Le film a-t-il été principalement réalisé après {y - 1} ? (o/n) "
        except Exception:
            return f"Le film a-t-il été principalement réalisé après {value} ? (o/n) "
    if qtype == "popularity":
        # pivot value is a float
        try:
            p = float(value)
            return f"Le film fait-il partie des films plus populaires (pop >= {p:.2f}) ? (o/n) "
        except Exception:
            return f"Le film fait-il partie des films plus populaires (pop >= {value}) ? (o/n) "
    if qtype == "runtime":
        try:
            r = int(float(value))
            return f"Le film dure-t-il au moins {r} minutes ? (o/n) "
        except Exception:
            return f"Le film dure-t-il au moins {value} minutes ? (o/n) "
    if qtype == "collection":
        return f"Le film appartient-il à la franchise/collection '{value}' ? (o/n) "
    if qtype == "actor":
        return f"Est-ce que l'acteur {value} joue dans le film ? (o/n) "
    if qtype == "director":
        return f"Est-ce que le réalisateur {value} a réalisé le film ? (o/n) "
    if qtype == "keyword":
        return f"Le film contient-il le thème/mot-clé '{value}' ? (o/n) "
    if qtype == "decade":
        return f"Le film a-t-il été principalement diffusé dans les années {value} ? (o/n) "
    if qtype == "language":
        return f"Le film est-il principalement en langue '{value}' ? (o/n) "
    return f"Question inconnue ({qtype}) ? (o/n) "


def filter_candidates(candidates: List[Dict[str, Any]], qtype: str, value: Any, answer_yes: bool) -> List[Dict[str, Any]]:
    if qtype == "genre":
        return [m for m in candidates if (value in (m.get("genres") or [])) == answer_yes]
    if qtype == "actor":
        return [m for m in candidates if (value in (m.get("cast") or [])) == answer_yes]
    if qtype == "director":
        return [m for m in candidates if (value in (m.get("directors") or [])) == answer_yes]
    if qtype == "keyword":
        return [m for m in candidates if (value in (m.get("keywords") or [])) == answer_yes]
    if qtype == "decade":
        return [m for m in candidates if (decade_label(m.get("year")) == value) == answer_yes]
    if qtype == "language":
        return [m for m in candidates if (m.get("language") == value) == answer_yes]
    return candidates


def guess_stage(candidates: List[Dict[str, Any]]) -> None:
    if not candidates:
        print("Je n'ai plus de candidats plausibles.")
        return

    # propose les 3 films les plus populaires restants
    candidates = sorted(candidates, key=lambda m: float(m.get("popularity") or 0.0), reverse=True)
    top = candidates[:3]
    for i, m in enumerate(top, start=1):
        ans = safe_input(f"Est-ce que le film est '{m.get('title')}' ({m.get('year')}) ? (o/n) ")
        if ans.startswith("o"):
            print("Génial ! J'ai deviné.")
            return
    print("Dommage — je n'ai pas trouvé. Fin du jeu.")


def main() -> None:
    # Si une base SQLite existe, utiliser le moteur DB rapide
    db_path = os.environ.get("MOVIES_DB", "movies.db")
    if os.path.exists(db_path):
        try:
            from akinator_db import AkinatorDBGame
        except Exception as e:
            print(f"Impossible d'importer akinator_db: {e}")
            sys.exit(1)

        game = AkinatorDBGame(db_path=db_path)
        try:
            filters: List[Tuple[str, Any, bool]] = []
            qcount = 0
            min_guess = 3
            max_guess = 10
            while qcount < MAX_QUESTIONS:
                N = game.candidate_count(filters)
                # Ne jamais proposer si trop de candidats
                if N <= min_guess:
                    break
                best = game.pick_best_question(filters)
                if not best:
                    if N > max_guess:
                        print(f"Impossible de deviner : trop de candidats ({N}) et aucune question discriminante possible.")
                        return
                    else:
                        break
                qtype, value, score = best

                # Traduire value -> texte lisible si nécessaire
                if qtype == "genre":
                    row = game.cur.execute("SELECT name FROM genres WHERE id = ?", (int(value),)).fetchone()
                    label = row["name"] if row else str(value)
                elif qtype == "keyword":
                    row = game.cur.execute("SELECT name FROM keywords WHERE id = ?", (int(value),)).fetchone()
                    label = row["name"] if row else str(value)
                elif qtype in ("actor", "director"):
                    row = game.cur.execute("SELECT name FROM people WHERE id = ?", (int(value),)).fetchone()
                    label = row["name"] if row else str(value)
                elif qtype == "collection":
                    try:
                        row = game.cur.execute("SELECT collection_name FROM movies WHERE collection_id = ? AND collection_name IS NOT NULL LIMIT 1", (int(value),)).fetchone()
                        label = row["collection_name"] if row else str(value)
                    except Exception:
                        label = str(value)
                else:
                    label = str(value)

                qtext = ask_text(qtype, label, {})
                ans = safe_input(qtext)
                yes = ans.startswith("o")
                game.apply_answer(filters, qtype, value, yes)
                qcount += 1
                remaining = game.candidate_count(filters)
                print(f"Reste {remaining} candidats.")

            # proposer seulement si le nombre de candidats est raisonnable
            top = game.get_top_candidates(filters, limit=5)
            if len(top) == 0:
                print("Aucun film ne correspond à vos réponses.")
            elif len(top) > max_guess:
                print(f"Trop de candidats ({len(top)}) pour deviner. Essayez de répondre plus précisément ou relancez une partie.")
            else:
                for tid, title, year in top:
                    ans = safe_input(f"Est-ce que le film est '{title}' ({year}) ? (o/n) ")
                    if ans.startswith("o"):
                        print("Génial ! J'ai deviné.")
                        break
                else:
                    print("Je n'ai pas deviné. Vous pouvez lancer une nouvelle partie.")

        finally:
            game.close()
        return

    # Fallback: si pas de DB, utiliser le mode TMDB pool (nécessite TMDB_TOKEN)
    token = os.environ.get("TMDB_TOKEN", "").strip()
    if not token:
        print("Aucune base 'movies.db' trouvée et TMDB_TOKEN non fourni. Construisez la DB avec Guesser.py ou fournissez TMDB_TOKEN.")
        sys.exit(1)

    session = make_session(token)

    try:
        # quick validation
        try:
            _ = genre_list(session, "fr-FR")
        except Exception as e:
            log(f"Impossible de valider le token: {e}")
            sys.exit(1)

        print("Chargement du pool de films depuis TMDB (fallback)...")
        raw = fetch_pool(session, language="fr-FR", pool_size=POOL_SIZE)
        movies = enrich_movies(session, raw, language="fr-FR")

        # map genres
        gpayload = genre_list(session, "fr-FR")
        genres_map = {int(g["id"]): g["name"] for g in (gpayload.get("genres") or [])}

        candidates = movies
        asked: Set[Tuple[str, Any]] = set()
        attrs = build_attributes(candidates)

        qcount = 0
        while qcount < MAX_QUESTIONS and len(candidates) > 3:
            attrs = build_attributes(candidates)
            best = pick_best_question(candidates, attrs, asked)
            if not best:
                break
            qtype, value, score = best
            asked.add((qtype, value))
            qtext = ask_text(qtype, value, genres_map)
            ans = safe_input(qtext)
            if not ans:
                print("Réponse non reconnue — utilisez 'o' pour oui et 'n' pour non.")
                continue
            if ans[0] == 'o':
                candidates = filter_candidates(candidates, qtype, value, True)
            else:
                candidates = filter_candidates(candidates, qtype, value, False)
            qcount += 1
            print(f"Reste {len(candidates)} candidats.")

        # phase de proposition
        guess_stage(candidates)

    except TMDBError as e:
        log(f"Erreur TMDB: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

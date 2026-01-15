#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Moteur Akinator-like basé sur la base SQLite construite par `Guesser.py`.

Principe:
- Ne charge pas tous les films en mémoire.
- Requêtes SQL agrégées calculent les counts (n_yes) pour chaque attribut
  au sein de l'ensemble candidat courant (filtré par les réponses).
- L'ensemble candidat est représenté par des clauses WHERE dynamiques
  (EXISTS / NOT EXISTS) — évite la matérialisation de grands tableaux.

Usage:
  from akinator_db import AkinatorDBGame
  g = AkinatorDBGame('movies.db')
  g.pick_best_question(filters) -> (qtype, value, score)
  g.apply_answer(filters, qtype, value, yes)
  g.get_top_candidates(limit)
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple


class AkinatorDBGame:
    def __init__(self, db_path: str = "movies.db"):
        self.db_path = db_path
        self.con = sqlite3.connect(self.db_path)
        self.con.row_factory = sqlite3.Row
        self.cur = self.con.cursor()

    def close(self) -> None:
        self.con.close()

    def _build_filters_clause(self, filters: Sequence[Tuple[str, Any, bool]]) -> Tuple[str, List[Any]]:
        # filters: list of (qtype, value, positive)
        clauses: List[str] = []
        params: List[Any] = []

        for qtype, value, positive in filters:
            if qtype == "genre":
                sub = f"EXISTS(SELECT 1 FROM movie_genres mg WHERE mg.movie_id = m.id AND mg.genre_id = ?)"
                if positive:
                    clauses.append(sub)
                    params.append(int(value))
                else:
                    clauses.append(f"NOT {sub}")
                    params.append(int(value))

            elif qtype == "keyword":
                sub = f"EXISTS(SELECT 1 FROM movie_keywords mk WHERE mk.movie_id = m.id AND mk.keyword_id = ?)"
                if positive:
                    clauses.append(sub)
                    params.append(int(value))
                else:
                    clauses.append(f"NOT {sub}")
                    params.append(int(value))

            elif qtype == "actor":
                # value is person name or id; try id first
                if isinstance(value, int):
                    pid = value
                else:
                    row = self.cur.execute("SELECT id FROM people WHERE name = ? COLLATE NOCASE LIMIT 1", (value,)).fetchone()
                    pid = row["id"] if row else None
                if pid is None:
                    # no match -> this filter is inert (will discard nothing if positive)
                    if positive:
                        clauses.append("0")
                    else:
                        clauses.append("1")
                else:
                    sub = f"EXISTS(SELECT 1 FROM movie_cast mc WHERE mc.movie_id = m.id AND mc.person_id = ?)"
                    if positive:
                        clauses.append(sub)
                        params.append(pid)
                    else:
                        clauses.append(f"NOT {sub}")
                        params.append(pid)

            elif qtype == "director":
                if isinstance(value, int):
                    pid = value
                else:
                    row = self.cur.execute("SELECT id FROM people WHERE name = ? COLLATE NOCASE LIMIT 1", (value,)).fetchone()
                    pid = row["id"] if row else None
                if pid is None:
                    if positive:
                        clauses.append("0")
                    else:
                        clauses.append("1")
                else:
                    sub = f"EXISTS(SELECT 1 FROM movie_crew mc WHERE mc.movie_id = m.id AND mc.person_id = ? AND mc.job = 'Director')"
                    if positive:
                        clauses.append(sub)
                        params.append(pid)
                    else:
                        clauses.append(f"NOT {sub}")
                        params.append(pid)

            elif qtype == "decade":
                # value like '1990s' -> parse
                dec = int(str(value)[:4]) if isinstance(value, str) and value.endswith('s') else None
                if dec:
                    start = dec
                    end = dec + 9
                    cond = "(m.year BETWEEN ? AND ?)"
                    if positive:
                        clauses.append(cond)
                        params.extend([start, end])
                    else:
                        clauses.append(f"NOT {cond}")
                        params.extend([start, end])

            elif qtype == "language":
                cond = "m.original_language = ?"
                if positive:
                    clauses.append(cond)
                    params.append(value)
                else:
                    clauses.append(f"NOT {cond}")
                    params.append(value)
            elif qtype in ("year", "popularity", "runtime"):
                # numeric filters: positive means >= value, negative means < value
                try:
                    v = float(value)
                except Exception:
                    # invalid numeric value, skip
                    continue
                if qtype == "year":
                    # year stored as integer
                    if positive:
                        clauses.append("m.year >= ?")
                        params.append(int(v))
                    else:
                        clauses.append("m.year < ?")
                        params.append(int(v))
                else:
                    if positive:
                        clauses.append(f"m.{qtype} >= ?")
                        params.append(v)
                    else:
                        clauses.append(f"m.{qtype} < ?")
                        params.append(v)
            elif qtype == "collection":
                # value may be collection_id or name
                if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
                    cid = int(value)
                    if positive:
                        clauses.append("m.collection_id = ?")
                        params.append(cid)
                    else:
                        clauses.append("NOT (m.collection_id = ?)")
                        params.append(cid)
                else:
                    # match by collection_name
                    if positive:
                        clauses.append("m.collection_name = ?")
                        params.append(value)
                    else:
                        clauses.append("NOT (m.collection_name = ?)")
                        params.append(value)

        where = " AND ".join(f"({c})" for c in clauses) if clauses else "1"
        return where, params

    def candidate_count(self, filters: Sequence[Tuple[str, Any, bool]]) -> int:
        where, params = self._build_filters_clause(filters)
        q = f"SELECT COUNT(*) as c FROM movies m WHERE {where}"
        row = self.cur.execute(q, params).fetchone()
        return int(row["c"])

    def top_attribute_counts(self, filters: Sequence[Tuple[str, Any, bool]], attr: str, limit: int = 100) -> List[Tuple[Any, int]]:
        where, params = self._build_filters_clause(filters)
        if attr == "genres":
            q = f"SELECT mg.genre_id as val, COUNT(*) as c FROM movie_genres mg JOIN movies m ON mg.movie_id = m.id WHERE {where} GROUP BY mg.genre_id ORDER BY c DESC LIMIT ?"
            rows = self.cur.execute(q, params + [limit]).fetchall()
            return [(r["val"], int(r["c"])) for r in rows]

        if attr == "keywords":
            q = f"SELECT mk.keyword_id as val, COUNT(*) as c FROM movie_keywords mk JOIN movies m ON mk.movie_id = m.id WHERE {where} GROUP BY mk.keyword_id ORDER BY c DESC LIMIT ?"
            rows = self.cur.execute(q, params + [limit]).fetchall()
            return [(r["val"], int(r["c"])) for r in rows]

        if attr == "actors":
            q = f"SELECT mc.person_id as val, COUNT(*) as c FROM movie_cast mc JOIN movies m ON mc.movie_id = m.id WHERE {where} GROUP BY mc.person_id ORDER BY c DESC LIMIT ?"
            rows = self.cur.execute(q, params + [limit]).fetchall()
            return [(r["val"], int(r["c"])) for r in rows]

        if attr == "directors":
            q = f"SELECT mc.person_id as val, COUNT(*) as c FROM movie_crew mc JOIN movies m ON mc.movie_id = m.id WHERE mc.job = 'Director' AND {where} GROUP BY mc.person_id ORDER BY c DESC LIMIT ?"
            rows = self.cur.execute(q, params + [limit]).fetchall()
            return [(r["val"], int(r["c"])) for r in rows]

        if attr == "languages":
            q = f"SELECT m.original_language as val, COUNT(*) as c FROM movies m WHERE {where} GROUP BY m.original_language ORDER BY c DESC LIMIT ?"
            rows = self.cur.execute(q, params + [limit]).fetchall()
            return [(r["val"], int(r["c"])) for r in rows]

        if attr == "decades":
            # group by decade
            q = f"SELECT ((m.year / 10) * 10) as dec, COUNT(*) as c FROM movies m WHERE {where} AND m.year IS NOT NULL GROUP BY dec ORDER BY c DESC LIMIT ?"
            rows = self.cur.execute(q, params + [limit]).fetchall()
            return [(f"{int(r['dec'])}s", int(r["c"])) for r in rows if r["dec"] is not None]

        if attr == "collections":
            q = f"SELECT m.collection_id as val, COUNT(*) as c FROM movies m WHERE {where} AND m.collection_id IS NOT NULL GROUP BY m.collection_id ORDER BY c DESC LIMIT ?"
            rows = self.cur.execute(q, params + [limit]).fetchall()
            return [(r["val"], int(r["c"])) for r in rows]

        return []

    @staticmethod
    def _entropy(n: int) -> float:
        return 0.0 if n <= 1 else math.log2(n)

    def _information_gain(self, N: int, n_yes: int) -> float:
        if N <= 1:
            return 0.0
        n_no = N - n_yes
        if n_yes == 0 or n_no == 0:
            return 0.0
        before = self._entropy(N)
        after = (n_yes / N) * self._entropy(n_yes) + (n_no / N) * self._entropy(n_no)
        return before - after

    def pick_best_question(self, filters: Sequence[Tuple[str, Any, bool]]) -> Optional[Tuple[str, Any, float]]:
        N = self.candidate_count(filters)
        if N <= 1:
            return None

        best = None
        best_score = 0.0
        # precompute WHERE clause and params for numeric queries
        where, params = self._build_filters_clause(filters)
        # build asked set to avoid repeating the same question
        asked = set((qtype, value) for (qtype, value, positive) in filters)
        # also track numeric attributes already asked to avoid similar questions
        asked_numeric = set(qtype for (qtype, value, positive) in filters if qtype in ("year", "popularity", "runtime"))

        # Evaluate genres, keywords, actors, directors, languages, decades
        attr_limits = {
            "genres": 50,
            "keywords": 80,
            "actors": 80,
            "directors": 50,
            "languages": 20,
            "decades": 20,
            "collections": 30,
        }

        for attr, limit in attr_limits.items():
            rows = self.top_attribute_counts(filters, attr, limit=limit)
            for val, cnt in rows:
                key = (attr[:-1] if attr.endswith('s') else attr, val)
                if key in asked:
                    continue
                ratio = cnt / N if N else 0.0
                # skip extremely unbalanced splits
                if ratio < 0.02 or ratio > 0.98:
                    continue
                ig = self._information_gain(N, cnt)
                # prefer splits close to 50/50
                balance = 1.0 - abs(0.5 - ratio) * 2.0
                score = ig * balance
                if score > best_score:
                    best_score = score
                    best = (attr[:-1] if attr.endswith('s') else attr, val, score)

        # Multi-choice for decades: ask for one of the top decades
        if "decade" not in asked_numeric:
            rows = self.top_attribute_counts(filters, "decades", limit=5)
            for val, cnt in rows:
                key = ("decade", val)
                if key in asked:
                    continue
                ratio = cnt / N if N else 0.0
                if ratio < 0.05 or ratio > 0.95:
                    continue
                ig = self._information_gain(N, cnt)
                balance = 1.0 - abs(0.5 - ratio) * 2.0
                score = ig * balance
                if score > best_score:
                    best_score = score
                    best = ("decade", val, score)

        # Numeric splits: year, popularity, runtime -> use median as pivot
        for col in ("year", "popularity", "runtime"):
            if col in asked_numeric:
                continue
            qcnt = f"SELECT COUNT(*) as c FROM movies m WHERE {where} AND m.{col} IS NOT NULL"
            rowcnt = self.cur.execute(qcnt, params).fetchone()
            total = int(rowcnt["c"]) if rowcnt else 0
            if total <= 1:
                continue
            offset = total // 2
            qmed = f"SELECT m.{col} as v FROM movies m WHERE {where} AND m.{col} IS NOT NULL ORDER BY m.{col} LIMIT 1 OFFSET ?"
            rowm = self.cur.execute(qmed, params + [offset]).fetchone()
            if not rowm:
                continue
            pivot = rowm["v"]
            key = (col, pivot)
            if key in asked:
                continue
            # avoid similar pivots: check if a similar pivot was asked
            similar_asked = False
            # ...existing code...
            # count >= pivot
            qyes = f"SELECT COUNT(*) as c FROM movies m WHERE {where} AND m.{col} IS NOT NULL AND m.{col} >= ?"
            rowy = self.cur.execute(qyes, params + [pivot]).fetchone()
            n_yes = int(rowy["c"]) if rowy else 0
            ratio = n_yes / N if N else 0.0
            if ratio < 0.02 or ratio > 0.98:
                continue
            ig = self._information_gain(N, n_yes)
            balance = 1.0 - abs(0.5 - ratio) * 2.0
            score = ig * balance
            if score > best_score:
                best_score = score
                best = (col, pivot, score)

    def apply_answer(self, filters: List[Tuple[str, Any, bool]], qtype: str, value: Any, yes: bool) -> None:
        filters.append((qtype, value, yes))

    def get_top_candidates(self, filters: Sequence[Tuple[str, Any, bool]], limit: int = 5) -> List[Tuple[int, str, Optional[int]]]:
        where, params = self._build_filters_clause(filters)
        q = f"SELECT m.id as id, m.title as title, m.year as year FROM movies m WHERE {where} ORDER BY m.popularity DESC LIMIT ?"
        rows = self.cur.execute(q, params + [limit]).fetchall()
        return [(int(r["id"]), r["title"], r["year"]) for r in rows]

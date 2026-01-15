#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import traceback
from pathlib import Path
from typing import Dict, Any

from flask import Flask, request, jsonify
from flask_cors import CORS

from engines.engine_akinator import (
    load_genres,
    discover_movies,
    default_questions,
    init_state,
    sort_candidates,
    choose_best_question,
    update_state_with_answer,
)

app = Flask(__name__)
origin = os.getenv("ALLOWED_ORIGIN", "https://origanire.github.io")
CORS(app, resources={r"/*": {"origins": [origin]}})

OPTIONS_UI = ["Oui", "Non", "Je ne sais pas", "Probablement", "Probablement pas"]

UI_TO_ENGINE = {
    "Oui": "y",
    "Non": "n",
    "Je ne sais pas": "?",
    "Probablement": "py",
    "Probablement pas": "pn",
    "y": "y",
    "n": "n",
    "?": "?",
    "py": "py",
    "pn": "pn",
}

# Session: on ne stocke PAS les questions (car elles capturent conn)
game_state: Dict[str, Dict[str, Any]] = {}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def db_path() -> str:
    return str(repo_root() / "movies.db")


def open_db() -> sqlite3.Connection:
    p = db_path()
    if not os.path.exists(p):
        raise FileNotFoundError(f"movies.db introuvable: {p}")

    conn = sqlite3.connect(p, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = 10000")
    return conn


def new_game_id() -> str:
    return os.urandom(8).hex()


def internal_error(where: str, exc: Exception):
    return (
        jsonify(
            {
                "error": "Internal error",
                "where": where,
                "detail": str(exc),
                "trace": traceback.format_exc(),
                "db_path": db_path(),
            }
        ),
        500,
    )


@app.get("/")
def health():
    return jsonify({"status": "ok", "service": "Akinator API", "db": db_path()}), 200


@app.post("/akinator/start")
def start_game():
    try:
        conn = open_db()
        try:
            load_genres(conn)

            movies = discover_movies(conn)
            state = init_state(movies)
            sort_candidates(state)

            # QUESTIONS construites ici avec conn vivant
            questions = default_questions(conn)

            q = choose_best_question(
                state.candidates,
                questions,
                state.asked,
                is_first_question=True,
                state=state,
            )
            if q is None:
                return jsonify({"error": "Aucune question trouvée"}), 400

            gid = new_game_id()

            # Stocker uniquement l'état + la question courante
            game_state[gid] = {
                "state": state,
                "current_qkey": q.key,
            }

            return jsonify(
                {
                    "game_id": gid,
                    "question": q.text,
                    "question_key": q.key,
                    "options": OPTIONS_UI,
                    "finished": False,
                }
            ), 200
        finally:
            conn.close()
    except Exception as e:
        return internal_error("start_game", e)


@app.post("/akinator/answer")
def answer():
    try:
        data = request.get_json(silent=True) or {}
        gid = data.get("game_id")
        ui_answer = data.get("answer")
        q_key = data.get("question_key")

        if not gid:
            return jsonify({"error": "game_id manquant"}), 400
        if gid not in game_state:
            return jsonify({"error": "Partie non trouvée"}), 404

        if ui_answer not in UI_TO_ENGINE:
            return jsonify({"error": "Réponse invalide", "got": ui_answer}), 400

        session = game_state[gid]
        state = session["state"]

        # q_key obligatoire, sinon fallback
        if not q_key:
            q_key = session.get("current_qkey")
        if not q_key:
            return jsonify({"error": "question_key manquant"}), 400

        conn = open_db()
        try:
            load_genres(conn)

            # QUESTIONS reconstruites à chaque requête (conn vivant)
            questions = default_questions(conn)

            q = next((qq for qq in questions if qq.key == q_key), None)
            if q is None:
                return jsonify({"error": "Question introuvable", "question_key": q_key}), 400

            engine_answer = UI_TO_ENGINE[ui_answer]

            state.asked.add(q.key)
            state.question_count += 1

            update_state_with_answer(state, q, engine_answer, max_strikes=3)
            sort_candidates(state)

            # Vérifier s'il faut proposer un film
            return _next_step(state, questions, session)

        finally:
            conn.close()

    except Exception as e:
        return internal_error("answer", e)


def _next_step(state, questions, session):
    """Logique commune pour déterminer: proposer question ou film"""
    
    if not state.candidates:
        return jsonify({"finished": True, "guess": "Désolé, j'ai échoué! 😅"}), 200
    
    # Si peu de candidats, proposer le top film
    if len(state.candidates) <= 3:
        film = state.candidates[0]
        session["proposed_film_id"] = film.get("id")
        return jsonify({
            "finished": False,
            "asking_confirmation": True,
            "guess": film.get("title", "Inconnu"),
            "guess_id": film.get("id"),
            "confirmation_options": ["Oui, c'est ça!", "Non, continuer"]
        }), 200
    
    # Sinon, poser la question suivante
    q2 = choose_best_question(
        state.candidates,
        questions,
        state.asked,
        is_first_question=False,
        state=state,
    )

    if q2 is None:
        # Plus de questions, proposer le top film
        film = state.candidates[0]
        session["proposed_film_id"] = film.get("id")
        return jsonify({
            "finished": False,
            "asking_confirmation": True,
            "guess": film.get("title", "Inconnu"),
            "guess_id": film.get("id"),
            "confirmation_options": ["Oui, c'est ça!", "Non, continuer"]
        }), 200

    session["current_qkey"] = q2.key
    return jsonify({
        "finished": False,
        "question": q2.text,
        "question_key": q2.key,
        "options": OPTIONS_UI,
    }), 200


@app.post("/akinator/confirm")
def confirm_guess():
    """Confirme ou rejette le film proposé"""
    try:
        data = request.get_json(silent=True) or {}
        gid = data.get("game_id")
        confirmed = data.get("confirmed")  # True si "Oui", False si "Non"

        if not gid:
            return jsonify({"error": "game_id manquant"}), 400
        if gid not in game_state:
            return jsonify({"error": "Partie non trouvée"}), 404

        if not isinstance(confirmed, bool):
            return jsonify({"error": "confirmed doit être true ou false"}), 400

        session = game_state[gid]
        state = session["state"]

        # Si confirmation = Oui
        if confirmed:
            film = state.candidates[0]
            return jsonify({
                "finished": True,
                "guess": film.get("title", "Inconnu"),
                "message": "Bien joué! 🎬"
            }), 200

        # Sinon = Non → Supprimer ce film et CONTINUER LES QUESTIONS
        if state.candidates:
            state.candidates = state.candidates[1:]

        if not state.candidates:
            return jsonify({
                "finished": True,
                "guess": "Désolé, j'ai échoué! 😅"
            }), 200

        conn = open_db()
        try:
            load_genres(conn)
            questions = default_questions(conn)

            # Poser la PROCHAINE QUESTION (pas proposer un autre film)
            q2 = choose_best_question(
                state.candidates,
                questions,
                state.asked,
                is_first_question=False,
                state=state,
            )

            if q2 is None:
                if state.candidates:
                    return jsonify({
                        "finished": True,
                        "guess": state.candidates[0].get("title", "Inconnu")
                    }), 200
                return jsonify({
                    "finished": True,
                    "guess": "Désolé, j'ai échoué! 😅"
                }), 200

            session["current_qkey"] = q2.key

            return jsonify({
                "finished": False,
                "question": q2.text,
                "question_key": q2.key,
                "options": OPTIONS_UI
            }), 200

        finally:
            conn.close()

    except Exception as e:
        return internal_error("confirm_guess", e)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True, use_reloader=False)

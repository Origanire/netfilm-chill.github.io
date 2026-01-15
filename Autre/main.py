from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import threading
import asyncio
import subprocess
import sys
import os
import uuid
import time
from pydantic import BaseModel
import importlib

# importer le module Guesser pour réutiliser les helpers DB
try:
    GUESSER = importlib.import_module('backend.Guesser')
except Exception:
    try:
        # fallback si exécuté depuis backend/ directement
        GUESSER = importlib.import_module('Guesser')
    except Exception:
        GUESSER = None


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# `Guesser.py` se trouve dans le même dossier que ce fichier `main.py` (backend/)
GUESSER_PATH = os.path.join(os.path.dirname(__file__), "Guesser.py")
# projet racine (un niveau au-dessus de `backend/`) contenant `movies.db`
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SQLITE_FALLBACK_DIR = os.path.join(PROJECT_ROOT, "sqlite_parsing")


class InputPayload(BaseModel):
    text: str


class GuessPayload(BaseModel):
    title: str


class GameProcess:
    def __init__(self, cmd):
        # lancer Python en mode non-buffered aide à récupérer les prompts affichés
        if cmd and cmd[0].endswith('python') or cmd and cmd[0].endswith('python.exe'):
            # si la commande est [sys.executable, GUESSER_PATH], insérer -u
            cmd = [cmd[0], '-u'] + cmd[1:]

        # choisir le répertoire de travail : priorité = dossier de Guesser.py > racine projet > sqlite_parsing/
        dir_guesser = os.path.dirname(GUESSER_PATH)
        cwd = PROJECT_ROOT
        # support des noms alternatifs de DB (movies.db ou movies_akinator 1.db)
        if os.path.exists(os.path.join(dir_guesser, 'movies.db')) or os.path.exists(os.path.join(dir_guesser, 'movies_akinator 1.db')):
            cwd = dir_guesser
        elif os.path.exists(os.path.join(PROJECT_ROOT, 'movies.db')) or os.path.exists(os.path.join(PROJECT_ROOT, 'movies_akinator 1.db')):
            cwd = PROJECT_ROOT
        elif os.path.exists(os.path.join(SQLITE_FALLBACK_DIR, 'movies.db')):
            cwd = SQLITE_FALLBACK_DIR

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,
            cwd=cwd,
        )
        self.lock = threading.Lock()
        self.buffer = ""
        self.alive = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        try:
            # Lire par blocs pour réduire l'overhead (meilleure performance)
            while True:
                chunk = self.proc.stdout.read(1024)
                if chunk == '':
                    # EOF
                    break
                if not chunk:
                    # nothing read currently
                    continue
                with self.lock:
                    self.buffer += chunk
        finally:
            self.alive = False

    def read(self):
        with self.lock:
            out = self.buffer
            self.buffer = ""
        return out

    def send(self, s: str):
        if not self.alive:
            raise BrokenPipeError("process not running")
        try:
            self.proc.stdin.write(s + "\n")
            self.proc.stdin.flush()
        except Exception:
            raise

    def stop(self):
        try:
            self.proc.terminate()
        except Exception:
            pass
        self.alive = False


class GameInProcess:
    """Engine en mémoire utilisant directement les helpers de `Guesser` (plus rapide)."""
    def __init__(self, db_path: str, pages: int = 0, max_strikes: int = 3):
        self.lock = threading.Lock()
        self.buffer = ''
        self.alive = True
        self.max_strikes = max_strikes
        self.db_path = db_path
        self.pages = pages
        self.finished = False

        try:
            self.conn = GUESSER.get_connection(db_path)
        except Exception:
            self.conn = None

        # load minimal candidates quickly
        try:
            movies = None
            if hasattr(GUESSER, '_load_persistent_movies_cache'):
                try:
                    movies = GUESSER._load_persistent_movies_cache(db_path)
                except Exception:
                    movies = None
            if movies is None:
                movies = GUESSER.discover_movies_light(self.conn, pages=pages)
            self.movies = movies
        except Exception:
            self.movies = []

        try:
            self.questions = GUESSER.default_questions(self.conn)
        except Exception:
            self.questions = []

        self.state = GUESSER.init_state(self.movies)
        GUESSER.sort_candidates(self.state)
        self.history = []
        self.pending_guess = None
        self.pending_question = None
        # prepare first question
        q = None
        try:
            q = GUESSER.choose_best_question(self.state.candidates, self.questions, self.state.asked)
        except Exception:
            q = None
        if q is not None:
            self.pending_question = q
            self.buffer += f"Question #{self.state.question_count + 1}: {q.text}\n"
        else:
            # no question available
            self.buffer += "Aucune question disponible.\n"

    def read(self) -> str:
        with self.lock:
            out = self.buffer
            self.buffer = ''
        return out

    def stop(self):
        with self.lock:
            self.alive = False

    def send(self, ans: str):
        with self.lock:
            if not self.alive:
                raise BrokenPipeError('process not running')

            # handle undo
            if ans == 'u':
                if not self.history:
                    self.buffer += "Impossible: aucun historique.\n"
                    return
                self.state = self.history.pop()
                GUESSER.sort_candidates(self.state)
                self.buffer += "OK, retour en arrière effectué.\n"
                # compute next question
                q = GUESSER.choose_best_question(self.state.candidates, self.questions, self.state.asked)
                self.pending_question = q
                if q is not None:
                    self.buffer += f"Question #{self.state.question_count + 1}: {q.text}\n"
                return

            # If we are in guess confirmation mode
            if self.pending_guess is not None:
                # ans should be y/n
                if ans.lower() == 'y':
                    guess = self.pending_guess
                    self.buffer += f"\nJ'AI TROUVÉ : {GUESSER.short_movie_str(guess)}\n"
                    self.finished = True
                    self.alive = False
                    return
                else:
                    # eliminate and continue
                    mid = GUESSER.movie_id(self.pending_guess)
                    if mid is not None:
                        GUESSER.eliminate_movie(self.state, mid)
                    GUESSER.sort_candidates(self.state)
                    self.pending_guess = None
                    self.buffer += "OK, je continue.\n"
                    # compute next question
                    q = GUESSER.choose_best_question(self.state.candidates, self.questions, self.state.asked)
                    self.pending_question = q
                    if q is not None:
                        self.buffer += f"Question #{self.state.question_count + 1}: {q.text}\n"
                    return

            # Normal question answer flow
            q = self.pending_question
            if q is None:
                self.buffer += "Aucune question en attente.\n"
                return

            # snapshot
            self.history.append(GUESSER.snapshot_state(self.state))
            self.state.asked.add(q.key)
            self.state.question_count += 1
            # update
            try:
                GUESSER.update_state_with_answer(self.state, q, ans, max_strikes=self.max_strikes, debug_target_id=None)
            except Exception:
                pass

            # check convergence / guess conditions
            if len(self.state.candidates) == 1:
                top = self.state.candidates[0]
                self.buffer += f"\nJ'AI TROUVÉ : {GUESSER.short_movie_str(top)}\n"
                self.finished = True
                self.alive = False
                return

            # optional guess mode
            if GUESSER.should_enter_guess_mode(self.state):
                top = self.state.candidates[0]
                guess = GUESSER.short_movie_str(top)
                # enter guess confirmation mode
                self.pending_guess = top
                self.pending_question = None
                self.buffer += f"Question #{self.state.question_count}: Je pense que c'est: {guess}. C'est ça ? (y/n) : \n"
                return

            # otherwise compute next question
            q2 = GUESSER.choose_best_question(self.state.candidates, self.questions, self.state.asked)
            self.pending_question = q2
            if q2 is not None:
                self.buffer += f"Question #{self.state.question_count + 1}: {q2.text}\n"
            else:
                self.buffer += "Je n'ai plus de questions à poser.\n"


games = {}
# global singleton game to avoid multiple processes when frontend starts twice
GLOBAL_GAME_ID = None
GLOBAL_GAME = None
# lock pour empêcher une création concurrente de GameProcess
GLOBAL_GAME_LOCK = threading.Lock()

PRECOMPUTED = None
PRECOMPUTED_LOCK = threading.Lock()

def _precompute_initial_question():
    global PRECOMPUTED
    if GUESSER is None:
        return None
    try:
        db_path = _locate_db_path()
        conn = GUESSER.get_connection(db_path)
        # charger genres si possible
        try:
            GUESSER.load_genres(conn)
        except Exception:
            pass

        # essayer d'utiliser le cache léger si exposé
        movies = None
        try:
            if hasattr(GUESSER, '_load_persistent_movies_cache'):
                movies = GUESSER._load_persistent_movies_cache(db_path)
        except Exception:
            movies = None

        if movies is None:
            try:
                movies = GUESSER.discover_movies_light(conn, pages=1)
            except Exception:
                movies = []

        questions = []
        try:
            questions = GUESSER.default_questions(conn)
        except Exception:
            questions = []

        state = GUESSER.init_state(movies)
        q = None
        try:
            q = GUESSER.choose_best_question(state.candidates, questions, state.asked)
        except Exception:
            q = None

        with PRECOMPUTED_LOCK:
            PRECOMPUTED = {
                'question': q.text if q is not None else None,
                'candidates': len(state.candidates),
                'timestamp': time.time(),
            }
        return PRECOMPUTED
    except Exception:
        return None


@app.get('/game/precomputed')
def game_precomputed():
    with PRECOMPUTED_LOCK:
        if PRECOMPUTED is not None:
            return PRECOMPUTED
    # compute on demand (non-blocking in startup, but OK on first request)
    p = _precompute_initial_question()
    if p is None:
        raise HTTPException(status_code=500, detail='precompute failed')
    return p


def _ensure_global_game_preheated():
    """Créer un processus Guesser persistant si absent (pré-chauffage)."""
    global GLOBAL_GAME_ID, GLOBAL_GAME
    with GLOBAL_GAME_LOCK:
        if GLOBAL_GAME and GLOBAL_GAME.alive:
            return GLOBAL_GAME_ID
        try:
            db_path = _locate_db_path()
            gid = str(uuid.uuid4())
            if GUESSER is not None:
                # prefer in-process engine for speed
                gp = GameInProcess(db_path=db_path, pages=1)
            else:
                if not os.path.exists(GUESSER_PATH):
                    return None
                cmd = [sys.executable, GUESSER_PATH]
                gp = GameProcess(cmd)
            games[gid] = gp
            GLOBAL_GAME_ID = gid
            GLOBAL_GAME = gp
            # give it a short moment to write initial prompts
            time.sleep(0.1)
            # read initial output to fill buffer
            _ = gp.read()
            return GLOBAL_GAME_ID
        except Exception:
            return None


@app.on_event("startup")
def app_startup():
    # préchauffer le processus Guesser en tâche de fond pour rendre l'accès instantané
    threading.Thread(target=_ensure_global_game_preheated, daemon=True).start()


@app.on_event("shutdown")
def app_shutdown():
    global GLOBAL_GAME_ID, GLOBAL_GAME
    try:
        if GLOBAL_GAME:
            GLOBAL_GAME.stop()
    except Exception:
        pass
    GLOBAL_GAME_ID = None
    GLOBAL_GAME = None


@app.post("/game/start")
def start_game():
    try:
        if not os.path.exists(GUESSER_PATH):
            raise FileNotFoundError(f"Guesser.py not found at {GUESSER_PATH}")
        global GLOBAL_GAME_ID, GLOBAL_GAME
        # protection contre la course : n'autorise qu'un seul créateur à la fois
        with GLOBAL_GAME_LOCK:
            # Si, pendant qu'on attendait le lock, un jeu global a été créé, l'utiliser
            if GLOBAL_GAME and GLOBAL_GAME.alive:
                out = GLOBAL_GAME.read()
                return {"game_id": GLOBAL_GAME_ID, "output": out}
            gid = str(uuid.uuid4())
            db_path = _locate_db_path()
            # prefer in-process engine when available
            if GUESSER is not None:
                gp = GameInProcess(db_path=db_path, pages=1)
            else:
                cmd = [sys.executable, GUESSER_PATH]
                gp = GameProcess(cmd)
            games[gid] = gp
            GLOBAL_GAME_ID = gid
            GLOBAL_GAME = gp
            # laisser un court délai pour que le processus écrive son premier prompt
            time.sleep(0.1)
            return {"game_id": gid, "output": gp.read()}
    except Exception as e:
        # logger pour débogage
        print("[backend/main] erreur démarrage jeu:", repr(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket('/ws/game')
async def websocket_game(websocket: WebSocket):
    await websocket.accept()
    # ensure a game exists
    gid = _ensure_global_game_preheated()
    if gid is None:
        await websocket.send_text('Erreur: impossible de créer le moteur de jeu')
        await websocket.close()
        return
    game = GLOBAL_GAME

    try:
        # send initial buffer if any
        out = game.read()
        if out:
            await websocket.send_text(out)

        while True:
            # concurrently check for client input and for game output
            try:
                data_task = asyncio.create_task(websocket.receive_text())
                done, pending = await asyncio.wait([data_task], timeout=0.15)
                if data_task in done:
                    data = data_task.result()
                    if data is None:
                        continue
                    # protocol: 'INPUT:<answer>' or 'STOP'
                    if data.startswith('INPUT:'):
                        ans = data.split('INPUT:', 1)[1]
                        try:
                            game.send(ans.strip())
                        except BrokenPipeError:
                            await websocket.send_text('Erreur: jeu interrompu')
                            break
                        # immediately flush output
                        out = game.read()
                        if out:
                            await websocket.send_text(out)
                    elif data == 'STOP':
                        game.stop()
                        await websocket.send_text('Jeu arrêté.')
                        break
                    else:
                        # ignore unknown
                        pass
                else:
                    # no incoming message: send any new output
                    out = game.read()
                    if out:
                        await websocket.send_text(out)
                    # cancel pending receive to avoid leaks
                    for p in pending:
                        p.cancel()

                # if game ended, notify and close
                if not game.alive:
                    try:
                        out = game.read()
                        if out:
                            await websocket.send_text(out)
                    except Exception:
                        pass
                    break

            except WebSocketDisconnect:
                break
            except Exception:
                # on unexpected error, break the loop
                break

    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.post("/game/{gid}/input")
def send_input(gid: str, payload: InputPayload):
    game = games.get(gid)
    if not game or not game.alive:
        raise HTTPException(status_code=404, detail="game not found or ended")
    try:
        game.send(payload.text)
    except BrokenPipeError:
        raise HTTPException(status_code=500, detail="game process not running")
    # court délai pour laisser le process produire la sortie avant de la lire
    time.sleep(0.05)
    out = game.read()
    return {"output": out}


@app.get("/game/{gid}/output")
def get_output(gid: str):
    game = games.get(gid)
    if not game:
        raise HTTPException(status_code=404, detail="game not found")
    return {"alive": game.alive, "output": game.read()}


@app.post("/game/{gid}/stop")
def stop_game(gid: str):
    game = games.get(gid)
    if not game:
        raise HTTPException(status_code=404, detail="game not found")
    game.stop()
    # if this was the global game, clear global refs
    global GLOBAL_GAME_ID, GLOBAL_GAME
    if GLOBAL_GAME_ID == gid:
        GLOBAL_GAME_ID = None
        GLOBAL_GAME = None
    return {"stopped": True}


def _locate_db_path() -> str:
    # même logique que lors du choix du cwd : backend dir, project root, sqlite_parsing
    dir_backend = os.path.dirname(GUESSER_PATH)
    paths = [
        os.path.join(dir_backend, 'movies_akinator 1.db'),
        os.path.join(dir_backend, 'movies.db'),
        os.path.join(PROJECT_ROOT, 'movies_akinator 1.db'),
        os.path.join(PROJECT_ROOT, 'movies.db'),
        os.path.join(SQLITE_FALLBACK_DIR, 'movies.db'),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    # fallback: default to backend/movies.db path
    return os.path.join(dir_backend, 'movies.db')


@app.get('/movie/search')
def movie_search(title: str):
    """Recherche un film par titre (approx.) dans la DB locale et renvoie ses détails."""
    db_path = _locate_db_path()
    if GUESSER is None:
        raise HTTPException(status_code=500, detail='Guesser helper unavailable')
    try:
        conn = GUESSER.get_connection(db_path)
        cur = conn.cursor()
        # exact match, case-insensitive
        cur.execute("SELECT id, title FROM movies WHERE LOWER(title) = LOWER(?) LIMIT 1", (title,))
        row = cur.fetchone()
        if not row:
            # try substring
            cur.execute("SELECT id, title FROM movies WHERE LOWER(title) LIKE LOWER(?) LIMIT 1", (f"%{title}%",))
            row = cur.fetchone()
        if not row:
            return {"found": False, "message": "Movie not found"}
        mid = row[0]
        details = GUESSER.get_details(conn, int(mid))
        return {"found": True, "movie_id": mid, "details": details}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/movie/{mid}')
def movie_get(mid: int):
    db_path = _locate_db_path()
    if GUESSER is None:
        raise HTTPException(status_code=500, detail='Guesser helper unavailable')
    try:
        conn = GUESSER.get_connection(db_path)
        details = GUESSER.get_details(conn, int(mid))
        if not details:
            raise HTTPException(status_code=404, detail='movie not found')
        return details
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




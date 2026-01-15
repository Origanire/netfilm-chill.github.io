from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import random
import requests
import os

app = Flask(__name__)
origin = os.getenv("ALLOWED_ORIGIN", "https://origanire.github.io")
CORS(app, resources={r"/*": {"origins": [origin]}})

@app.route("/", methods=["GET"])
def home():
    return "Bienvenue sur l'API Blind Test ! Utilisez les routes /api/... pour accéder aux fonctionnalités."

# Base de données de musiques de films (vous pouvez l'enrichir)
SOUNDTRACKS = [
    {
        "id": 1,
        "title": "Titanic",
        "composer": "James Horner",
        "year": 1997,
        "difficulty": "easy",
        "movie_id": 597
    },
    {
        "id": 2,
        "title": "Interstellar",
        "composer": "Hans Zimmer",
        "year": 2014,
        "difficulty": "medium",
        "movie_id": 157336
    },
    {
        "id": 3,
        "title": "Inception",
        "composer": "Hans Zimmer",
        "year": 2010,
        "difficulty": "medium",
        "movie_id": 27205
    },
    {
        "id": 4,
        "title": "The Dark Knight",
        "composer": "Hans Zimmer, James Newton Howard",
        "year": 2008,
        "difficulty": "hard",
        "movie_id": 155
    },
    {
        "id": 5,
        "title": "Forrest Gump",
        "composer": "Alan Silvestri",
        "year": 1994,
        "difficulty": "easy",
        "movie_id": 13
    },
    {
        "id": 6,
        "title": "Le roi lion",
        "composer": "Elton John, Tim Rice",
        "year": 1994,
        "difficulty": "easy",
        "movie_id": 8587
    },
    {
        "id": 7,
        "title": "Gladiator",
        "composer": "Hans Zimmer, Lisa Gerrard",
        "year": 2000,
        "difficulty": "medium",
        "movie_id": 98
    },
    {
        "id": 8,
        "title": "The Avengers",
        "composer": "Alan Silvestri",
        "year": 2012,
        "difficulty": "hard",
        "movie_id": 24428
    },
    {
        "id": 9,
        "title": "Jurassic Park",
        "composer": "John Williams",
        "year": 1993,
        "difficulty": "easy",
        "movie_id": 329
    },
    {
        "id": 10,
        "title": "Star Wars: A New Hope",
        "composer": "John Williams",
        "year": 1977,
        "difficulty": "easy",
        "movie_id": 11
    },
]

@app.route('/api/data', methods=['GET'])
def get_data():
    return jsonify({"message": "Hello from Flask!"})

@app.route('/api/quiz/random', methods=['GET'])
def get_random_quiz():
    """Retourne une question de blind test aléatoire"""
    difficulty = request.args.get('difficulty', None)
    
    if difficulty:
        questions = [q for q in SOUNDTRACKS if q['difficulty'] == difficulty]
    else:
        questions = SOUNDTRACKS
    
    if not questions:
        return jsonify({"error": "Aucune question disponible"}), 404
    
    question = random.choice(questions)
    
    # On retourne la question sans la réponse
    return jsonify({
        "id": question["id"],
        "title": question["title"],
        "composer": question["composer"],
        "year": question["year"],
        "difficulty": question["difficulty"]
    })

@app.route('/api/quiz/all', methods=['GET'])
def get_all_quiz():
    """Retourne toutes les questions de blind test"""
    return jsonify(SOUNDTRACKS)

@app.route('/api/quiz/<int:quiz_id>/answer', methods=['POST'])
def check_answer(quiz_id):
    """Vérifie la réponse donnée"""
    data = request.json
    user_answer = data.get('answer', '').strip().lower()
    
    # Chercher la question
    question = next((q for q in SOUNDTRACKS if q['id'] == quiz_id), None)
    
    if not question:
        return jsonify({"error": "Question non trouvée"}), 404
    
    correct_title = question['title'].lower()
    
    # Vérification simple (peut être améliorée)
    is_correct = user_answer == correct_title or user_answer in correct_title
    
    return jsonify({
        "correct": is_correct,
        "answer": question['title'],
        "composer": question['composer'],
        "year": question['year']
    })

@app.route('/api/quiz/random-set', methods=['GET'])
def get_random_set():
    """Retourne un set de 10 questions aléatoires pour un blind test complet"""
    num_questions = request.args.get('count', 10, type=int)
    difficulty = request.args.get('difficulty', None)
    
    if difficulty:
        available = [q for q in SOUNDTRACKS if q['difficulty'] == difficulty]
    else:
        available = SOUNDTRACKS
    
    if len(available) < num_questions:
        num_questions = len(available)
    
    questions = random.sample(available, num_questions)
    
    # Retourner sans les réponses
    return jsonify([{
        "id": q["id"],
        "title": q["title"],
        "composer": q["composer"],
        "year": q["year"],
        "difficulty": q["difficulty"]
    } for q in questions])

@app.route('/api/stats', methods=['POST'])
def save_stats():
    """Sauvegarde les statistiques du joueur"""
    data = request.json
    score = data.get('score', 0)
    total = data.get('total', 0)
    username = data.get('username', 'Anonymous')
    difficulty = data.get('difficulty', 'mixed')
    
    # Ici vous pouvez sauvegarder dans une base de données
    return jsonify({
        "success": True,
        "message": f"Résultats sauvegardés: {score}/{total}",
        "score": score,
        "total": total,
        "percentage": round((score / total * 100) if total > 0 else 0, 2)
    })

@app.route('/api/audio/<int:quiz_id>', methods=['GET'])
def get_audio(quiz_id):
    """Serve audio files for soundtracks"""
    # Chercher la question
    question = next((q for q in SOUNDTRACKS if q['id'] == quiz_id), None)
    
    if not question:
        return jsonify({"error": "Question non trouvée"}), 404
    
    # Créer le chemin du fichier audio
    audio_filename = f"{question['id']}.mp3"
    audio_path = os.path.join(
        os.path.dirname(__file__),
        '..', 'projectweek', 'public', 'soundtracks', audio_filename
    )
    
    # Vérifier si le fichier existe
    if os.path.exists(audio_path):
        return send_file(audio_path, mimetype='audio/mpeg')
    else:
        return jsonify({
            "error": "Fichier audio non trouvé",
            "expected_path": audio_path,
            "hint": f"Placez votre fichier audio à: {audio_path}"
        }), 404

if __name__ == '__main__':
    port = int(os.getenv('BLINDTEST_PORT', 5002))
    app.run(host='0.0.0.0', debug=True, port=port)

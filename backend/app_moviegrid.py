from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
origin = os.getenv("ALLOWED_ORIGIN", "https://origanire.github.io")
CORS(app, resources={r"/*": {"origins": [origin]}})

# Clé API TMDB - À configurer dans les variables d'environnement
TMDB_API_KEY = os.getenv('TMDB_API_KEY', 'a46949b0732719a510a26fd7c0a1a3ae')

@app.route("/", methods=["GET"])
def home():
    return "Bienvenue sur l'API MovieGrid !"

@app.route('/moviegrid/verify-movie', methods=['POST'])
def verify_movie():
    """Vérifie si un film correspond aux deux critères donnés"""
    try:
        data = request.json
        movie_id = data.get('movieId')
        row_criterion = data.get('rowCriterion')
        col_criterion = data.get('colCriterion')

        if not movie_id or not row_criterion or not col_criterion:
            return jsonify({'isValid': False}), 400

        # Récupérer les détails du film depuis TMDB
        url = f"https://api.themoviedb.org/3/movie/{movie_id}"
        params = {
            'api_key': TMDB_API_KEY,
            'append_to_response': 'credits,release_dates',
            'language': 'fr-FR'
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code != 200:
            print(f"[MovieGrid] Movie fetch failed: {movie_id}")
            return jsonify({'isValid': False})

        movie = response.json()
        
        # Vérifier les deux critères
        matches_row = check_criterion(movie, row_criterion)
        matches_col = check_criterion(movie, col_criterion)

        print(f"[MovieGrid] Verification: {movie.get('title')} - Row: {matches_row}, Col: {matches_col}")

        return jsonify({'isValid': matches_row and matches_col})

    except Exception as e:
        print(f"[MovieGrid] Error verifying movie: {e}")
        return jsonify({'isValid': False})


def check_criterion(movie, criterion):
    """Vérifie si un film correspond à un critère donné"""
    criterion_type = criterion.get('type')
    criterion_value = criterion.get('value')

    if criterion_type == 'genre':
        genre_ids = [str(g['id']) for g in movie.get('genres', [])]
        return criterion_value in genre_ids

    elif criterion_type == 'actor':
        actor_ids = [str(c['id']) for c in movie.get('credits', {}).get('cast', [])]
        return criterion_value in actor_ids

    elif criterion_type == 'director':
        crew = movie.get('credits', {}).get('crew', [])
        director_ids = [str(c['id']) for c in crew if c.get('job') == 'Director']
        return criterion_value in director_ids

    elif criterion_type == 'year':
        release_date = movie.get('release_date', '')
        if not release_date:
            return False
        release_year = int(release_date[:4])
        start_year, end_year = map(int, criterion_value.split('-'))
        return start_year <= release_year <= end_year

    elif criterion_type == 'studio':
        company_ids = [str(c['id']) for c in movie.get('production_companies', [])]
        return criterion_value in company_ids

    elif criterion_type == 'language':
        languages = [movie.get('original_language')]
        languages.extend([l['iso_639_1'] for l in movie.get('spoken_languages', [])])
        return criterion_value in languages

    return False


@app.route('/moviegrid/search-movies', methods=['GET'])
def search_movies():
    """Recherche des films par titre"""
    query = request.args.get('query', '')
    
    if not query:
        return jsonify({'results': []})

    try:
        url = "https://api.themoviedb.org/3/search/movie"
        params = {
            'api_key': TMDB_API_KEY,
            'query': query,
            'language': 'fr-FR'
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({'results': []})

    except Exception as e:
        print(f"[MovieGrid] Error searching movies: {e}")
        return jsonify({'error': 'Failed to search movies'}), 500


@app.route('/moviegrid/get-solutions', methods=['POST'])
def get_solutions():
    """Récupère les solutions possibles pour une combinaison de critères"""
    try:
        data = request.json
        row_criterion = data.get('rowCriterion')
        col_criterion = data.get('colCriterion')

        if not row_criterion or not col_criterion:
            return jsonify({'movies': []})

        # Construire l'URL de découverte TMDB
        url = "https://api.themoviedb.org/3/discover/movie"
        params = {
            'api_key': TMDB_API_KEY,
            'language': 'fr-FR',
            'sort_by': 'popularity.desc',
            'page': 1
        }

        # Appliquer les critères
        params = apply_criterion_to_params(params, row_criterion)
        params = apply_criterion_to_params(params, col_criterion)

        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            movies = data.get('results', [])[:10]  # Top 10 résultats
            
            formatted_movies = [
                {
                    'id': m['id'],
                    'title': m['title'],
                    'release_date': m.get('release_date', ''),
                    'poster_path': m.get('poster_path', '')
                }
                for m in movies
            ]
            
            return jsonify({'movies': formatted_movies})
        else:
            return jsonify({'movies': []})

    except Exception as e:
        print(f"[MovieGrid] Error getting solutions: {e}")
        return jsonify({'movies': []})


def apply_criterion_to_params(params, criterion):
    """Applique un critère aux paramètres de requête TMDB"""
    criterion_type = criterion.get('type')
    criterion_value = criterion.get('value')

    if criterion_type == 'genre':
        params['with_genres'] = criterion_value

    elif criterion_type == 'actor':
        params['with_cast'] = criterion_value

    elif criterion_type == 'director':
        params['with_crew'] = criterion_value

    elif criterion_type == 'year':
        start_year, end_year = criterion_value.split('-')
        params['primary_release_date.gte'] = f"{start_year}-01-01"
        params['primary_release_date.lte'] = f"{end_year}-12-31"

    elif criterion_type == 'studio':
        params['with_companies'] = criterion_value

    elif criterion_type == 'language':
        params['with_original_language'] = criterion_value

    return params


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=True)

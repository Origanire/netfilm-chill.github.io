import React, { useState, useEffect, Fragment } from 'react';
import './MovieGrid.css';
import { API_ENDPOINTS } from '../config/api';

const API_URL = API_ENDPOINTS.MOVIEGRID;

export default function MovieGrid() {
  const [gridCells, setGridCells] = useState([]);
  const [selectedCell, setSelectedCell] = useState(null);
  const [score, setScore] = useState(0);
  const [attempts, setAttempts] = useState(0);
  const [rowCriteria, setRowCriteria] = useState([]);
  const [colCriteria, setColCriteria] = useState([]);
  const [debugMode, setDebugMode] = useState(false);
  const [debugSolutions, setDebugSolutions] = useState([]);
  const [showSearchDialog, setShowSearchDialog] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);

  useEffect(() => {
    initializeGame();
    // eslint-disable-next-line
  }, []);

  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }

    const delayDebounceFn = setTimeout(() => {
      searchMovies(searchQuery);
    }, 500);

    return () => clearTimeout(delayDebounceFn);
    // eslint-disable-next-line
  }, [searchQuery]);

  const initializeGame = async () => {
    const cells = [];
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 3; col++) {
        cells.push({
          row,
          col,
          movieId: null,
          movieTitle: null,
          moviePoster: null,
          isCorrect: null,
        });
      }
    }
    setGridCells(cells);
    setScore(0);
    setAttempts(0);

    const genres = [
      { type: 'genre', value: '28', label: 'Action' },
      { type: 'genre', value: '35', label: 'Comédie' },
      { type: 'genre', value: '18', label: 'Drame' },
      { type: 'genre', value: '27', label: 'Horreur' },
      { type: 'genre', value: '878', label: 'Science-Fiction' },
      { type: 'genre', value: '53', label: 'Thriller' },
      { type: 'genre', value: '10749', label: 'Romance' },
      { type: 'genre', value: '16', label: 'Animation' },
    ];

    const actors = [
      { type: 'actor', value: '500', label: 'Tom Cruise' },
      { type: 'actor', value: '3894', label: 'Christian Bale' },
      { type: 'actor', value: '6193', label: 'Leonardo DiCaprio' },
      { type: 'actor', value: '2231', label: 'Samuel L. Jackson' },
      { type: 'actor', value: '1136', label: 'Natalie Portman' },
      { type: 'actor', value: '72129', label: 'Jennifer Lawrence' },
      { type: 'actor', value: '8691', label: 'Scarlett Johansson' },
      { type: 'actor', value: '1245', label: 'Will Smith' },
      { type: 'actor', value: '1892', label: 'Matt Damon' },
      { type: 'actor', value: '976', label: 'Jason Statham' },
      { type: 'actor', value: '5081', label: 'Emily Blunt' },
      { type: 'actor', value: '287', label: 'Brad Pitt' },
      { type: 'actor', value: '192', label: 'Morgan Freeman' },
    ];

    const directors = [
      { type: 'director', value: '525', label: 'Christopher Nolan' },
      { type: 'director', value: '138', label: 'Quentin Tarantino' },
      { type: 'director', value: '488', label: 'Steven Spielberg' },
      { type: 'director', value: '578', label: 'Ridley Scott' },
      { type: 'director', value: '893', label: 'James Cameron' },
      { type: 'director', value: '7467', label: 'David Fincher' },
      { type: 'director', value: '108', label: 'Peter Jackson' },
    ];

    const years = [
      { type: 'year', value: '1990-1999', label: 'Années 90' },
      { type: 'year', value: '2000-2009', label: 'Années 2000' },
      { type: 'year', value: '2010-2019', label: 'Années 2010' },
      { type: 'year', value: '2020-2024', label: 'Années 2020' },
    ];

    const studios = [
      { type: 'studio', value: '1', label: 'Warner Bros' },
      { type: 'studio', value: '2', label: 'Universal' },
      { type: 'studio', value: '4', label: 'Paramount' },
      { type: 'studio', value: '2', label: 'Disney' },
    ];

    const languages = [
      { type: 'language', value: 'en', label: 'Anglais' },
      { type: 'language', value: 'fr', label: 'Français' },
      { type: 'language', value: 'es', label: 'Espagnol' },
    ];

    const selectNonConflictingCriteria = () => {
      const typeGroups = { genre: genres, actor: actors, director: directors, year: years, studio: studios, language: languages };
      const types = Object.keys(typeGroups);
      const shuffled = [...types].sort(() => Math.random() - 0.5);
      
      const rowTypes = shuffled.slice(0, 3);
      const availableForCols = types.filter(t => !rowTypes.includes(t));
      const finalColTypes = availableForCols.slice(0, 3);

      const rows = rowTypes.map(type => {
        const criteriaList = typeGroups[type];
        return criteriaList[Math.floor(Math.random() * criteriaList.length)];
      });
      
      const cols = finalColTypes.map(type => {
        const criteriaList = typeGroups[type];
        return criteriaList[Math.floor(Math.random() * criteriaList.length)];
      });
      
      return { rows, cols };
    };

    const { rows: newRowCriteria, cols: newColCriteria } = selectNonConflictingCriteria();
    setRowCriteria(newRowCriteria);
    setColCriteria(newColCriteria);

    if (debugMode) {
      await fetchDebugSolutions(newRowCriteria, newColCriteria);
    }
  };

  const fetchDebugSolutions = async (rows, cols) => {
    const solutions = [];
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 3; col++) {
        try {
          const response = await fetch(`${API_URL}/get-solutions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              rowCriterion: rows[row],
              colCriterion: cols[col],
            }),
          });
          const data = await response.json();
          solutions.push({ row, col, movies: data.movies || [] });
        } catch (error) {
          console.error(`Error fetching solutions for cell ${row},${col}:`, error);
          solutions.push({ row, col, movies: [] });
        }
      }
    }
    setDebugSolutions(solutions);
  };

  const handleCellClick = (row, col) => {
    const cell = gridCells.find((c) => c.row === row && c.col === col);
    if (cell?.movieId) return;
    setSelectedCell({ row, col });
    setShowSearchDialog(true);
  };

  const searchMovies = async (query) => {
    setSearchLoading(true);
    try {
      const response = await fetch(`${API_URL}/search-movies?query=${encodeURIComponent(query)}`);
      const data = await response.json();
      setSearchResults(data.results || []);
    } catch (error) {
      console.error('Error searching movies:', error);
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  };

  const handleMovieSelect = async (movie) => {
    if (!selectedCell) return;

    const { row, col } = selectedCell;
    setAttempts(attempts + 1);

    const rowCriterion = rowCriteria[row];
    const colCriterion = colCriteria[col];

    const isValid = await verifyMovie(movie.id, rowCriterion, colCriterion);

    setGridCells((prev) =>
      prev.map((cell) =>
        cell.row === row && cell.col === col
          ? { ...cell, movieId: movie.id, movieTitle: movie.title, moviePoster: movie.poster_path, isCorrect: isValid }
          : cell,
      ),
    );

    if (isValid) {
      setScore(score + 1);
    }

    setSelectedCell(null);
    setShowSearchDialog(false);
    setSearchQuery('');
    setSearchResults([]);
  };

  const verifyMovie = async (movieId, rowCriterion, colCriterion) => {
    try {
      const response = await fetch(`${API_URL}/verify-movie`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ movieId, rowCriterion, colCriterion }),
      });
      const data = await response.json();
      return data.isValid;
    } catch (error) {
      console.error('Error verifying movie:', error);
      return false;
    }
  };

  const getCriteriaColor = (type) => {
    switch (type) {
      case 'genre': return 'criteria-genre';
      case 'actor': return 'criteria-actor';
      case 'director': return 'criteria-director';
      case 'year': return 'criteria-year';
      case 'studio': return 'criteria-studio';
      case 'language': return 'criteria-language';
      default: return 'criteria-default';
    }
  };

  const getDebugSolutionsForCell = (row, col) => {
    const solution = debugSolutions.find((s) => s.row === row && s.col === col);
    return solution?.movies || [];
  };

  return (
    <div className="moviegrid-container">
      <main className="moviegrid-main">
        <div className="moviegrid-card">
          <div className="moviegrid-header-section">
            <div className="moviegrid-stats">
              <div className="moviegrid-stat">
                <div className="moviegrid-stat-value">{score}</div>
                <div className="moviegrid-stat-label">Score</div>
              </div>
              <div className="moviegrid-stat">
                <div className="moviegrid-stat-value">{attempts}</div>
                <div className="moviegrid-stat-label">Tentatives</div>
              </div>
            </div>
            <div className="moviegrid-actions">
              <button
                onClick={() => {
                  const newDebugMode = !debugMode;
                  setDebugMode(newDebugMode);
                  if (newDebugMode && rowCriteria.length > 0) {
                    fetchDebugSolutions(rowCriteria, colCriteria);
                  }
                }}
                className={`btn ${debugMode ? 'btn-primary' : 'btn-secondary'}`}
              >
                🐛 Debug
              </button>
              <button onClick={initializeGame} className="btn btn-secondary">
                🔄 Nouvelle partie
              </button>
            </div>
          </div>

          <div className="moviegrid-grid-container">
            <div className="moviegrid-grid-corner"></div>

            {colCriteria.map((criterion) => (
              <div key={criterion.value} className="moviegrid-criteria-cell">
                <span className={`moviegrid-badge ${getCriteriaColor(criterion.type)}`}>
                  {criterion.label}
                </span>
              </div>
            ))}

            {[0, 1, 2].map((row) => (
              <Fragment key={`row-${row}`}>
                <div className="moviegrid-criteria-cell">
                  <span className={`moviegrid-badge ${getCriteriaColor(rowCriteria[row]?.type)}`}>
                    {rowCriteria[row]?.label}
                  </span>
                </div>

                {[0, 1, 2].map((col) => {
                  const cell = gridCells.find((c) => c.row === row && c.col === col);
                  const debugSols = debugMode ? getDebugSolutionsForCell(row, col) : [];

                  return (
                    <div key={`${row}-${col}`} className="moviegrid-cell-wrapper">
                      <button
                        onClick={() => handleCellClick(row, col)}
                        disabled={!!cell?.movieId}
                        className={`moviegrid-cell ${
                          selectedCell?.row === row && selectedCell?.col === col ? 'moviegrid-cell-selected' : ''
                        } ${cell?.isCorrect === true ? 'moviegrid-cell-correct' : ''} ${
                          cell?.isCorrect === false ? 'moviegrid-cell-incorrect' : ''
                        }`}
                      >
                        {cell?.movieId ? (
                          <div className="moviegrid-cell-content">
                            {cell.moviePoster ? (
                              <img
                                src={`https://image.tmdb.org/t/p/w200${cell.moviePoster}`}
                                alt={cell.movieTitle || ''}
                                className="moviegrid-cell-poster"
                              />
                            ) : (
                              <div className="moviegrid-cell-title">{cell.movieTitle}</div>
                            )}
                            <div className="moviegrid-cell-icon">
                              {cell.isCorrect ? (
                                <span className="icon-check">✓</span>
                              ) : (
                                <span className="icon-x">✗</span>
                              )}
                            </div>
                          </div>
                        ) : (
                          <div className="moviegrid-cell-empty">+</div>
                        )}
                      </button>
                      {debugMode && !cell?.movieId && debugSols.length > 0 && (
                        <div className="moviegrid-debug-badge">{debugSols.length}</div>
                      )}
                    </div>
                  );
                })}
              </Fragment>
            ))}
          </div>

          {debugMode && selectedCell && (
            <div className="moviegrid-debug-panel">
              <div className="moviegrid-debug-header">
                <h3>Combinaison pour la case ({selectedCell.row + 1}, {selectedCell.col + 1}):</h3>
                <div className="moviegrid-debug-criteria">
                  <div>
                    <p className="moviegrid-debug-label">Ligne:</p>
                    <span className={`moviegrid-badge ${getCriteriaColor(rowCriteria[selectedCell.row]?.type)}`}>
                      {rowCriteria[selectedCell.row]?.label}
                    </span>
                  </div>
                  <span>×</span>
                  <div>
                    <p className="moviegrid-debug-label">Colonne:</p>
                    <span className={`moviegrid-badge ${getCriteriaColor(colCriteria[selectedCell.col]?.type)}`}>
                      {colCriteria[selectedCell.col]?.label}
                    </span>
                  </div>
                </div>
              </div>
              <h3>Solutions trouvées:</h3>
              <div className="moviegrid-debug-solutions">
                {getDebugSolutionsForCell(selectedCell.row, selectedCell.col).map((movie) => (
                  <div key={movie.id}>
                    • {movie.title} ({movie.release_date ? new Date(movie.release_date).getFullYear() : 'N/A'})
                  </div>
                ))}
                {getDebugSolutionsForCell(selectedCell.row, selectedCell.col).length === 0 && (
                  <div className="moviegrid-debug-warning">⚠️ Aucune solution trouvée - combinaison impossible!</div>
                )}
              </div>
            </div>
          )}
        </div>

        {showSearchDialog && (
          <div className="moviegrid-dialog-overlay" onClick={() => setShowSearchDialog(false)}>
            <div className="moviegrid-dialog" onClick={(e) => e.stopPropagation()}>
              <div className="moviegrid-dialog-header">
                <h2>Rechercher un film</h2>
                <p>Entrez le titre d'un film qui correspond aux deux critères</p>
              </div>

              <div className="moviegrid-search-box">
                <span className="moviegrid-search-icon">🔍</span>
                <input
                  type="text"
                  placeholder="Rechercher un film..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="moviegrid-search-input"
                  autoFocus
                />
              </div>

              <div className="moviegrid-search-results">
                {searchLoading ? (
                  <div className="moviegrid-search-loading">Recherche en cours...</div>
                ) : searchResults.length > 0 ? (
                  <div className="moviegrid-results-list">
                    {searchResults.map((movie) => (
                      <button
                        key={movie.id}
                        onClick={() => handleMovieSelect(movie)}
                        className="moviegrid-result-item"
                      >
                        {movie.poster_path ? (
                          <img
                            src={`https://image.tmdb.org/t/p/w92${movie.poster_path}`}
                            alt={movie.title}
                            className="moviegrid-result-poster"
                          />
                        ) : (
                          <div className="moviegrid-result-no-poster">📽️</div>
                        )}
                        <div className="moviegrid-result-info">
                          <div className="moviegrid-result-title">{movie.title}</div>
                          <div className="moviegrid-result-year">
                            {movie.release_date ? new Date(movie.release_date).getFullYear() : 'N/A'}
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : searchQuery && !searchLoading ? (
                  <div className="moviegrid-search-loading">Aucun résultat trouvé</div>
                ) : null}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

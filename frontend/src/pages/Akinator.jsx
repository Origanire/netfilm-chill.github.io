import React, { useState, useEffect } from 'react';
import '../pages/Akinator.css';
import avatar from '../assets/logo.png';

const API_URL = 'http://localhost:5001/akinator';

export default function Akinator({ user }) {
  const [gameId, setGameId] = useState(null);
  const [questionKey, setQuestionKey] = useState(null);
  const [questionCount, setQuestionCount] = useState(0);

  const [question, setQuestion] = useState('');
  const [options, setOptions] = useState([]);
  const [finished, setFinished] = useState(false);
  const [guess, setGuess] = useState('');
  const [askingConfirmation, setAskingConfirmation] = useState(false);
  const [confirmationOptions, setConfirmationOptions] = useState([]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    startGame();
    // eslint-disable-next-line
  }, []);

  function parseError(data, res) {
    if (data && typeof data === 'object') {
      // backend renvoie "detail" si erreur interne
      if (data.detail) return String(data.detail);
      if (data.error) return String(data.error);
    }
    return `Erreur HTTP ${res.status}`;
  }

  function saveGameHistory(filmName, won, questionCount) {
    if (!user) return;
    
    const history = JSON.parse(localStorage.getItem('netfilm_game_history') || '[]');
    history.push({
      gameType: 'Akinator',
      guess: filmName,
      won: won === true || won === 'Oui, c\'est ça!',
      date: new Date().toISOString(),
      questions: questionCount,
    });
    
    // Keep only last 10 games
    localStorage.setItem('netfilm_game_history', JSON.stringify(history.slice(-10)));
  }

  function startGame() {
    setLoading(true);
    setError('');
    setQuestionCount(0);

    fetch(`${API_URL}/start`, { method: 'POST' })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(parseError(data, res));
        return data;
      })
      .then((data) => {
        setGameId(data.game_id || null);
        setQuestionKey(data.question_key || null);

        setQuestion(data.question || '');
        setOptions(Array.isArray(data.options) ? data.options : []);
        setAskingConfirmation(false);
        setConfirmationOptions([]);

        setFinished(false);
        setGuess('');
        setLoading(false);
      })
      .catch((e) => {
        console.error('startGame failed:', e);
        setError(e?.message || 'Internal error');
        setLoading(false);
      });
  }

  function handleAnswer(answer) {
    if (!gameId || !questionKey) return;

    setLoading(true);
    setError('');

    fetch(`${API_URL}/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        game_id: gameId,
        question_key: questionKey,
        answer,
      }),
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(parseError(data, res));
        return data;
      })
      .then((data) => {
        const newCount = questionCount + 1;
        setQuestionCount(newCount);

        if (data.finished) {
          setFinished(true);
          setGuess(data.guess || '');
          setAskingConfirmation(false);
          setLoading(false);
          // Save game history
          saveGameHistory(data.guess || '', true, newCount);
          return;
        }

        // Si demande de confirmation
        if (data.asking_confirmation) {
          setAskingConfirmation(true);
          setGuess(data.guess || '');
          setConfirmationOptions(Array.isArray(data.confirmation_options) ? data.confirmation_options : []);
          setQuestion('');
          setOptions([]);
          setLoading(false);
          return;
        }

        // Sinon, prochaine question
        setQuestion(data.question || '');
        setQuestionKey(data.question_key || null);
        setOptions(Array.isArray(data.options) ? data.options : []);
        setAskingConfirmation(false);
        setConfirmationOptions([]);

        setLoading(false);
      })
      .catch((e) => {
        console.error('answer failed:', e);
        setError(e?.message || 'Internal error');
        setLoading(false);
      });
  }

  function handleConfirm(confirmed) {
    if (!gameId) return;

    setLoading(true);
    setError('');

    fetch(`${API_URL}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        game_id: gameId,
        confirmed,
      }),
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(parseError(data, res));
        return data;
      })
      .then((data) => {
        if (data.finished) {
          setFinished(true);
          setGuess(data.guess || '');
          setAskingConfirmation(false);
          setLoading(false);
          // Save game history
          saveGameHistory(data.guess || '', confirmed, questionCount);
          return;
        }

        // Si demande de confirmation (nouveau film proposé)
        if (data.asking_confirmation) {
          setAskingConfirmation(true);
          setGuess(data.guess || '');
          setConfirmationOptions(Array.isArray(data.confirmation_options) ? data.confirmation_options : []);
          setQuestion('');
          setOptions([]);
          setLoading(false);
          return;
        }

        // Sinon, prochaine question
        setQuestion(data.question || '');
        setQuestionKey(data.question_key || null);
        setOptions(Array.isArray(data.options) ? data.options : []);
        setAskingConfirmation(false);
        setConfirmationOptions([]);

        setLoading(false);
      })
      .catch((e) => {
        console.error('confirm failed:', e);
        setError(e?.message || 'Internal error');
        setLoading(false);
      });
  }

  return (
    <div className="akinator-container">
      <header className="akinator-header"></header>

      <main className="akinator-main">
        <div className="akinator-avatar-box">
          <img src={avatar} alt="Akinator avatar" className="akinator-avatar" />
        </div>

        <div className="akinator-question-box">
          {loading ? (
            <div className="akinator-question">Chargement...</div>
          ) : error ? (
            <div className="akinator-result">
              <div className="akinator-question">{error}</div>
              <div className="akinator-result-actions">
                <button className="btn" onClick={startGame}>Réessayer</button>
              </div>
            </div>
          ) : askingConfirmation ? (
            <div className="akinator-result">
              <div className="akinator-question">
                Je pense à... <b>{guess}</b> !
              </div>
              <div className="akinator-answers">
                {confirmationOptions.map((opt) => (
                  <button
                    className="btn"
                    key={opt}
                    onClick={() => handleConfirm(opt === "Oui, c'est ça!")}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            </div>
          ) : !finished ? (
            <>
              <div className="akinator-question">{question}</div>
              <div className="akinator-answers">
                {options.map((opt) => (
                  <button className="btn" key={opt} onClick={() => handleAnswer(opt)}>
                    {opt}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <div className="akinator-result">
              <div className="akinator-question">
                Je pense à... <b>{guess}</b> !
              </div>
              <div className="akinator-result-actions">
                <button className="btn" onClick={startGame}>Rejouer</button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

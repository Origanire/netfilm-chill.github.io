import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import '../pages/Akinator.css';

// Charger automatiquement toutes les pistes depuis le dossier assets/soundtracks
const _soundModules = import.meta.glob('../assets/soundtracks/*.mp3', { eager: true, as: 'url' });
const SOUND_MAP = {};
const SOUND_URLS = [];
for (const p in _soundModules) {
  const file = p.split('/').pop();
  const key = `/assets/soundtracks/${file}`; // correspond au format renvoyé par le backend
  SOUND_MAP[key] = _soundModules[p];
  SOUND_URLS.push(_soundModules[p]);
}

export default function BlindTest() {
  const [question, setQuestion] = useState(null);
  const [audioUrl, setAudioUrl] = useState(null);
  const [difficulty, setDifficulty] = useState(null);
  const [answer, setAnswer] = useState('');
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  
  const audioRef = React.useRef(null);
  const inputRef = React.useRef(null);
  const feedbackRef = React.useRef(null);
  const [quizId, setQuizId] = useState(null);

  // Utiliser l'API exposée par `importFlask.py`
  const API_URL = 'http://localhost:5002/api';

  function startBlindTest() {
    // stop any playing sounds when starting a new quiz
    if (audioRef.current) { audioRef.current.pause(); audioRef.current.currentTime = 0; }
    if (feedbackRef.current) { feedbackRef.current.pause(); feedbackRef.current.currentTime = 0; feedbackRef.current = null; }
    setLoading(true);
    fetch(`${API_URL}/quiz/random`) // GET retourne { id, title, composer, year, difficulty }
      .then(res => res.json())
      .then(data => {
        const id = data.id;
        setQuizId(id);
        setQuestion(`Quel est le film correspondant à cette musique ?`);
        // Priorité: asset local si présent sinon tester le backend puis fallback
        const backendAudio = `${API_URL}/audio/${id}`;
        const localKey = `/assets/soundtracks/${id}.mp3`;
        const localUrl = SOUND_MAP[localKey] || null;
        if (localUrl) {
          setAudioUrl(localUrl);
          setTimeout(() => inputRef.current?.focus(), 200);
        } else {
          fetch(backendAudio, { method: 'HEAD' }).then(res => {
            if (res.ok) setAudioUrl(backendAudio);
            else if (SOUND_URLS.length) setAudioUrl(SOUND_URLS[Math.floor(Math.random() * SOUND_URLS.length)]);
            else setAudioUrl(backendAudio);
            setTimeout(() => inputRef.current?.focus(), 200);
          }).catch(() => {
            if (SOUND_URLS.length) setAudioUrl(SOUND_URLS[Math.floor(Math.random() * SOUND_URLS.length)]);
            else setAudioUrl(backendAudio);
            setTimeout(() => inputRef.current?.focus(), 200);
          });
        }
        // reset answer when new quiz starts
        setDifficulty(data.difficulty);
        setResult('');
        setAnswer('');
        setLoading(false);
      })
      .catch(err => {
        console.error('BlindTest: failed to start quiz', err);
        setLoading(false);
      });
  }

  function handleAnswerSubmit(e) {
    e.preventDefault();
    if (!quizId || !answer) return;
    // stop main audio immediately when validating
    if (audioRef.current) { audioRef.current.pause(); }
    // stop any feedback currently playing
    if (feedbackRef.current) { feedbackRef.current.pause(); feedbackRef.current.currentTime = 0; feedbackRef.current = null; }
    setLoading(true);
    fetch(`${API_URL}/quiz/${quizId}/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    })
      .then(res => res.json())
      .then(data => {
        if (data.correct !== undefined) {
          setResult(data.correct ? 'Bonne réponse !' : `Mauvaise réponse. La bonne réponse était : ${data.answer}`);
          // play feedback sound
          const fbKey = data.correct ? '/assets/soundtracks/yay.mp3' : '/assets/soundtracks/flop.mp3';
          const fbUrl = SOUND_MAP[fbKey] || null;
          if (fbUrl) {
            try {
              const fb = new Audio(fbUrl);
              feedbackRef.current = fb;
              fb.play().catch(() => {});
            } catch (err) {
              console.error('Feedback play failed', err);
            }
          }
        }
        setLoading(false);
      })
      .catch(err => {
        console.error('BlindTest: answer submit failed', err);
        setLoading(false);
      });
  }

  useEffect(() => {
    startBlindTest();
  }, []);

  // manage audio element when audioUrl changes
  useEffect(() => {
    // cleanup previous
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
    if (!audioUrl) return;
    const audio = new Audio(audioUrl);
    audioRef.current = audio;
    audio.addEventListener('timeupdate', () => setCurrentTime(audio.currentTime));
    audio.addEventListener('loadedmetadata', () => setDuration(audio.duration || 0));
    audio.addEventListener('ended', () => setIsPlaying(false));
    // do not show audio error message to user (autoplay policies may trigger harmless errors)
    // auto-play if possible
    audio.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
    return () => {
      if (audio) {
        audio.pause();
        audio.src = '';
      }
    };
  }, [audioUrl]);

  // helpers
  function togglePlay() {
    if (!audioRef.current) return;
    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
    }
  }

  function seekTo(value) {
    if (!audioRef.current) return;
    audioRef.current.currentTime = value;
    setCurrentTime(value);
  }

  function openModal() {
    // kept for compatibility if needed
  }

  function closeModal() {
    // kept for compatibility if needed
  }

  function submitModal(e) {
    // kept for compatibility if needed
  }

  return (
    <div className="akinator-container">
      <header className="akinator-header">
        {/* header intentionally empty: topbar brand handles home navigation */}
      </header>
      <main className="akinator-main">
        <div className="akinator-question-box">
          {loading ? (
            <div className="akinator-question">Chargement...</div>
          ) : result ? (
            <div className="akinator-result">
              <div className="akinator-question">{result}</div>
              <button className="btn" onClick={startBlindTest}>Question suivante</button>
            </div>
          ) : (
            <>
              <div className="akinator-question">{question}</div>
              {difficulty && (
                <div className="blindtest-difficulty">Difficulté : {difficulty}</div>
              )}
              {audioUrl && (
                <div style={{ margin: '20px 0', width: '100%' }}>
                  <div className="blindtest-player" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <button className="btn" onClick={togglePlay}>{isPlaying ? '⏸️ Pause' : '▶️ Play'}</button>
                    <div style={{ flex: 1 }}>
                      <input
                        type="range"
                        min={0}
                        max={duration || 0}
                        value={currentTime}
                        onChange={e => seekTo(Number(e.target.value))}
                        style={{ width: '100%' }}
                      />
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                        <div>{new Date((currentTime||0) * 1000).toISOString().substr(14, 5)}</div>
                        <div>{duration ? new Date(duration * 1000).toISOString().substr(14, 5) : '00:00'}</div>
                      </div>
                    </div>
                      {/* Inline answer input (directly editable) */}
                      <form onSubmit={handleAnswerSubmit} className="blindtest-form" style={{ marginTop: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
                        <input
                          type="text"
                          value={answer}
                          onChange={e => setAnswer(e.target.value)}
                          placeholder="Entrez le titre du film"
                          className="blindtest-input"
                          disabled={loading}
                          autoFocus
                          style={{ flex: 1, padding: '8px 10px' }}
                        />
                        <button className="btn" type="submit" disabled={loading || !answer}>Valider</button>
                      </form>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

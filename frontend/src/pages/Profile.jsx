import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/Profile.css'

export default function Profile({ user, onLogout }) {
  const navigate = useNavigate()
  const [gameHistory, setGameHistory] = useState([])

  useEffect(() => {
    const history = JSON.parse(localStorage.getItem('netfilm_game_history') || '[]')
    setGameHistory(history.reverse())
  }, [])

  const handleLogout = () => {
    onLogout()
    navigate('/')
  }

  const stats = {
    gamesPlayed: gameHistory.length,
    wins: gameHistory.filter(g => g.won).length,
    winRate: gameHistory.length > 0 ? Math.round((gameHistory.filter(g => g.won).length / gameHistory.length) * 100) : 0,
  }

  const formatDate = (isoString) => {
    const date = new Date(isoString)
    return date.toLocaleDateString('fr-FR', { 
      day: '2-digit', 
      month: '2-digit', 
      year: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  return (
    <div className="profile-container">
      <div className="profile-card">
        <div className="profile-header">
          <div className="profile-avatar">{user?.avatar || '👤'}</div>
          <div className="profile-info">
            <h1 className="profile-name">{user?.name || 'Joueur'}</h1>
            <p className="profile-email">{user?.email || 'email@example.com'}</p>
            <p className="profile-member">
              Membre depuis {new Date(user?.loginDate).toLocaleDateString('fr-FR')}
            </p>
          </div>
          <button className="profile-logout-btn" onClick={handleLogout}>
            Déconnexion
          </button>
        </div>

        <div className="profile-stats">
          <div className="stat-item">
            <div className="stat-number">{stats.gamesPlayed}</div>
            <div className="stat-label">Parties jouées</div>
          </div>
          <div className="stat-item">
            <div className="stat-number">{stats.wins}</div>
            <div className="stat-label">Films trouvés</div>
          </div>
          <div className="stat-item">
            <div className="stat-number">{stats.winRate}%</div>
            <div className="stat-label">Taux de réussite</div>
          </div>
        </div>

        <div className="profile-history">
          <h2 className="history-title">📽️ Historique des parties</h2>
          {gameHistory.length === 0 ? (
            <div className="history-empty">
              <p>Aucune partie jouée</p>
              <small>Commencez une partie pour voir votre historique ici</small>
            </div>
          ) : (
            <div className="history-list">
              {gameHistory.slice(0, 10).map((game, idx) => (
                <div key={idx} className={`history-item ${game.won ? 'won' : 'lost'}`}>
                  <div className="history-game-type">{game.gameType}</div>
                  <div className="history-content">
                    <div className="history-result">
                      {game.won ? '✅ Trouvé' : '❌ Raté'}: <b>{game.guess}</b>
                    </div>
                    <div className="history-date">{formatDate(game.date)}</div>
                  </div>
                  <div className="history-questions">{game.questions} Q</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

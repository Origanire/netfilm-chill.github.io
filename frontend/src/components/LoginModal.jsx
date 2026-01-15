import React from 'react'
import './LoginModal.css'

export default function LoginModal({ onLogin }) {
  const handleGoogleLogin = () => {
    // Mock Google login
    const mockUser = {
      id: Math.random().toString(36).substr(2, 9),
      name: 'Joueur Netflix',
      email: 'joueur@netfilm.fr',
      avatar: '👤',
      loginDate: new Date().toISOString(),
    }
    
    localStorage.setItem('netfilm_user', JSON.stringify(mockUser))
    onLogin(mockUser)
  }

  return (
    <div className="login-modal-overlay">
      <div className="login-modal">
        <div className="login-header">
          <h1 className="login-title">NetFilm & Chill</h1>
          <p className="login-subtitle">Bienvenue !</p>
        </div>

        <div className="login-content">
          <p className="login-description">
            Connectez-vous pour accéder à tous les jeux et suivre vos parties.
          </p>

          <button className="google-login-btn" onClick={handleGoogleLogin}>
            <span className="google-icon">🔐</span>
            <span>Se connecter avec Google</span>
          </button>

          <p className="login-footer">
            <em>Connexion simulée pour démonstration</em>
          </p>
        </div>
      </div>
    </div>
  )
}

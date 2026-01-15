import React, { useState, useEffect } from 'react'
import { Routes, Route, Link, useLocation } from 'react-router-dom'
import Home from './pages/Home'
import Akinator from './pages/Akinator'
import BlindTest from './pages/BlindTest'
import MovieGrid from './pages/MovieGrid'
import Profile from './pages/Profile'
import LoginModal from './components/LoginModal'
import ThemeSwitch from './components/ThemeSwitch'

export default function App() {
  const location = useLocation()
  const isHome = location.pathname === '/'
  const [user, setUser] = useState(null)

  // Load user from localStorage on mount
  useEffect(() => {
    const savedUser = localStorage.getItem('netfilm_user')
    if (savedUser) {
      try {
        setUser(JSON.parse(savedUser))
      } catch (e) {
        console.error('Error loading user:', e)
      }
    }
  }, [])

  const handleLogin = (userData) => {
    setUser(userData)
  }

  const handleLogout = () => {
    localStorage.removeItem('netfilm_user')
    localStorage.removeItem('netfilm_game_history')
    setUser(null)
  }

  // Show login modal if not authenticated
  if (!user) {
    return <LoginModal onLogin={handleLogin} />
  }

  return (
    <div className="app-root">
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand">
            <span className="brand-icon">🎯</span>
            NetFilm & Chill
          </Link>
          
          <div className="topbar-right">
            {!isHome && <Link to="/" className="btn btn-secondary">Accueil</Link>}
            {location.pathname !== '/profile' && (
              <Link to="/profile" className="btn btn-secondary">{user.name}</Link>
            )}
            <div className="theme-toggle-container">
              <ThemeSwitch />
            </div>
          </div>
        </div>
      </header>

      <main className="main-content">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/akinator" element={<Akinator user={user} />} />
          <Route path="/blindtest" element={<BlindTest />} />
          <Route path="/moviegrid" element={<MovieGrid />} />
          <Route path="/profile" element={<Profile user={user} onLogout={handleLogout} />} />
        </Routes>
      </main>

      <footer className="footer">
        <div className="footer-content">
          <p className="footer-copyright">Projet Week- Bousquet/Muzay/Kenzi/Bengana/Vitte/Mondoloni</p>
        </div>
      </footer>
    </div>
  )
}

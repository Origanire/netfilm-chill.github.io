import React from 'react'
import { Link } from 'react-router-dom'
import GameCard from '../components/GameCard'

export default function Home() {
  return (
    <div className="home-root fade-up">
      <section className="games-section">
        <h1 className="games-main-title">Jeux</h1>
        <div className="games-row">
          <GameCard
            title="Akinator"
            description="Le célèbre jeu qui devine à qui tu penses !"
            to="/akinator"
            icon={<span role="img" aria-label="Akinator">🔮</span>}
          />
          <GameCard
            title="BlindTest"
            description="Devine le film à partir de la bande-son !"
            to="/blindtest"
            icon={<span role="img" aria-label="BlindTest">🎧</span>}
          />
          <GameCard
            title="MovieGrid"
            description="Devinez les films par catégorie dans une grille 3x3 !"
            to="/moviegrid"
            icon={<span role="img" aria-label="MovieGrid">🎬</span>}
          />
          <div className="placeholder"></div>
        </div>
      </section>
    </div>
  )
}

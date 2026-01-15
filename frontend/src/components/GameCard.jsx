import React from 'react';
import { Link } from 'react-router-dom';

export default function GameCard({ title, description, to, icon, image }) {
  return (
    <Link to={to} className="game-card-link" tabIndex={0} style={{ textDecoration: 'none' }}>
      <div className="game-card fade-up" tabIndex={-1}>
        <div className="game-card-media">
          {image ? (
            <img src={image} alt={`${title} cover`} style={{ borderRadius: '12px 12px 0 0', boxShadow: '0 2px 12px rgba(108,99,255,0.10)' }} />
          ) : (
            <div className="game-card-media-title">{icon ? <span className="game-card-icon">{icon}</span> : title}</div>
          )}
        </div>
        <div className="game-card-body">
          <h3 className="game-card-title">{title}</h3>
          <p className="game-card-desc">{description}</p>
        </div>
      </div>
    </Link>
  );
}

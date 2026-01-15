import React from 'react';

export default function Guesser() {
  return (
    <div className="guesser-root fade-up" style={{ padding: '2.5rem 1.2rem', textAlign: 'center', minHeight: '60vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
      <h1 style={{ color: 'var(--accent)', fontWeight: 800, fontSize: '2.1rem', marginBottom: '1rem' }}>Guesser</h1>
      <p style={{ color: 'var(--muted)', fontSize: '1.15rem', maxWidth: 420 }}>Ce mode de jeu n'est pas encore disponible.<br/>Restez connectés pour les prochaines nouveautés !</p>
    </div>
  );
}

"use client";

import { useState } from "react";
import { useHeroes } from "@/lib/useHeroes";
import HeroSlot from "./HeroSlot";

type PredictResponse = {
  probability_radiant: number;
  probability_dire: number;
  predicted_winner: "radiant" | "dire";
  model_version: string;
};

export default function Home() {
  const { heroes, loading: heroesLoading, error: heroesError } = useHeroes();
  const [radiant, setRadiant] = useState<(number | null)[]>([null, null, null, null, null]);
  const [dire, setDire] = useState<(number | null)[]>([null, null, null, null, null]);
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const radiantComplete = radiant.every((h) => h !== null);
  const direComplete = dire.every((h) => h !== null);
  const canPredict = radiantComplete && direComplete;

  async function handlePredict() {
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const res = await fetch("/api/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          radiantHeroIds: radiant,
          direHeroIds: dire,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Error al predecir.");
      setResult(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const pctRadiant = result ? Math.round(result.probability_radiant * 100) : 50;

  return (
    <main className="page">
      <p className="eyebrow">Predictor · Torneos Tier 1</p>
      <h1 className="title">Sala de Draft</h1>
      <p className="subtitle">
        Elige los 5 héroes de cada bando y el modelo estima la probabilidad de
        victoria a partir de partidas profesionales tier 1 recientes.
      </p>

      {heroesError && (
        <div className="error-banner">No se pudo cargar el catálogo de héroes: {heroesError}</div>
      )}

      <datalist id="hero-options">
        {heroes.map((h) => (
          <option key={h.hero_id} value={h.localized_name} />
        ))}
      </datalist>

      <div className="draft-grid">
        <section className="team-panel radiant">
          <h2 className="team-header">Radiant</h2>
          {radiant.map((val, i) => (
            <HeroSlot
              key={i}
              index={i + 1}
              heroes={heroes}
              value={val}
              listId="hero-options"
              onChange={(id) =>
                setRadiant((prev) => prev.map((v, idx) => (idx === i ? id : v)))
              }
            />
          ))}
        </section>

        <div className="vs-divider">VS</div>

        <section className="team-panel dire">
          <h2 className="team-header">Dire</h2>
          {dire.map((val, i) => (
            <HeroSlot
              key={i}
              index={i + 1}
              heroes={heroes}
              value={val}
              listId="hero-options"
              onChange={(id) => setDire((prev) => prev.map((v, idx) => (idx === i ? id : v)))}
            />
          ))}
        </section>
      </div>

      <div className="predict-row">
        <button
          className="predict-button"
          disabled={!canPredict || loading || heroesLoading}
          onClick={handlePredict}
        >
          {loading ? "Calculando..." : "Predecir resultado"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {result && (
        <section className="result-panel">
          <div className="tug-bar">
            <div className="tug-bar-fill" style={{ width: `${pctRadiant}%` }} />
            <div className="tug-marker" style={{ left: `${pctRadiant}%` }} />
          </div>
          <div className="result-labels">
            <span>RADIANT {pctRadiant}%</span>
            <span>DIRE {100 - pctRadiant}%</span>
          </div>
          <p className="result-winner">
            Favorito: {result.predicted_winner === "radiant" ? "Radiant" : "Dire"}
          </p>
          <p className="result-meta">modelo {result.model_version}</p>
        </section>
      )}
    </main>
  );
}

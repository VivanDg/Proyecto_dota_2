"""
Entrena dos modelos sobre el mismo dataset (partidas tier 1, picks de héroes):

  1) Red neuronal con embeddings por héroe (modelo principal, sirve la
     probabilidad de victoria y de ahí se deriva la salida binaria).
  2) Gradient Boosting (LightGBM) sobre vectores multi-hot, como baseline
     interpretable (feature importance / SHAP) y control de calidad: si la
     red no supera al GBM, algo está mal en el entrenamiento.

Split temporal (no aleatorio): las partidas más recientes van a validación,
para simular el escenario real de "predecir partidas futuras con datos pasados"
y evitar fuga de información del meta.

Uso:
    python train.py --min-patch 7.33
"""
import argparse
import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score

from config import MIN_PATCH_NUMBER, RECENCY_HALF_LIFE_PATCHES, MODEL_DIR
from features import build_training_table
from supabase_client import get_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("train")


# ---------------------------------------------------------------------------
# Dataset -> tensores
# ---------------------------------------------------------------------------

def build_hero_index(df: pd.DataFrame) -> dict[int, int]:
    all_heroes = sorted({h for row in df["radiant_heroes"] for h in row} |
                         {h for row in df["dire_heroes"] for h in row})
    return {hero_id: idx for idx, hero_id in enumerate(all_heroes)}


def recency_weights(patch_numbers: pd.Series, half_life: float) -> np.ndarray:
    """Peso exponencial: las partidas del parche más reciente pesan más.
    half_life = cuántos "parches atrás" hacen que el peso caiga a la mitad."""
    max_patch = patch_numbers.astype(float).max()
    delta = max_patch - patch_numbers.astype(float)
    return np.power(0.5, delta / max(half_life, 0.1))


def to_index_tensor(hero_lists: pd.Series, hero_index: dict[int, int]) -> torch.Tensor:
    arr = np.array([[hero_index[h] for h in heroes] for heroes in hero_lists])
    return torch.tensor(arr, dtype=torch.long)


def to_multi_hot(hero_lists: pd.Series, num_heroes: int, hero_index: dict[int, int]) -> np.ndarray:
    out = np.zeros((len(hero_lists), num_heroes), dtype=np.float32)
    for i, heroes in enumerate(hero_lists):
        for h in heroes:
            out[i, hero_index[h]] = 1.0
    return out


# ---------------------------------------------------------------------------
# Modelo: red con embeddings de héroe
# ---------------------------------------------------------------------------

class HeroWinPredictor(nn.Module):
    def __init__(self, num_heroes: int, embed_dim: int = 24, hidden: int = 64):
        super().__init__()
        self.embedding = nn.Embedding(num_heroes, embed_dim)
        # team_pool: suma de embeddings del equipo (invariante al orden de picks)
        self.net = nn.Sequential(
            nn.Linear(embed_dim * 3, hidden),   # [radiant_pool, dire_pool, diff]
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
            nn.Linear(hidden // 2, 1),
        )

    def forward(self, radiant_idx: torch.Tensor, dire_idx: torch.Tensor) -> torch.Tensor:
        radiant_pool = self.embedding(radiant_idx).sum(dim=1)   # (batch, embed_dim)
        dire_pool = self.embedding(dire_idx).sum(dim=1)
        diff = radiant_pool - dire_pool
        x = torch.cat([radiant_pool, dire_pool, diff], dim=1)
        logit = self.net(x).squeeze(-1)
        return logit  # sin sigmoid: usamos BCEWithLogitsLoss


def train_neural_net(train_df, val_df, hero_index, sample_weights, epochs=40, lr=1e-3):
    num_heroes = len(hero_index)
    model = HeroWinPredictor(num_heroes=num_heroes)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    loss_fn = nn.BCEWithLogitsLoss(reduction="none")

    r_train = to_index_tensor(train_df["radiant_heroes"], hero_index)
    d_train = to_index_tensor(train_df["dire_heroes"], hero_index)
    y_train = torch.tensor(train_df["radiant_win"].astype(float).values, dtype=torch.float32)
    w_train = torch.tensor(sample_weights, dtype=torch.float32)

    r_val = to_index_tensor(val_df["radiant_heroes"], hero_index)
    d_val = to_index_tensor(val_df["dire_heroes"], hero_index)
    y_val = val_df["radiant_win"].astype(float).values

    best_val_loss = float("inf")
    best_state = None
    patience, bad_epochs = 6, 0

    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        logits = model(r_train, d_train)
        loss = (loss_fn(logits, y_train) * w_train).mean()
        loss.backward()
        optimizer.step()

        model.eval()
        with torch.no_grad():
            val_logits = model(r_val, d_val)
            val_probs = torch.sigmoid(val_logits).numpy()
            val_loss = log_loss(y_val, val_probs, labels=[0, 1])

        log.info(f"  epoch {epoch:02d}  train_loss={loss.item():.4f}  val_log_loss={val_loss:.4f}")

        if val_loss < best_val_loss - 1e-4:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                log.info("  early stopping.")
                break

    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        val_probs = torch.sigmoid(model(r_val, d_val)).numpy()

    metrics = {
        "log_loss": float(log_loss(y_val, val_probs, labels=[0, 1])),
        "accuracy": float(accuracy_score(y_val, val_probs > 0.5)),
        "auc": float(roc_auc_score(y_val, val_probs)),
    }
    return model, metrics


def train_gbm_baseline(train_df, val_df, hero_index):
    import lightgbm as lgb

    num_heroes = len(hero_index)
    X_train = np.concatenate([
        to_multi_hot(train_df["radiant_heroes"], num_heroes, hero_index),
        to_multi_hot(train_df["dire_heroes"], num_heroes, hero_index),
    ], axis=1)
    X_val = np.concatenate([
        to_multi_hot(val_df["radiant_heroes"], num_heroes, hero_index),
        to_multi_hot(val_df["dire_heroes"], num_heroes, hero_index),
    ], axis=1)
    y_train = train_df["radiant_win"].astype(int).values
    y_val = val_df["radiant_win"].astype(int).values

    clf = lgb.LGBMClassifier(n_estimators=300, max_depth=5, learning_rate=0.05)
    clf.fit(X_train, y_train)
    probs = clf.predict_proba(X_val)[:, 1]

    metrics = {
        "log_loss": float(log_loss(y_val, probs, labels=[0, 1])),
        "accuracy": float(accuracy_score(y_val, probs > 0.5)),
        "auc": float(roc_auc_score(y_val, probs)),
    }
    return clf, metrics


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-patch", default=MIN_PATCH_NUMBER)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    args = parser.parse_args()

    log.info("Cargando dataset de entrenamiento desde Supabase...")
    df = build_training_table(min_patch=args.min_patch)
    df = df.sort_values("start_time").reset_index(drop=True)
    log.info(f"  {len(df)} partidas cargadas (parche >= {args.min_patch}).")

    if len(df) < 500:
        log.warning(
            "Menos de 500 partidas disponibles. El modelo probablemente estará "
            "sobreajustado. Considera bajar --min-patch o esperar más datos."
        )

    split_idx = int(len(df) * (1 - args.val_fraction))
    train_df, val_df = df.iloc[:split_idx], df.iloc[split_idx:]

    hero_index = build_hero_index(df)
    weights = recency_weights(train_df["patch_number"], RECENCY_HALF_LIFE_PATCHES)

    log.info("Entrenando baseline GBM...")
    gbm_model, gbm_metrics = train_gbm_baseline(train_df, val_df, hero_index)
    log.info(f"  GBM metrics: {gbm_metrics}")

    log.info("Entrenando red neuronal...")
    nn_model, nn_metrics = train_neural_net(train_df, val_df, hero_index, weights)
    log.info(f"  NN metrics: {nn_metrics}")

    if nn_metrics["log_loss"] > gbm_metrics["log_loss"]:
        log.warning(
            "La red neuronal NO superó al baseline GBM en log_loss. "
            "Se guardan ambos modelos igual, pero revisa hiperparámetros "
            "o cantidad de datos antes de promover la red a producción."
        )

    version = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    save_artifacts(nn_model, gbm_model, hero_index, nn_metrics, gbm_metrics,
                    version, args.min_patch, df)


def save_artifacts(nn_model, gbm_model, hero_index, nn_metrics, gbm_metrics,
                    version, min_patch, df):
    import os
    import joblib

    os.makedirs(MODEL_DIR, exist_ok=True)
    run_dir = os.path.join(MODEL_DIR, version)
    os.makedirs(run_dir, exist_ok=True)

    torch.save(nn_model.state_dict(), os.path.join(run_dir, "nn_model.pt"))
    joblib.dump(gbm_model, os.path.join(run_dir, "gbm_model.joblib"))

    metadata = {
        "version": version,
        "hero_index": hero_index,          # hero_id -> índice de embedding
        "num_heroes": len(hero_index),
        "min_patch": min_patch,
        "max_patch": df["patch_number"].max(),
        "train_rows": len(df),
        "nn_metrics": nn_metrics,
        "gbm_metrics": gbm_metrics,
    }
    with open(os.path.join(run_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    log.info(f"Artefactos guardados en {run_dir}")
    log.info("Siguiente paso: python export_onnx.py --run-dir " + run_dir)

    # Registrar el intento de entrenamiento en Supabase (sin activarlo todavía;
    # export_onnx.py es quien lo marca is_active tras subir el .onnx)
    client = get_client()
    client.table("model_registry").insert({
        "version": version,
        "model_type": "neural_net",
        "patch_range_min": min_patch,
        "patch_range_max": str(df["patch_number"].max()),
        "tier_filter": ["premium", "professional"],
        "train_rows": len(df),
        "val_rows": int(len(df) * 0.15),
        "metrics": nn_metrics,
        "storage_path": None,
        "is_active": False,
    }).execute()


if __name__ == "__main__":
    main()

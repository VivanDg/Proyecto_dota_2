"""
Exporta el modelo entrenado (nn_model.pt) a ONNX, lo sube al bucket "models"
de Supabase Storage, y lo marca como activo SOLO si su log_loss de validación
es mejor que el del modelo actualmente activo (o si no hay ninguno todavía).

Esto evita que un reentrenamiento con datos ruidosos degrade lo que está
sirviendo la API en producción.

Uso:
    python export_onnx.py --run-dir ./models/2026-07-18T0000Z
"""
import argparse
import json
import logging
import os

import torch

from train import HeroWinPredictor
from supabase_client import get_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export_onnx")

BUCKET = "models"


def load_metadata(run_dir: str) -> dict:
    with open(os.path.join(run_dir, "metadata.json")) as f:
        return json.load(f)


def export_to_onnx(run_dir: str, metadata: dict) -> str:
    num_heroes = metadata["num_heroes"]
    model = HeroWinPredictor(num_heroes=num_heroes)
    model.load_state_dict(torch.load(os.path.join(run_dir, "nn_model.pt")))
    model.eval()

    dummy_radiant = torch.zeros((1, 5), dtype=torch.long)
    dummy_dire = torch.zeros((1, 5), dtype=torch.long)

    onnx_path = os.path.join(run_dir, "model.onnx")
    torch.onnx.export(
        model,
        (dummy_radiant, dummy_dire),
        onnx_path,
        input_names=["radiant_hero_idx", "dire_hero_idx"],
        output_names=["win_logit"],
        dynamic_axes={
            "radiant_hero_idx": {0: "batch"},
            "dire_hero_idx": {0: "batch"},
            "win_logit": {0: "batch"},
        },
        opset_version=17,
    )
    log.info(f"Modelo exportado a {onnx_path}")
    return onnx_path


def get_active_model_metrics(model_type: str = "neural_net") -> dict | None:
    client = get_client()
    res = (
        client.table("model_registry")
        .select("*")
        .eq("model_type", model_type)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def promote_model(version: str, onnx_path: str, metadata: dict):
    client = get_client()

    # 1. Subir el .onnx y el mapeo hero_id -> índice (necesario para inferencia)
    storage_path = f"{version}/model.onnx"
    with open(onnx_path, "rb") as f:
        client.storage.from_(BUCKET).upload(
            storage_path, f, {"content-type": "application/octet-stream", "upsert": "true"}
        )

    hero_index_path = f"{version}/hero_index.json"
    client.storage.from_(BUCKET).upload(
        hero_index_path,
        json.dumps(metadata["hero_index"]).encode("utf-8"),
        {"content-type": "application/json", "upsert": "true"},
    )

    # 2. Desactivar el modelo anterior y activar el nuevo (transacción lógica)
    client.table("model_registry").update({"is_active": False}) \
        .eq("model_type", "neural_net").eq("is_active", True).execute()

    client.table("model_registry").update({
        "storage_path": storage_path,
        "is_active": True,
    }).eq("version", version).execute()

    log.info(f"Modelo {version} promovido a producción ({storage_path}).")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--force", action="store_true",
                         help="Promover el modelo aunque no mejore al activo.")
    args = parser.parse_args()

    metadata = load_metadata(args.run_dir)
    onnx_path = export_to_onnx(args.run_dir, metadata)

    active = get_active_model_metrics()
    new_log_loss = metadata["nn_metrics"]["log_loss"]

    if active is None:
        log.info("No hay modelo activo todavía. Promoviendo el nuevo directamente.")
        promote_model(metadata["version"], onnx_path, metadata)
        return

    active_log_loss = active["metrics"]["log_loss"]
    log.info(f"Modelo activo actual: log_loss={active_log_loss:.4f} | "
              f"Nuevo modelo: log_loss={new_log_loss:.4f}")

    if new_log_loss < active_log_loss or args.force:
        promote_model(metadata["version"], onnx_path, metadata)
    else:
        log.warning(
            "El nuevo modelo NO mejora al activo. No se promueve. "
            "Usa --force si quieres promoverlo de todas formas."
        )


if __name__ == "__main__":
    main()

import * as ort from "onnxruntime-node";
import { supabaseAdmin } from "./supabaseAdmin";

type LoadedModel = {
  session: ort.InferenceSession;
  heroIndex: Record<string, number>;
  version: string;
};

// Cache en memoria del proceso serverless. Sobrevive entre invocaciones
// mientras la instancia siga "tibia" (comportamiento normal de Vercel/Lambda).
// Evita re-descargar el modelo en cada request.
let cached: LoadedModel | null = null;
let cachedAt = 0;
const CACHE_TTL_MS = 10 * 60 * 1000; // revisa si hay modelo nuevo cada 10 min

async function fetchActiveModelMeta() {
  const { data, error } = await supabaseAdmin
    .from("model_registry")
    .select("version, storage_path")
    .eq("model_type", "neural_net")
    .eq("is_active", true)
    .single();

  if (error || !data || !data.storage_path) {
    throw new Error(
      "No hay ningún modelo activo en model_registry. Corre el pipeline de " +
        "entrenamiento (data-pipeline/train.py + export_onnx.py) primero."
    );
  }
  return data as { version: string; storage_path: string };
}

async function downloadFromStorage(path: string): Promise<Buffer> {
  const { data, error } = await supabaseAdmin.storage.from("models").download(path);
  if (error || !data) {
    throw new Error(`No se pudo descargar ${path} de Supabase Storage: ${error?.message}`);
  }
  return Buffer.from(await data.arrayBuffer());
}

export async function getActiveModel(): Promise<LoadedModel> {
  const now = Date.now();
  if (cached && now - cachedAt < CACHE_TTL_MS) {
    return cached;
  }

  const meta = await fetchActiveModelMeta();

  // Evitar recargar si sigue siendo la misma versión que ya teníamos cacheada
  if (cached && cached.version === meta.version) {
    cachedAt = now;
    return cached;
  }

  const modelDir = meta.storage_path.split("/")[0]; // ej: "2026-07-18T0000Z"
  const [onnxBuffer, heroIndexBuffer] = await Promise.all([
    downloadFromStorage(meta.storage_path),
    downloadFromStorage(`${modelDir}/hero_index.json`),
  ]);

  const session = await ort.InferenceSession.create(onnxBuffer);
  const heroIndex = JSON.parse(heroIndexBuffer.toString("utf-8"));

  cached = { session, heroIndex, version: meta.version };
  cachedAt = now;
  return cached;
}

export type PredictionResult = {
  probabilityRadiant: number;
  predictedWinner: "radiant" | "dire";
  modelVersion: string;
};

export async function predictWinner(
  radiantHeroIds: number[],
  direHeroIds: number[]
): Promise<PredictionResult> {
  if (radiantHeroIds.length !== 5 || direHeroIds.length !== 5) {
    throw new Error("Cada equipo debe tener exactamente 5 héroes.");
  }

  const { session, heroIndex, version } = await getActiveModel();

  const mapToIdx = (ids: number[]) =>
    ids.map((id) => {
      const idx = heroIndex[String(id)];
      if (idx === undefined) {
        throw new Error(
          `El héroe con id ${id} no estaba en los datos de entrenamiento del ` +
            `modelo activo (${version}). Puede ser un héroe nuevo aún sin partidas tier 1.`
        );
      }
      return idx;
    });

  const radiantTensor = new ort.Tensor(
    "int64",
    BigInt64Array.from(mapToIdx(radiantHeroIds).map(BigInt)),
    [1, 5]
  );
  const direTensor = new ort.Tensor(
    "int64",
    BigInt64Array.from(mapToIdx(direHeroIds).map(BigInt)),
    [1, 5]
  );

  const output = await session.run({
    radiant_hero_idx: radiantTensor,
    dire_hero_idx: direTensor,
  });

  const logit = (output.win_logit.data as Float32Array)[0];
  const probabilityRadiant = 1 / (1 + Math.exp(-logit));

  return {
    probabilityRadiant,
    predictedWinner: probabilityRadiant >= 0.5 ? "radiant" : "dire",
    modelVersion: version,
  };
}

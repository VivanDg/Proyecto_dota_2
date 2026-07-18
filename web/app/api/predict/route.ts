import { NextRequest, NextResponse } from "next/server";
import { predictWinner } from "@/lib/inference";
import { supabaseAdmin } from "@/lib/supabaseAdmin";

// Necesita el runtime de Node (no Edge) porque onnxruntime-node usa binarios nativos.
export const runtime = "nodejs";

type PredictBody = {
  radiantHeroIds: number[];
  direHeroIds: number[];
};

export async function POST(req: NextRequest) {
  let body: PredictBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "JSON inválido." }, { status: 400 });
  }

  const { radiantHeroIds, direHeroIds } = body;

  if (
    !Array.isArray(radiantHeroIds) ||
    !Array.isArray(direHeroIds) ||
    radiantHeroIds.length !== 5 ||
    direHeroIds.length !== 5
  ) {
    return NextResponse.json(
      { error: "Se requieren exactamente 5 hero_id para radiant y 5 para dire." },
      { status: 400 }
    );
  }

  const overlap = radiantHeroIds.filter((id) => direHeroIds.includes(id));
  if (overlap.length > 0) {
    return NextResponse.json(
      { error: `Los héroes ${overlap.join(", ")} no pueden estar en ambos equipos.` },
      { status: 400 }
    );
  }

  try {
    const result = await predictWinner(radiantHeroIds, direHeroIds);

    // Log de la predicción para poder medir drift más adelante (fire-and-forget:
    // no bloquea la respuesta ni la hace fallar si el log falla).
    logPrediction(req, radiantHeroIds, direHeroIds, result);

    return NextResponse.json({
      probability_radiant: result.probabilityRadiant,
      probability_dire: 1 - result.probabilityRadiant,
      predicted_winner: result.predictedWinner,
      model_version: result.modelVersion,
    });
  } catch (err: any) {
    return NextResponse.json({ error: err.message ?? "Error interno." }, { status: 500 });
  }
}

async function logPrediction(
  req: NextRequest,
  radiantHeroIds: number[],
  direHeroIds: number[],
  result: { probabilityRadiant: number; predictedWinner: "radiant" | "dire"; modelVersion: string }
) {
  try {
    await supabaseAdmin.from("predictions_log").insert({
      radiant_hero_ids: radiantHeroIds,
      dire_hero_ids: direHeroIds,
      predicted_prob_radiant: result.probabilityRadiant,
      predicted_winner: result.predictedWinner,
      model_version: result.modelVersion,
      client_ip: req.headers.get("x-forwarded-for") ?? null,
    });
  } catch {
    // No queremos que un fallo de logging tumbe la respuesta de predicción.
  }
}

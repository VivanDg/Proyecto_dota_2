import { createClient } from "@supabase/supabase-js";

// SOLO se importa desde código que corre en el servidor (API routes).
// Nunca importar este archivo desde un componente cliente ("use client"),
// porque expondría la service_role key en el bundle del navegador.
export const supabaseAdmin = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_KEY!,
  { auth: { persistSession: false } }
);

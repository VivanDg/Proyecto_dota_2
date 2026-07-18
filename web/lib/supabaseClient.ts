import { createClient } from "@supabase/supabase-js";

// Clave pública (anon) — solo debe tener permisos de LECTURA sobre
// tablas públicas como "heroes" y "hero_meta_by_patch" (configura Row
// Level Security en Supabase para restringir todo lo demás).
export const supabaseBrowser = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

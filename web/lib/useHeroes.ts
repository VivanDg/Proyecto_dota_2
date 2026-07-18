"use client";

import { useEffect, useState } from "react";
import { supabaseBrowser } from "./supabaseClient";

export type Hero = {
  hero_id: number;
  localized_name: string;
};

export function useHeroes() {
  const [heroes, setHeroes] = useState<Hero[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    supabaseBrowser
      .from("heroes")
      .select("hero_id, localized_name")
      .order("localized_name")
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) setError(error.message);
        else setHeroes(data ?? []);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { heroes, loading, error };
}

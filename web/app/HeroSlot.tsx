"use client";

import { Hero } from "@/lib/useHeroes";

type Props = {
  index: number;
  heroes: Hero[];
  value: number | null;
  onChange: (heroId: number | null) => void;
  listId: string;
};

export default function HeroSlot({ index, heroes, value, onChange, listId }: Props) {
  const selected = heroes.find((h) => h.hero_id === value);

  function handleInput(text: string) {
    const match = heroes.find(
      (h) => h.localized_name.toLowerCase() === text.trim().toLowerCase()
    );
    onChange(match ? match.hero_id : null);
  }

  return (
    <div className="hero-slot">
      <span className="slot-index">{index}</span>
      <input
        list={listId}
        placeholder="Buscar héroe..."
        defaultValue={selected?.localized_name ?? ""}
        onChange={(e) => handleInput(e.target.value)}
        autoComplete="off"
      />
    </div>
  );
}

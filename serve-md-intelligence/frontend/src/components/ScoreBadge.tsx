import { fmtScore, scoreColor } from "../lib/format";

export default function ScoreBadge({ score, size = "md" }: { score: number | null | undefined; size?: "md" | "lg" }) {
  const cls = size === "lg" ? "h-20 w-20 text-3xl" : "h-8 w-12 text-sm";
  return (
    <div
      className={`flex items-center justify-center rounded-lg font-bold text-white ${cls}`}
      style={{ background: scoreColor(score) }}
      title="SERVE MD Score (0-100)"
    >
      {fmtScore(score)}
    </div>
  );
}

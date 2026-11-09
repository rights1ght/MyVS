import { useId } from "react";

export function Sparkline({
  values,
  color = "var(--accent)",
  height = 56,
  max,
  fill = true,
}: {
  values: number[];
  color?: string;
  height?: number;
  max?: number;
  fill?: boolean;
}) {
  const id = useId().replace(/:/g, "");
  const width = 320;
  if (!values.length) {
    return <div className="h-14 rounded-lg border border-dashed border-[var(--border)]" />;
  }
  const upper = max ?? Math.max(...values, 1);
  const points = values.map((value, index) => {
    const x = (index / Math.max(values.length - 1, 1)) * width;
    const y = height - (Math.max(0, value) / upper) * (height - 6) - 3;
    return [x, y] as const;
  });
  const line = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `0,${height} ${line} ${width},${height}`;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-14 w-full" preserveAspectRatio="none" role="img" aria-label="график">
      <defs>
        <linearGradient id={`spark-${id}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <polygon points={area} fill={`url(#spark-${id})`} />}
      <polyline points={line} fill="none" stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

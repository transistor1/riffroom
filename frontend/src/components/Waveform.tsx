export default function Waveform({
  peaks,
  color = "#708078",
  progress = 0,
  beats = [],
  duration = 0,
}: {
  peaks: number[];
  color?: string;
  progress?: number;
  beats?: number[];
  duration?: number;
}) {
  // One marker per two viewBox units, retaining accents when ticks collide.
  const ticks = new Map<number, boolean>();
  if (duration > 0) beats.forEach((beat, i) => {
    const x = Math.round(beat / duration * 300) * 2;
    if (x >= 0 && x <= 600) ticks.set(x, !!ticks.get(x) || i % 4 === 0);
  });
  return (
    <svg viewBox="0 0 600 52" preserveAspectRatio="none" aria-hidden="true">
      {peaks.map((v, i) => (
        <line
          key={i}
          x1={(i * 600) / peaks.length}
          x2={(i * 600) / peaks.length}
          y1={26 - Math.max(1, v * 24)}
          y2={26 + Math.max(1, v * 24)}
          stroke={color}
          strokeWidth="1.5"
          opacity={i / peaks.length < progress ? 1 : 0.4}
        />
      ))}
      {[...ticks].map(([x, accent]) => (
        <line key={`beat-${x}`} x1={x} x2={x} y1={0} y2={accent ? 13 : 7}
          stroke={color} strokeWidth={accent ? 1.5 : 1} opacity={accent ? 0.9 : 0.45} />
      ))}
    </svg>
  );
}

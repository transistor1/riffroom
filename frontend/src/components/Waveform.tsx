export default function Waveform({
  peaks,
  color = "#708078",
  progress = 0,
}: {
  peaks: number[];
  color?: string;
  progress?: number;
}) {
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
    </svg>
  );
}

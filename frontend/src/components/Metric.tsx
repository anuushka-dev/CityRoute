export function Metric({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="metric-block">
      <span className="metric-label">{label}</span>
      <strong className={mono ? 'metric-value metric-mono' : 'metric-value'}>{value}</strong>
    </div>
  );
}

interface StatusBadgeProps {
  ready: boolean | null;
}

export function StatusBadge({ ready }: StatusBadgeProps) {
  if (ready === null) {
    return <span className="status-badge status-badge-neutral">Checking</span>;
  }

  return (
    <span className={`status-badge ${ready ? 'status-badge-ready' : 'status-badge-error'}`}>
      <span className="status-dot" aria-hidden="true" />
      {ready ? 'Backend ready' : 'Backend unavailable'}
    </span>
  );
}

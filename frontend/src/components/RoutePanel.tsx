import type { Coordinate, RouteComparisonResponse } from '../types/domain';
import { formatDistance, formatDuration, formatMilliseconds } from '../utils/format';

interface RoutePanelProps {
  start: Coordinate | null;
  end: Coordinate | null;
  onChooseStart: () => void;
  onChooseEnd: () => void;
  onRoute: () => void;
  onCompare: () => void;
  loading: boolean;
  comparing: boolean;
  error: string | null;
  compareError: string | null;
  distanceMeters: number | null;
  etaSeconds: number | null;
  comparison: RouteComparisonResponse | null;
}

function CoordinateLine({ coordinate }: { coordinate: Coordinate | null }) {
  if (!coordinate) {
    return <span className="muted-value">Choose on map</span>;
  }

  return <span className="mono-value">{coordinate.lat.toFixed(5)}, {coordinate.lon.toFixed(5)}</span>;
}

export function RoutePanel({
  start,
  end,
  onChooseStart,
  onChooseEnd,
  onRoute,
  onCompare,
  loading,
  comparing,
  error,
  compareError,
  distanceMeters,
  etaSeconds,
  comparison,
}: RoutePanelProps) {
  const canRoute = Boolean(start && end) && !loading;
  const canCompare = Boolean(start && end) && !loading && !comparing;

  return (
    <div className="panel-stack">
      <div>
        <p className="eyebrow">Point-to-point routing</p>
        <h2 className="panel-title">Find a road route</h2>
        <p className="panel-copy">Use the loaded road graph, node snapping, A* routing and ETA estimation.</p>
      </div>

      <div className="location-list">
        <button className="location-row" type="button" onClick={onChooseStart}>
          <span className="location-marker location-marker-start" />
          <span className="location-content">
            <span className="location-label">Start</span>
            <CoordinateLine coordinate={start} />
          </span>
        </button>

        <button className="location-row" type="button" onClick={onChooseEnd}>
          <span className="location-marker location-marker-end" />
          <span className="location-content">
            <span className="location-label">Destination</span>
            <CoordinateLine coordinate={end} />
          </span>
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}
      {compareError && <div className="error-box">{compareError}</div>}

      <div className="panel-actions">
        <button className="primary-button" type="button" onClick={onRoute} disabled={!canRoute}>
          {loading ? 'Routing…' : 'Calculate route'}
        </button>
        <button className="secondary-button" type="button" onClick={onCompare} disabled={!canCompare}>
          {comparing ? 'Comparing…' : 'Compare A* / Bi-A*'}
        </button>
      </div>

      {(distanceMeters !== null || etaSeconds !== null) && (
        <div className="result-card result-card-grid">
          <Metric label="Road distance" value={distanceMeters === null ? '—' : formatDistance(distanceMeters)} />
          <Metric label="ETA" value={etaSeconds === null ? '—' : formatDuration(etaSeconds)} />
        </div>
      )}

      {comparison && (
        <section className="technical-result">
          <div className="result-section-heading">
            <span>Routing comparison</span>
            <span className="result-chip">same road result: {comparison.comparison.same_distance ? 'yes' : 'no'}</span>
          </div>
          <div className="comparison-grid">
            <AlgorithmCard
              title="A*"
              time={comparison.astar.route_time_ms}
              nodes={comparison.astar.nodes_expanded}
            />
            <AlgorithmCard
              title="Bidirectional A*"
              time={comparison.bidirectional_astar.route_time_ms}
              nodes={comparison.bidirectional_astar.nodes_expanded}
            />
          </div>
          <div className="result-footnote">
            {comparison.comparison.bidirectional_faster
              ? `${comparison.comparison.route_time_reduction_pct.toFixed(1)}% lower route time with Bidirectional A*.`
              : 'This query did not make Bidirectional A* faster.'}
            {' '}
            Comparison execution: {formatMilliseconds(comparison.compare_total_time_ms)}.
          </div>
        </section>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="result-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AlgorithmCard({ title, time, nodes }: { title: string; time: number; nodes: number }) {
  return (
    <div className="algorithm-card">
      <strong>{title}</strong>
      <span>{formatMilliseconds(time)}</span>
      <span>{nodes.toLocaleString()} nodes expanded</span>
    </div>
  );
}

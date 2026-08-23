import type { Coordinate, VrpStrategy } from '../types/domain';
import { formatDistance, formatMilliseconds } from '../utils/format';

interface StopsPanelProps {
  start: Coordinate | null;
  stops: Coordinate[];
  strategy: VrpStrategy;
  matrixAlgorithm: 'source_dijkstra' | 'bidirectional_astar';
  useCache: boolean;
  returnToStart: boolean;
  onStrategyChange: (value: VrpStrategy) => void;
  onMatrixAlgorithmChange: (value: 'source_dijkstra' | 'bidirectional_astar') => void;
  onUseCacheChange: (value: boolean) => void;
  onReturnToStartChange: (value: boolean) => void;
  onChooseStart: () => void;
  onAddStop: () => void;
  onOptimize: () => void;
  onRemoveStop: (index: number) => void;
  onClear: () => void;
  loading: boolean;
  error: string | null;
  optimizedOrder: number[];
  totalDistanceMeters: number | null;
  optimizationTimeMs: number | null;
  matrixTimeMs: number | null;
  cacheStatus: string | null;
  twoOptDistanceMeters: number | null;
  twoOptImprovementPct: number | null;
  lnsDistanceMeters: number | null;
  lnsImprovementPct: number | null;
  selectedResult: VrpStrategy | null;
  onSelectResult: (strategy: VrpStrategy) => void;
}

export function StopsPanel({
  start,
  stops,
  strategy,
  matrixAlgorithm,
  useCache,
  returnToStart,
  onStrategyChange,
  onMatrixAlgorithmChange,
  onUseCacheChange,
  onReturnToStartChange,
  onChooseStart,
  onAddStop,
  onOptimize,
  onRemoveStop,
  onClear,
  loading,
  error,
  optimizedOrder,
  totalDistanceMeters,
  optimizationTimeMs,
  matrixTimeMs,
  cacheStatus,
  twoOptDistanceMeters,
  twoOptImprovementPct,
  lnsDistanceMeters,
  lnsImprovementPct,
  selectedResult,
  onSelectResult,
}: StopsPanelProps) {
  const canOptimize = Boolean(start) && stops.length > 0 && !loading;

  return (
    <div className="panel-stack">
      <div>
        <p className="eyebrow">Delivery optimization</p>
        <h2 className="panel-title">Build a multi-stop run</h2>
        <p className="panel-copy">The backend can expose the greedy baseline, 2-Opt comparison, and LNS pipeline.</p>
      </div>

      <button className="location-row" type="button" onClick={onChooseStart}>
        <span className="location-marker location-marker-start" />
        <span className="location-content">
          <span className="location-label">Depot / Start</span>
          <span className="mono-value">{start ? `${start.lat.toFixed(5)}, ${start.lon.toFixed(5)}` : 'Choose on map'}</span>
        </span>
      </button>

      <div className="stops-list">
        {stops.map((stop, index) => (
          <div className="stop-row" key={`${stop.lat}-${stop.lon}-${index}`}>
            <span className="stop-number">{index + 1}</span>
            <span className="location-content">
              <span className="location-label">Stop {index + 1}</span>
              <span className="mono-value">{stop.lat.toFixed(5)}, {stop.lon.toFixed(5)}</span>
            </span>
            <button className="icon-button" type="button" onClick={() => onRemoveStop(index)} aria-label={`Remove stop ${index + 1}`}>×</button>
          </div>
        ))}
        {stops.length === 0 && <p className="empty-state">No delivery stops yet.</p>}
      </div>

      <div className="panel-actions">
        <button className="secondary-button" type="button" onClick={onAddStop}>Add stop</button>
        <button className="secondary-button" type="button" onClick={onClear} disabled={!start && stops.length === 0}>Clear</button>
      </div>

      <section className="control-section">
        <div className="section-heading"><span>Optimization path</span></div>
        <div className="segmented-control segmented-control-three">
          <button type="button" className={strategy === 'greedy' ? 'segment-active' : ''} onClick={() => onStrategyChange('greedy')}>Greedy</button>
          <button type="button" className={strategy === 'two_opt' ? 'segment-active' : ''} onClick={() => onStrategyChange('two_opt')}>Greedy + 2-Opt</button>
          <button type="button" className={strategy === 'lns' ? 'segment-active' : ''} onClick={() => onStrategyChange('lns')}>Greedy + 2-Opt + LNS</button>
        </div>
      </section>

      <div className="form-row">
        <label className="field-label">
          Matrix algorithm
          <select value={matrixAlgorithm} onChange={(event) => onMatrixAlgorithmChange(event.target.value as typeof matrixAlgorithm)}>
            <option value="source_dijkstra">Source Dijkstra</option>
            <option value="bidirectional_astar">Bidirectional A*</option>
          </select>
        </label>
      </div>

      <div className="option-grid">
        <label className="toggle-row"><input checked={returnToStart} type="checkbox" onChange={(event) => onReturnToStartChange(event.target.checked)} /> Return to depot</label>
        <label className="toggle-row"><input checked={useCache} type="checkbox" onChange={(event) => onUseCacheChange(event.target.checked)} /> Use matrix cache</label>
      </div>

      {error && <div className="error-box">{error}</div>}

      <button className="primary-button" type="button" onClick={onOptimize} disabled={!canOptimize}>
        {loading ? 'Optimizing…' : 'Run optimization'}
      </button>

      {totalDistanceMeters !== null && optimizedOrder.length > 0 && (
        <section className="technical-result">
          <div className="result-section-heading">
            <span>Selected result</span>
            <span className="result-chip">{selectedResult ?? strategy}</span>
          </div>
          <div className="result-card result-card-grid">
            <Metric label="Route distance" value={formatDistance(totalDistanceMeters)} />
            <Metric label="Optimization time" value={optimizationTimeMs === null ? '—' : formatMilliseconds(optimizationTimeMs)} />
          </div>
          <div className="order-line"><span>Visit order</span><strong>{optimizedOrder.map((index) => index + 1).join(' → ')}</strong></div>
          {matrixTimeMs !== null && <div className="result-footnote">Matrix generation: {formatMilliseconds(matrixTimeMs)} · Cache: {cacheStatus ?? 'unknown'}</div>}
        </section>
      )}

      {(twoOptDistanceMeters !== null || lnsDistanceMeters !== null) && (
        <section className="technical-result">
          <div className="result-section-heading"><span>Optimization comparison</span></div>
          {twoOptDistanceMeters !== null && <ResultChoice label="2-Opt" distance={twoOptDistanceMeters} improvement={twoOptImprovementPct} active={selectedResult === 'two_opt'} onClick={() => onSelectResult('two_opt')} />}
          {lnsDistanceMeters !== null && <ResultChoice label="LNS" distance={lnsDistanceMeters} improvement={lnsImprovementPct} active={selectedResult === 'lns'} onClick={() => onSelectResult('lns')} />}
        </section>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><span className="result-label">{label}</span><strong>{value}</strong></div>;
}

function ResultChoice({ label, distance, improvement, active, onClick }: { label: string; distance: number; improvement: number | null; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`result-choice ${active ? 'result-choice-active' : ''}`} onClick={onClick}>
      <span><strong>{label}</strong><span>{formatDistance(distance)}</span></span>
      <span>{improvement === null ? '—' : `${improvement.toFixed(1)}% saved`}</span>
    </button>
  );
}

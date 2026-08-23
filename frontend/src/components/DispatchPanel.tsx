import type { DispatchCompareResponse, DispatchDriverRequest, DispatchMatrixAlgorithm, DispatchOrderRequest } from '../types/domain';
import { formatDistance, formatMilliseconds } from '../utils/format';

interface DispatchPanelProps {
  drivers: DispatchDriverRequest[];
  orders: DispatchOrderRequest[];
  matrixAlgorithm: DispatchMatrixAlgorithm;
  useCache: boolean;
  response: DispatchCompareResponse | null;
  onMatrixAlgorithmChange: (value: DispatchMatrixAlgorithm) => void;
  onUseCacheChange: (value: boolean) => void;
  onAddDriver: () => void;
  onAddOrder: () => void;
  onRemoveDriver: (index: number) => void;
  onRemoveOrder: (index: number) => void;
  onDispatch: () => void;
  onClear: () => void;
  onAssignmentViewChange: (value: 'hungarian' | 'greedy') => void;
  assignmentView: 'hungarian' | 'greedy';
  loading: boolean;
  error: string | null;
}

export function DispatchPanel({
  drivers,
  orders,
  matrixAlgorithm,
  useCache,
  response,
  onMatrixAlgorithmChange,
  onUseCacheChange,
  onAddDriver,
  onAddOrder,
  onRemoveDriver,
  onRemoveOrder,
  onDispatch,
  onClear,
  onAssignmentViewChange,
  assignmentView,
  loading,
  error,
}: DispatchPanelProps) {
  const canDispatch = drivers.length > 0 && orders.length > 0 && !loading;
  const selectedResult = response?.[assignmentView];
  const selectedFairness = assignmentView === 'hungarian' ? response?.hungarian_fairness : response?.greedy_fairness;

  return (
    <div className="panel-stack">
      <div>
        <p className="eyebrow">Driver dispatch</p>
        <h2 className="panel-title">Assign orders to drivers</h2>
        <p className="panel-copy">Compare greedy assignment with the Hungarian optimizer using the backend cost model.</p>
      </div>

      <section className="compact-section">
        <div className="section-heading"><span>Drivers</span><button className="text-button" type="button" onClick={onAddDriver}>Add</button></div>
        {drivers.length === 0 && <p className="empty-state">No drivers yet.</p>}
        {drivers.map((driver, index) => (
          <div className="dispatch-row" key={driver.driver_id}>
            <span className="dispatch-swatch dispatch-swatch-driver" />
            <span className="dispatch-text"><strong>{driver.driver_id}</strong><span>{driver.lat.toFixed(4)}, {driver.lon.toFixed(4)} · {driver.max_capacity - driver.current_load} slots</span></span>
            <button className="icon-button" type="button" onClick={() => onRemoveDriver(index)} aria-label={`Remove ${driver.driver_id}`}>×</button>
          </div>
        ))}
      </section>

      <section className="compact-section">
        <div className="section-heading"><span>Orders</span><button className="text-button" type="button" onClick={onAddOrder}>Add</button></div>
        {orders.length === 0 && <p className="empty-state">No orders yet.</p>}
        {orders.map((order, index) => (
          <div className="dispatch-row" key={order.order_id}>
            <span className="dispatch-swatch dispatch-swatch-order" />
            <span className="dispatch-text"><strong>{order.order_id}</strong><span>{order.pickup_lat.toFixed(4)}, {order.pickup_lon.toFixed(4)}</span></span>
            <button className="icon-button" type="button" onClick={() => onRemoveOrder(index)} aria-label={`Remove ${order.order_id}`}>×</button>
          </div>
        ))}
      </section>

      <div className="form-row">
        <label className="field-label">
          Cost matrix
          <select value={matrixAlgorithm} onChange={(event) => onMatrixAlgorithmChange(event.target.value as DispatchMatrixAlgorithm)}>
            <option value="haversine">Haversine</option>
            <option value="source_dijkstra">Source Dijkstra / road network</option>
          </select>
        </label>
      </div>

      <label className="toggle-row"><input checked={useCache} type="checkbox" onChange={(event) => onUseCacheChange(event.target.checked)} /> Use dispatch cache</label>

      {error && <div className="error-box">{error}</div>}

      <button className="primary-button" type="button" onClick={onDispatch} disabled={!canDispatch}>
        {loading ? 'Assigning…' : 'Run dispatch comparison'}
      </button>

      <button className="secondary-button" type="button" onClick={onClear} disabled={drivers.length === 0 && orders.length === 0}>Clear dispatch</button>

      {response && selectedResult && selectedFairness && (
        <section className="technical-result">
          <div className="result-section-heading"><span>Assignment result</span><span className="result-chip">{assignmentView === 'hungarian' ? 'Hungarian' : 'Greedy'}</span></div>
          <div className="segmented-control">
            <button type="button" className={assignmentView === 'greedy' ? 'segment-active' : ''} onClick={() => onAssignmentViewChange('greedy')}>Greedy</button>
            <button type="button" className={assignmentView === 'hungarian' ? 'segment-active' : ''} onClick={() => onAssignmentViewChange('hungarian')}>Hungarian</button>
          </div>

          <div className="result-card result-card-grid">
            <Metric label="Assigned" value={`${selectedResult.assigned_count}`} />
            <Metric label="Total cost" value={formatDistance(selectedResult.total_cost)} />
            <Metric label="Compute time" value={formatMilliseconds(response.total_time_ms)} />
            <Metric label="Fairness score" value={selectedFairness.fairness_score.toFixed(3)} />
          </div>

          <div className="assignment-list">
            {selectedResult.assignments.map((assignment) => (
              <div className="assignment-row" key={`${assignment.driver_id}-${assignment.order_id}`}>
                <span>{assignment.driver_id}</span><strong>→</strong><span>{assignment.order_id}</span><span>{formatDistance(assignment.cost)}</span>
              </div>
            ))}
          </div>

          <div className="result-footnote">
            Hungarian vs Greedy: {response.comparison.hungarian_vs_greedy_improvement_pct.toFixed(1)}% lower cost. Cache: {response.cache_status ?? 'unknown'}.
          </div>
        </section>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><span className="result-label">{label}</span><strong>{value}</strong></div>;
}

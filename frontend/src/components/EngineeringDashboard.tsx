import { useEffect, useMemo, useState } from 'react';
import {
  getGraphStats,
  getHealth,
  getLiveness,
  getMetrics,
  getReadiness,
} from '../api/cityRouteApi';
import type {
  AdvancedCompareResponse,
  DispatchCompareResponse,
  GraphStatsResponse,
  HealthResponse,
  LivenessResponse,
  ReadinessResponse,
  RouteComparisonResponse,
  VrpCompareResponse,
  VrpGreedyResponse,
} from '../types/domain';

interface EngineeringDashboardProps {
  routeResponse: RouteComparisonResponse | null;
  greedyResponse: VrpGreedyResponse | null;
  vrpComparison: VrpCompareResponse | null;
  advancedComparison: AdvancedCompareResponse | null;
  dispatchResponse: DispatchCompareResponse | null;
}

interface MetricValue {
  name: string;
  value: string;
  labels: string;
}

const REFRESH_INTERVAL_MS = 15_000;
const MAX_METRIC_ROWS = 18;

function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function formatMilliseconds(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${formatNumber(value, 2)} ms`;
}

function formatDistance(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return value >= 1000 ? `${formatNumber(value / 1000, 2)} km` : `${formatNumber(value, 0)} m`;
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${formatNumber(value, 2)}%`;
}

function formatUptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—';
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3_600);
  const minutes = Math.floor((total % 3_600) / 60);
  return days > 0 ? `${days}d ${hours}h ${minutes}m` : `${hours}h ${minutes}m`;
}

function metricLooksInteresting(name: string): boolean {
  return (
    name.startsWith('cityroute_') &&
    !name.endsWith('_created') &&
    !name.includes('_bucket') &&
    !name.includes('_count') &&
    !name.includes('_sum')
  );
}

function parsePrometheusMetrics(payload: string): MetricValue[] {
  const rows: MetricValue[] = [];

  for (const line of payload.split('\n')) {
    if (!line || line.startsWith('#')) continue;

    const match = line.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{([^}]*)\})?\s+(.+)$/);
    if (!match) continue;

    const [, name, , labels, value] = match;
    if (!metricLooksInteresting(name)) continue;

    rows.push({ name, labels: labels ?? '', value });
    if (rows.length >= MAX_METRIC_ROWS) break;
  }

  return rows;
}

function statusClass(status: string | undefined): string {
  if (!status) return 'eng-state eng-state-neutral';
  if (['ready', 'alive', 'ok'].includes(status)) return 'eng-state eng-state-ready';
  if (['degraded', 'starting'].includes(status)) return 'eng-state eng-state-warn';
  return 'eng-state eng-state-error';
}

function RuntimePanel({
  readiness,
  health,
  liveness,
  graph,
}: {
  readiness: ReadinessResponse | null;
  health: HealthResponse | null;
  liveness: LivenessResponse | null;
  graph: GraphStatsResponse | null;
}) {
  const components = readiness?.components;

  return (
    <section className="eng-panel eng-panel-runtime">
      <div className="eng-panel-header">
        <div>
          <p className="eyebrow">Runtime</p>
          <h2 className="eng-panel-title">Production state</h2>
        </div>
        <span className={statusClass(readiness?.status)}>{readiness?.status ?? 'unknown'}</span>
      </div>

      <div className="eng-grid eng-grid-runtime">
        <div className="eng-state-card">
          <span className="eng-muted">Liveness</span>
          <strong>{liveness?.status ?? '—'}</strong>
          <small>{formatUptime(liveness?.uptime_s)} uptime</small>
        </div>
        <div className="eng-state-card">
          <span className="eng-muted">Readiness</span>
          <strong>{readiness?.ready ? 'Accepting' : 'Blocked'}</strong>
          <small>{readiness?.phase ?? 'phase unknown'}</small>
        </div>
        <div className="eng-state-card">
          <span className="eng-muted">Legacy health</span>
          <strong>{health?.status ?? '—'}</strong>
          <small>graph_loaded={String(health?.graph_loaded ?? false)}</small>
        </div>
        <div className="eng-state-card">
          <span className="eng-muted">Graph</span>
          <strong>{graph?.graph_loaded ? 'Loaded' : 'Unavailable'}</strong>
          <small>{graph?.city ?? '—'}</small>
        </div>
      </div>

      <div className="eng-component-grid">
        {[
          ['graph', components?.graph],
          ['snap index', components?.snap_index],
          ['dispatch adjacency', components?.dispatch_adjacency],
          ['redis', components?.redis],
        ].map(([name, value]) => (
          <div className="eng-component" key={name as string}>
            <span>{name}</span>
            <b className={statusClass(value as string)}>{(value as string) ?? '—'}</b>
          </div>
        ))}
      </div>

      {(readiness?.degraded_dependencies.length ?? 0) > 0 && (
        <div className="eng-inline-warning">
          Degraded dependencies: {readiness?.degraded_dependencies.join(', ')}
        </div>
      )}
    </section>
  );
}

function GraphPanel({ graph }: { graph: GraphStatsResponse | null }) {
  return (
    <section className="eng-panel">
      <div className="eng-panel-header">
        <div>
          <p className="eyebrow">Infrastructure</p>
          <h2 className="eng-panel-title">Road graph</h2>
        </div>
        <span className="eng-chip">OpenStreetMap graph</span>
      </div>
      <div className="eng-metric-grid">
        <div><span>City</span><strong>{graph?.city ?? '—'}</strong></div>
        <div><span>Nodes</span><strong>{formatNumber(graph?.nodes, 0)}</strong></div>
        <div><span>Edges</span><strong>{formatNumber(graph?.edges, 0)}</strong></div>
        <div><span>Load time</span><strong>{graph?.load_time_s == null ? '—' : `${formatNumber(graph.load_time_s, 2)} s`}</strong></div>
        <div><span>File size</span><strong>{graph?.graph_file_size_mb == null ? '—' : `${formatNumber(graph.graph_file_size_mb, 2)} MB`}</strong></div>
        <div><span>Memory</span><strong>{graph?.memory_mb == null ? '—' : `${formatNumber(graph.memory_mb, 2)} MB`}</strong></div>
      </div>
    </section>
  );
}

function RouteEvidence({ response }: { response: RouteComparisonResponse | null }) {
  return (
    <section className="eng-panel">
      <div className="eng-panel-header">
        <div>
          <p className="eyebrow">Phase 4 · Routing</p>
          <h2 className="eng-panel-title">A* vs Bidirectional A*</h2>
        </div>
        <span className="eng-chip">{response?.status ?? 'no run'}</span>
      </div>

      {!response ? (
        <div className="eng-empty">Run Route → Compare algorithms in the product view to populate live evidence here.</div>
      ) : (
        <>
          <div className="eng-compare-grid">
            <div className="eng-algo-card">
              <div className="eng-algo-name">A*</div>
              <div className="eng-big-number">{formatMilliseconds(response.astar.route_time_ms)}</div>
              <div className="eng-submetric">{formatNumber(response.astar.nodes_expanded, 0)} nodes expanded</div>
              <div className="eng-submetric">{formatDistance(response.astar.distance_m)}</div>
            </div>
            <div className="eng-algo-card eng-algo-highlight">
              <div className="eng-algo-name">Bidirectional A*</div>
              <div className="eng-big-number">{formatMilliseconds(response.bidirectional_astar.route_time_ms)}</div>
              <div className="eng-submetric">{formatNumber(response.bidirectional_astar.nodes_expanded, 0)} nodes expanded</div>
              <div className="eng-submetric">meeting node: {response.bidirectional_astar.meeting_node ?? '—'}</div>
            </div>
          </div>

          <div className="eng-proof-row">
            <div><span>Distance parity</span><strong>{response.comparison.same_distance ? 'YES' : 'NO'}</strong></div>
            <div><span>Node reduction</span><strong>{formatPercent(response.comparison.nodes_expanded_reduction_pct)}</strong></div>
            <div><span>Time reduction</span><strong>{formatPercent(response.comparison.route_time_reduction_pct)}</strong></div>
            <div><span>Total compare</span><strong>{formatMilliseconds(response.compare_total_time_ms)}</strong></div>
          </div>
        </>
      )}
    </section>
  );
}

function VrpEvidence({
  greedy,
  comparison,
  advanced,
}: {
  greedy: VrpGreedyResponse | null;
  comparison: VrpCompareResponse | null;
  advanced: AdvancedCompareResponse | null;
}) {
  const rows = useMemo(() => {
    const values = [
      greedy
        ? {
            key: 'greedy',
            label: 'Greedy',
            distance: greedy.total_distance_m,
            time: greedy.optimization_time_ms,
            improvement: null as number | null,
          }
        : null,
      comparison
        ? {
            key: 'two_opt',
            label: '2-Opt',
            distance: comparison.two_opt.total_distance_m,
            time: comparison.two_opt.optimization_time_ms,
            improvement: comparison.improvement.improvement_pct,
          }
        : null,
      advanced
        ? {
            key: 'lns',
            label: 'LNS',
            distance: advanced.lns.total_distance_m,
            time: advanced.lns.optimization_time_ms,
            improvement: advanced.comparison.lns_vs_greedy_improvement_pct,
          }
        : null,
    ];
    return values.filter(Boolean) as Array<{
      key: string;
      label: string;
      distance: number;
      time: number;
      improvement: number | null;
    }>;
  }, [greedy, comparison, advanced]);

  return (
    <section className="eng-panel">
      <div className="eng-panel-header">
        <div>
          <p className="eyebrow">Tier 2 → Tier 3 · Optimization</p>
          <h2 className="eng-panel-title">Greedy → 2-Opt → LNS</h2>
        </div>
        <span className="eng-chip">{rows.length} stages captured</span>
      </div>

      {rows.length === 0 ? (
        <div className="eng-empty">Run a delivery optimization in the product view to populate algorithm evidence.</div>
      ) : (
        <>
          <div className="eng-table">
            <div className="eng-table-row eng-table-head"><span>Algorithm</span><span>Distance</span><span>Runtime</span><span>Improvement</span></div>
            {rows.map((row) => (
              <div className="eng-table-row" key={row.key}>
                <span>{row.label}</span>
                <span>{formatDistance(row.distance)}</span>
                <span>{formatMilliseconds(row.time)}</span>
                <span>{row.improvement == null ? 'baseline' : formatPercent(row.improvement)}</span>
              </div>
            ))}
          </div>

          {(comparison || advanced) && (
            <div className="eng-proof-row">
              {comparison && <div><span>2-Opt swaps</span><strong>{comparison.two_opt.swaps_applied}</strong></div>}
              {comparison && <div><span>2-Opt converged</span><strong>{String(comparison.two_opt.converged)}</strong></div>}
              {advanced && <div><span>LNS iterations</span><strong>{advanced.lns.iterations_run}</strong></div>}
              {advanced && <div><span>LNS improvements</span><strong>{advanced.lns.improvements_applied}</strong></div>}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function DispatchEvidence({ response }: { response: DispatchCompareResponse | null }) {
  return (
    <section className="eng-panel">
      <div className="eng-panel-header">
        <div>
          <p className="eyebrow">Tier 3 · Dispatch</p>
          <h2 className="eng-panel-title">Greedy vs Hungarian</h2>
        </div>
        <span className="eng-chip">assignment engine</span>
      </div>

      {!response ? (
        <div className="eng-empty">Run Dispatch in the product view to populate live assignment evidence.</div>
      ) : (
        <>
          <div className="eng-compare-grid">
            <div className="eng-algo-card">
              <div className="eng-algo-name">Greedy</div>
              <div className="eng-big-number">{formatDistance(response.greedy.total_cost)}</div>
              <div className="eng-submetric">{response.greedy.assigned_count} assignments</div>
            </div>
            <div className="eng-algo-card eng-algo-highlight">
              <div className="eng-algo-name">Hungarian</div>
              <div className="eng-big-number">{formatDistance(response.hungarian.total_cost)}</div>
              <div className="eng-submetric">{response.hungarian.assigned_count} assignments</div>
            </div>
          </div>
          <div className="eng-proof-row">
            <div><span>Cost saved</span><strong>{formatDistance(response.comparison.hungarian_vs_greedy_cost_saved)}</strong></div>
            <div><span>Improvement</span><strong>{formatPercent(response.comparison.hungarian_vs_greedy_improvement_pct)}</strong></div>
            <div><span>Cost matrix</span><strong>{formatMilliseconds(response.cost_matrix_build_time_ms)}</strong></div>
            <div><span>Total</span><strong>{formatMilliseconds(response.total_time_ms)}</strong></div>
          </div>
          <div className="eng-proof-row">
            <div><span>Hungarian fairness</span><strong>{formatNumber(response.hungarian_fairness.fairness_score, 3)}</strong></div>
            <div><span>Unassigned orders</span><strong>{response.unassigned_order_count}</strong></div>
            <div><span>Unused slots</span><strong>{response.unused_slot_count}</strong></div>
            <div><span>Matrix algorithm</span><strong>{response.matrix_algorithm}</strong></div>
          </div>
        </>
      )}
    </section>
  );
}


function ApiSurfacePanel() {
  const groups = [
    {
      name: 'Routing',
      endpoints: ['/route', '/route/compare'],
    },
    {
      name: 'Graph & location',
      endpoints: ['/graph/stats', '/graph/validate', '/graph/snap'],
    },
    {
      name: 'Matrix',
      endpoints: ['POST /matrix'],
    },
    {
      name: 'Optimization',
      endpoints: ['/vrp/greedy', '/vrp/compare', '/vrp/compare/advanced'],
    },
    {
      name: 'Dispatch',
      endpoints: ['/dispatch/compare'],
    },
    {
      name: 'Runtime & observability',
      endpoints: ['/health', '/health/live', '/health/ready', '/metrics'],
    },
  ];

  return (
    <section className="eng-panel">
      <div className="eng-panel-header">
        <div>
          <p className="eyebrow">API surface</p>
          <h2 className="eng-panel-title">Capabilities exposed by the backend</h2>
        </div>
        <span className="eng-chip">verified surface</span>
      </div>
      <div className="eng-api-grid">
        {groups.map((group) => (
          <div className="eng-api-group" key={group.name}>
            <strong>{group.name}</strong>
            {group.endpoints.map((endpoint) => (
              <code key={endpoint}>{endpoint}</code>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function MetricsPanel({ metrics }: { metrics: MetricValue[] }) {
  return (
    <section className="eng-panel">
      <div className="eng-panel-header">
        <div>
          <p className="eyebrow">Phase 11 · Observability</p>
          <h2 className="eng-panel-title">Runtime metrics</h2>
        </div>
        <span className="eng-chip">Prometheus</span>
      </div>
      {metrics.length === 0 ? (
        <div className="eng-empty">No Prometheus samples are currently available.</div>
      ) : (
        <div className="eng-metrics-list">
          {metrics.map((metric) => (
            <div className="eng-metric-line" key={`${metric.name}-${metric.labels}`}>
              <span>{metric.name}</span>
              <code>{metric.value}{metric.labels ? `  {${metric.labels}}` : ''}</code>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ArchitecturePanel() {
  const stages = [
    ['Client', 'Product UI / API consumer'],
    ['API', 'FastAPI routers'],
    ['Services', 'Routing / matrix / VRP / dispatch orchestration'],
    ['Core', 'A*, Bi-A*, Dijkstra, 2-Opt, LNS, Hungarian'],
    ['Infrastructure', 'Graph loading, snapping, Redis, resilience'],
    ['Observability', 'Readiness, metrics, concurrency, timeouts'],
  ];

  return (
    <section className="eng-panel">
      <div className="eng-panel-header">
        <div>
          <p className="eyebrow">System design</p>
          <h2 className="eng-panel-title">Execution architecture</h2>
        </div>
        <span className="eng-chip">layered</span>
      </div>
      <div className="eng-architecture">
        {stages.map(([name, detail], index) => (
          <div className="eng-architecture-node" key={name}>
            <div className="eng-architecture-index">0{index + 1}</div>
            <div>
              <strong>{name}</strong>
              <span>{detail}</span>
            </div>
            {index < stages.length - 1 && <div className="eng-architecture-arrow">↓</div>}
          </div>
        ))}
      </div>
    </section>
  );
}

export function EngineeringDashboard({
  routeResponse,
  greedyResponse,
  vrpComparison,
  advancedComparison,
  dispatchResponse,
}: EngineeringDashboardProps) {
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [liveness, setLiveness] = useState<LivenessResponse | null>(null);
  const [graph, setGraph] = useState<GraphStatsResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricValue[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh(): Promise<void> {
    setLoading(true);
    setError(null);

    const results = await Promise.allSettled([
      getReadiness(),
      getHealth(),
      getLiveness(),
      getGraphStats(),
      getMetrics(),
    ]);

    const [readinessResult, healthResult, livenessResult, graphResult, metricsResult] = results;

    if (readinessResult.status === 'fulfilled') setReadiness(readinessResult.value);
    if (healthResult.status === 'fulfilled') setHealth(healthResult.value);
    if (livenessResult.status === 'fulfilled') setLiveness(livenessResult.value);
    if (graphResult.status === 'fulfilled') setGraph(graphResult.value);
    if (metricsResult.status === 'fulfilled') setMetrics(parsePrometheusMetrics(metricsResult.value));

    const failures = results.filter((result) => result.status === 'rejected');
    if (failures.length > 0) {
      setError(`${failures.length} telemetry request${failures.length > 1 ? 's' : ''} failed; successful panels are still shown.`);
    }

    setLastRefresh(new Date());
    setLoading(false);
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const topLine = [
    readiness?.phase ?? 'phase unavailable',
    graph?.city ?? 'city unavailable',
    `${formatNumber(graph?.nodes, 0)} nodes`,
    `${formatNumber(graph?.edges, 0)} edges`,
  ].join(' · ');

  return (
    <main className="eng-shell">
      <header className="eng-header">
        <div>
          <p className="eng-kicker">CITYROUTE / ENGINEERING</p>
          <h1>System Observatory</h1>
          <p className="eng-subtitle">Algorithms, runtime state, infrastructure and live execution evidence.</p>
          <p className="eng-meta">{topLine}</p>
        </div>
        <div className="eng-header-actions">
          <span className="eng-live-dot">● LIVE</span>
          <button className="eng-refresh" type="button" onClick={() => void refresh()} disabled={loading}>
            {loading ? 'Refreshing…' : 'Refresh telemetry'}
          </button>
        </div>
      </header>

      {error && <div className="eng-banner">{error}</div>}
      {lastRefresh && <div className="eng-last-refresh">Last telemetry refresh: {lastRefresh.toLocaleTimeString()}</div>}

      <div className="eng-dashboard-grid">
        <RuntimePanel readiness={readiness} health={health} liveness={liveness} graph={graph} />
        <GraphPanel graph={graph} />
        <RouteEvidence response={routeResponse} />
        <VrpEvidence greedy={greedyResponse} comparison={vrpComparison} advanced={advancedComparison} />
        <DispatchEvidence response={dispatchResponse} />
        <ArchitecturePanel />
        <ApiSurfacePanel />
        <MetricsPanel metrics={metrics} />
      </div>
    </main>
  );
}

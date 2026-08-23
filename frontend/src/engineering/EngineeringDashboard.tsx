import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  compareAdvancedStops,
  compareDispatch,
  compareRoute,
  createMatrix,
  getGraphStats,
  getHealth,
  getLiveness,
  getMetricsText,
  getReadiness,
  getRoot,
  snapGraphCoordinate,
  validateGraphCoordinate,
} from '../api/cityRouteApi';
import { CodeTag, PanelSection, StatusPill } from '../components/PanelPrimitives';
import { Metric } from '../components/Metric';
import type {
  ArchitectureInventory,
  Coordinate,
  DispatchCompareResponse,
  DispatchDriverRequest,
  DispatchOrderRequest,
  EvidenceSummary,
  GraphSnapResponse,
  GraphStatsResponse,
  GraphValidationResponse,
  LegacyHealthResponse,
  LivenessResponse,
  MatrixResponse,
  MetricSample,
  ReadinessResponse,
  RootResponse,
  TestInventory,
  VrpAdvancedCompareRequest,
  AdvancedCompareResponse,
} from '../types/domain';
import { formatBool, formatBytesMb, formatMilliseconds, formatNumber, formatSeconds } from '../utils/format';
import { metricValue, parsePrometheusText } from '../utils/prometheus';

const REFRESH_INTERVAL_MS = 10_000;
const DEFAULT_PROBE_COORDINATE: Coordinate = { lat: 26.465, lon: 80.33 };
const MAX_MATRIX_PROBE_LOCATIONS = 8;
const MAX_DISPATCH_PROBE_DRIVERS = 4;
const MAX_DISPATCH_PROBE_ORDERS = 4;

const API_SURFACE = [
  ['/health', 'legacy health contract'],
  ['/health/live', 'liveness / process availability'],
  ['/health/ready', 'readiness / dependency state'],
  ['/graph/stats', 'loaded road graph metadata'],
  ['/graph/validate', 'coordinate validation'],
  ['/graph/snap', 'coordinate → graph node'],
  ['/route', 'A* point-to-point routing'],
  ['/route/compare', 'A* vs Bidirectional A*'],
  ['/matrix', 'N×N road distance / ETA matrix'],
  ['/vrp/greedy', 'nearest-neighbor baseline'],
  ['/vrp/compare', 'Greedy vs 2-Opt'],
  ['/vrp/compare/advanced', 'Greedy vs 2-Opt vs LNS'],
  ['/dispatch/compare', 'Greedy vs Hungarian dispatch'],
  ['/metrics', 'Prometheus exposition'],
] as const;

type EngineView = 'overview' | 'routing' | 'optimization' | 'dispatch' | 'runtime' | 'evidence';

interface EngineeringSnapshot {
  root: RootResponse | null;
  health: LegacyHealthResponse | null;
  liveness: LivenessResponse | null;
  readiness: ReadinessResponse | null;
  graph: GraphStatsResponse | null;
  metrics: MetricSample[];
  refreshedAt: string | null;
}

interface ProbeLocation extends Coordinate {
  id: string;
}

function emptySnapshot(): EngineeringSnapshot {
  return { root: null, health: null, liveness: null, readiness: null, graph: null, metrics: [], refreshedAt: null };
}

function stateForComponent(value: string | undefined): 'ok' | 'warn' | 'bad' | 'neutral' {
  if (!value) return 'neutral';
  if (value === 'ready' || value === 'available') return 'ok';
  if (value === 'degraded') return 'warn';
  if (value === 'unavailable' || value === 'not_ready') return 'bad';
  return 'neutral';
}

function formatMetric(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—';
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function safeJsonParse<T>(value: string, label: string): T {
  try {
    return JSON.parse(value) as T;
  } catch (error) {
    throw new Error(`${label} is not valid JSON: ${error instanceof Error ? error.message : 'unknown parse error'}`);
  }
}

const INITIAL_MATRIX_LOCATIONS: ProbeLocation[] = [
  { id: 'A', lat: 26.465, lon: 80.330 },
  { id: 'B', lat: 26.470, lon: 80.345 },
  { id: 'C', lat: 26.458, lon: 80.350 },
];

export function EngineeringDashboard() {
  const [view, setView] = useState<EngineView>('overview');
  const [snapshot, setSnapshot] = useState<EngineeringSnapshot>(emptySnapshot());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [architecture, setArchitecture] = useState<ArchitectureInventory | null>(null);
  const [tests, setTests] = useState<TestInventory | null>(null);
  const [evidence, setEvidence] = useState<EvidenceSummary[]>([]);
  const [benchmarkCatalog, setBenchmarkCatalog] = useState<Array<{ phase: string; file_count: number; json_count: number; python_count: number; text_count: number }>>([]);

  const refreshLiveState = useCallback(async () => {
    setLoading(true);
    setError(null);
    const results = await Promise.allSettled([
      getRoot(),
      getHealth(),
      getLiveness(),
      getReadiness(),
      getGraphStats(),
      getMetricsText(),
    ]);

    const [rootResult, healthResult, liveResult, readyResult, graphResult, metricsResult] = results;
    const failed = results.filter((result) => result.status === 'rejected');
    if (failed.length === results.length) {
      setError('Live engineering endpoints are currently unavailable.');
      setLoading(false);
      return;
    }

    setSnapshot({
      root: rootResult.status === 'fulfilled' ? rootResult.value : snapshot.root,
      health: healthResult.status === 'fulfilled' ? healthResult.value : snapshot.health,
      liveness: liveResult.status === 'fulfilled' ? liveResult.value : snapshot.liveness,
      readiness: readyResult.status === 'fulfilled' ? readyResult.value : snapshot.readiness,
      graph: graphResult.status === 'fulfilled' ? graphResult.value : snapshot.graph,
      metrics: metricsResult.status === 'fulfilled' ? parsePrometheusText(metricsResult.value) : snapshot.metrics,
      refreshedAt: new Date().toISOString(),
    });

    if (failed.length > 0) {
      setError(`${failed.length} live engineering request${failed.length === 1 ? '' : 's'} failed; available panels remain usable.`);
    }
    setLoading(false);
  }, [snapshot.graph, snapshot.health, snapshot.liveness, snapshot.metrics, snapshot.readiness, snapshot.root]);

  useEffect(() => {
    void refreshLiveState();
    const interval = window.setInterval(() => void refreshLiveState(), REFRESH_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [refreshLiveState]);

  useEffect(() => {
    void Promise.all([
      fetch('/evidence/phase11-evidence.json').then((response) => response.json() as Promise<EvidenceSummary[]>),
      fetch('/evidence/test-inventory.json').then((response) => response.json() as Promise<TestInventory>),
      fetch('/evidence/architecture-inventory.json').then((response) => response.json() as Promise<ArchitectureInventory>),
      fetch('/evidence/benchmark-catalog.json').then((response) => response.json() as Promise<Array<{ phase: string; file_count: number; json_count: number; python_count: number; text_count: number }>>),
    ]).then(([nextEvidence, nextTests, nextArchitecture, nextBenchmarkCatalog]) => {
      setEvidence(nextEvidence);
      setTests(nextTests);
      setArchitecture(nextArchitecture);
      setBenchmarkCatalog(nextBenchmarkCatalog);
    }).catch(() => {
      setError('Archived evidence assets could not be loaded from the frontend bundle.');
    });
  }, []);

  const runtime = useMemo(() => ({
    active: metricValue(snapshot.metrics, 'cityroute_active_requests'),
    waiting: metricValue(snapshot.metrics, 'cityroute_waiting_requests'),
    maxActive: metricValue(snapshot.metrics, 'cityroute_max_active_requests'),
    maxWaiting: metricValue(snapshot.metrics, 'cityroute_max_waiting_requests'),
    rejections: metricValue(snapshot.metrics, 'cityroute_request_rejections_total'),
    overload: metricValue(snapshot.metrics, 'cityroute_overload_events_total'),
    redis: metricValue(snapshot.metrics, 'cityroute_redis_available'),
    graph: metricValue(snapshot.metrics, 'cityroute_graph_loaded'),
    snap: metricValue(snapshot.metrics, 'cityroute_snap_index_loaded'),
    timeouts: metricValue(snapshot.metrics, 'cityroute_request_timeouts_total'),
  }), [snapshot.metrics]);

  const nav = [
    ['overview', 'Overview'],
    ['routing', 'Routing Engine'],
    ['optimization', 'Optimization Engine'],
    ['dispatch', 'Dispatch Engine'],
    ['runtime', 'Runtime & Resilience'],
    ['evidence', 'Evidence'],
  ] as const;

  return (
    <div className="engineering-shell">
      <header className="engine-hero">
        <div>
          <div className="engine-kicker"><span className="engine-pulse" /> ENGINEERING CONSOLE · LIVE STATE + VERIFIED EVIDENCE</div>
          <h2>Inspect the system behind CityRoute.</h2>
          <p>Architecture, algorithms, execution probes, runtime controls, resilience behavior and supplied benchmark evidence. Historical artifacts are never presented as current telemetry.</p>
        </div>
        <div className="engine-hero-actions">
          <div className="provenance-legend">
            <span><i className="legend-live" /> LIVE</span>
            <span><i className="legend-probe" /> PROBE</span>
            <span><i className="legend-evidence" /> EVIDENCE</span>
          </div>
          <StatusPill label={snapshot.readiness?.status ?? (loading ? 'refreshing' : 'unknown')} state={snapshot.readiness?.ready ? 'ok' : snapshot.readiness?.status === 'degraded' ? 'warn' : snapshot.readiness ? 'bad' : 'neutral'} />
          <button className="secondary-button compact-button" type="button" onClick={() => void refreshLiveState()} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh live state'}</button>
        </div>
      </header>

      <nav className="engine-nav" aria-label="Engineering views">
        {nav.map(([key, label]) => <button key={key} type="button" className={view === key ? 'engine-nav-active' : ''} onClick={() => setView(key)}>{label}</button>)}
      </nav>

      {error && <div className="notice-box engineering-error">{error}</div>}

      {view === 'overview' && <OverviewView snapshot={snapshot} runtime={runtime} architecture={architecture} evidence={evidence} tests={tests} benchmarkCatalog={benchmarkCatalog} setView={setView} />}
      {view === 'routing' && <RoutingEngineView snapshot={snapshot} />}
      {view === 'optimization' && <OptimizationEngineView architecture={architecture} />}
      {view === 'dispatch' && <DispatchEngineView architecture={architecture} />}
      {view === 'runtime' && <RuntimeView snapshot={snapshot} runtime={runtime} architecture={architecture} evidence={evidence} />}
      {view === 'evidence' && <EvidenceView evidence={evidence} tests={tests} benchmarkCatalog={benchmarkCatalog} />}

      <footer className="engineering-footer">
        <span>Live refresh: {snapshot.refreshedAt ? new Date(snapshot.refreshedAt).toLocaleTimeString() : '—'}</span>
        <span>Live source: /health + /graph/stats + /metrics</span>
        <span>Archived source: supplied source/test/benchmark archives</span>
      </footer>
    </div>
  );
}

function OverviewView({ snapshot, runtime, architecture, evidence, tests, benchmarkCatalog, setView }: any) {
  return <>
    <section className="engine-grid engine-grid-hero">
      <PanelSection title="System architecture" subtitle="Current source inventory, not inferred from the UI.">
        <div className="engine-flow">
          <FlowNode eyebrow="API" title="FastAPI routers" detail={architecture?.api?.join(' · ') ?? '—'} />
          <span className="flow-arrow">→</span>
          <FlowNode eyebrow="SERVICES" title="Orchestration" detail={architecture?.services?.join(' · ') ?? '—'} />
          <span className="flow-arrow">→</span>
          <FlowNode eyebrow="CORE" title="Algorithms" detail={architecture?.core?.filter((x: string) => x !== '__init__.py').join(' · ') ?? '—'} />
          <span className="flow-arrow">→</span>
          <FlowNode eyebrow="INFRA / RUNTIME" title="Operational layer" detail={[...(architecture?.infrastructure ?? []), ...(architecture?.middleware ?? [])].join(' · ')} />
        </div>
      </PanelSection>
      <PanelSection title="Current runtime state" subtitle="LIVE — directly from the running backend.">
        <div className="live-service-grid">
          {(['graph', 'snap_index', 'dispatch_adjacency', 'redis'] as const).map((key) => (
            <div key={key} className="live-service-card"><span>{key.replace('_', ' ')}</span><StatusPill label={snapshot.readiness?.components[key] ?? 'unknown'} state={stateForComponent(snapshot.readiness?.components[key])} /></div>
          ))}
        </div>
        <div className="metric-grid metric-grid-4 engine-runtime-metrics">
          <Metric label="Active" value={formatMetric(runtime.active)} />
          <Metric label="Waiting" value={formatMetric(runtime.waiting)} />
          <Metric label="Configured active" value={formatMetric(runtime.maxActive)} />
          <Metric label="Configured waiting" value={formatMetric(runtime.maxWaiting)} />
        </div>
      </PanelSection>
    </section>

    <section className="engine-grid engine-grid-three">
      <EngineTile title="Routing engine" code="A* · Bi-A* · Dijkstra · ETA" description="Real graph routing, snapping and algorithm comparison." onClick={() => setView('routing')} />
      <EngineTile title="Optimization engine" code="Matrix · Greedy · 2-Opt · LNS" description="Road-distance matrix, cache, optimization pipeline and execution traces." onClick={() => setView('optimization')} />
      <EngineTile title="Dispatch engine" code="Cost matrix · Greedy · Hungarian" description="Capacity, reachability, fairness and road-network dispatch." onClick={() => setView('dispatch')} />
      <EngineTile title="Runtime & resilience" code="Concurrency · Timeout · Lifecycle" description="Admission control, readiness, Redis resilience and service lifecycle." onClick={() => setView('runtime')} />
      <EngineTile title="Evidence explorer" code="Tests · Benchmarks · Phase 11" description="Historical proof kept separate from current runtime telemetry." onClick={() => setView('evidence')} />
      <div className="engineering-source-card"><div className="engine-tile-code">SOURCE INVENTORY</div><h3>{architecture ? architecture.core.length : 0} core modules</h3><p>{architecture?.services.length ?? 0} services · {architecture?.api.length ?? 0} API modules · {tests?.test_file_count ?? 0} test modules.</p></div>
    </section>

    <section className="engine-grid">
      <PanelSection title="Road graph — LIVE" subtitle="Current /graph/stats response.">
        <div className="metric-grid metric-grid-4">
          <Metric label="City" value={snapshot.graph?.city ?? '—'} />
          <Metric label="Nodes" value={formatNumber(snapshot.graph?.nodes)} />
          <Metric label="Edges" value={formatNumber(snapshot.graph?.edges)} />
          <Metric label="Load time" value={formatSeconds(snapshot.graph?.load_time_s)} />
          <Metric label="Graph size" value={formatBytesMb(snapshot.graph?.graph_file_size_mb)} />
          <Metric label="Memory" value={formatBytesMb(snapshot.graph?.memory_mb)} />
          <Metric label="Loaded" value={formatBool(snapshot.graph?.graph_loaded)} />
        </div>
      </PanelSection>
      <PanelSection title="Evidence inventory — ARCHIVE" subtitle="Artifact presence does not mean current runtime status.">
        <div className="metric-grid metric-grid-4">
          <Metric label="Phase 11 probes" value={formatNumber(evidence.length)} />
          <Metric label="Benchmark phases" value={formatNumber(benchmarkCatalog.length)} />
          <Metric label="Test modules" value={formatNumber(tests?.test_file_count)} />
          <Metric label="Explicit test defs" value={formatNumber(tests?.explicit_test_function_count)} />
        </div>
        <div className="source-note">The supplied test inventory counts explicit <code>test_*</code> definitions. It does not claim a current pass count.</div>
      </PanelSection>
    </section>
  </>;
}

function RoutingEngineView({ snapshot }: { snapshot: EngineeringSnapshot }) {
  const [coordinate, setCoordinate] = useState<Coordinate>(DEFAULT_PROBE_COORDINATE);
  const [end, setEnd] = useState<Coordinate>({ lat: 26.47, lon: 80.345 });
  const [validation, setValidation] = useState<GraphValidationResponse | null>(null);
  const [snapResult, setSnapResult] = useState<GraphSnapResponse | null>(null);
  const [comparison, setComparison] = useState<any>(null);
  const [probeLoading, setProbeLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function validateAndSnap(): Promise<void> {
    setProbeLoading(true);
    setError(null);
    try {
      const nextValidation = await validateGraphCoordinate(coordinate);
      setValidation(nextValidation);
      setSnapResult(nextValidation.valid ? await snapGraphCoordinate(coordinate) : null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Graph probe failed.');
    } finally {
      setProbeLoading(false);
    }
  }

  async function runComparison(): Promise<void> {
    setProbeLoading(true);
    setError(null);
    try {
      setComparison(await compareRoute(coordinate, end));
    } catch (requestError) {
      setComparison(null);
      setError(requestError instanceof Error ? requestError.message : 'Routing comparison failed.');
    } finally {
      setProbeLoading(false);
    }
  }

  return <>
    <section className="engine-grid engine-grid-top">
      <PanelSection title="Routing pipeline" subtitle="Implementation → validation → graph → search → geometry.">
        <div className="engine-stack-diagram">
          <StackStage label="01" detail="Coordinate input" />
          <StackStage label="02" detail="/graph/validate" />
          <StackStage label="03" detail="/graph/snap" />
          <StackStage label="04" detail="A* / Bi-A* / Dijkstra" />
          <StackStage label="05" detail="geometry + distance + ETA" />
        </div>
        <ArchitectureBlock label="Core source" items={['a_star.py', 'bidirectional_a_star.py', 'multi_target_dijkstra.py', 'graph_adjacency.py', 'eta.py']} />
        <ArchitectureBlock label="Routing APIs" items={['/route', '/route/compare', '/graph/validate', '/graph/snap', '/graph/stats']} />
      </PanelSection>
      <PanelSection title="Road graph state — LIVE" subtitle="Current process state.">
        <div className="metric-grid metric-grid-4">
          <Metric label="Loaded" value={formatBool(snapshot.graph?.graph_loaded)} />
          <Metric label="Nodes" value={formatNumber(snapshot.graph?.nodes)} />
          <Metric label="Edges" value={formatNumber(snapshot.graph?.edges)} />
          <Metric label="Memory" value={formatBytesMb(snapshot.graph?.memory_mb)} />
        </div>
      </PanelSection>
    </section>

    <section className="engine-grid engine-grid-top">
      <PanelSection title="Coordinate probe — PROBE" subtitle="Explicitly invokes the real validation and snap services.">
        <div className="coordinate-fields">
          <label>Latitude<input type="number" step="0.000001" value={coordinate.lat} onChange={(event) => setCoordinate({ ...coordinate, lat: Number(event.target.value) })} /></label>
          <label>Longitude<input type="number" step="0.000001" value={coordinate.lon} onChange={(event) => setCoordinate({ ...coordinate, lon: Number(event.target.value) })} /></label>
          <button className="primary-button" type="button" onClick={() => void validateAndSnap()} disabled={probeLoading}>{probeLoading ? 'Probing…' : 'Validate + snap'}</button>
        </div>
        {error && <div className="error-box">{error}</div>}
        {validation && <div className="probe-output"><CodeTag>PROBE /graph/validate</CodeTag><span>valid={String(validation.valid)} · {validation.message}</span></div>}
        {snapResult && <pre className="dark-inspector">{JSON.stringify(snapResult, null, 2)}</pre>}
      </PanelSection>
      <PanelSection title="Routing comparison — PROBE" subtitle="Runs A* and Bidirectional A* on the same request.">
        <div className="coordinate-fields">
          <label>End latitude<input type="number" step="0.000001" value={end.lat} onChange={(event) => setEnd({ ...end, lat: Number(event.target.value) })} /></label>
          <label>End longitude<input type="number" step="0.000001" value={end.lon} onChange={(event) => setEnd({ ...end, lon: Number(event.target.value) })} /></label>
          <button className="primary-button" type="button" onClick={() => void runComparison()} disabled={probeLoading}>{probeLoading ? 'Running…' : 'Compare routing'}</button>
        </div>
        {comparison && <div className="metric-grid metric-grid-4 routing-comparison-grid">
          <Metric label="Distance" value={`${formatMetric(comparison.astar.distance_km)} km`} />
          <Metric label="A* expanded" value={formatMetric(comparison.astar.nodes_expanded)} />
          <Metric label="Bi-A* expanded" value={formatMetric(comparison.bidirectional_astar.nodes_expanded)} />
          <Metric label="Reduction" value={`${formatMetric(comparison.comparison.nodes_expanded_reduction_pct)}%`} />
          <Metric label="A* time" value={formatMilliseconds(comparison.astar.route_time_ms)} />
          <Metric label="Bi-A* time" value={formatMilliseconds(comparison.bidirectional_astar.route_time_ms)} />
          <Metric label="Same distance" value={String(comparison.comparison.same_distance)} />
          <Metric label="Compare total" value={formatMilliseconds(comparison.compare_total_time_ms)} />
        </div>}
      </PanelSection>
    </section>
  </>;
}

function OptimizationEngineView({ architecture }: { architecture: ArchitectureInventory | null }) {
  const [locations, setLocations] = useState<ProbeLocation[]>(INITIAL_MATRIX_LOCATIONS);
  const [algorithm, setAlgorithm] = useState<'source_dijkstra' | 'bidirectional_astar' | 'astar'>('source_dijkstra');
  const [useCache, setUseCache] = useState(true);
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [advanced, setAdvanced] = useState<AdvancedCompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateLocation(index: number, field: keyof ProbeLocation, value: string | number): void {
    setLocations((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: field === 'id' ? String(value) : Number(value) } : item));
  }

  function addLocation(): void {
    if (locations.length >= MAX_MATRIX_PROBE_LOCATIONS) return;
    setLocations((current) => [...current, { id: String.fromCharCode(65 + current.length), lat: 26.465, lon: 80.33 }]);
  }

  function removeLocation(index: number): void {
    if (locations.length <= 2) return;
    setLocations((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  async function runMatrix(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      setMatrix(await createMatrix({ locations, algorithm, use_cache: useCache }));
    } catch (requestError) {
      setMatrix(null);
      setError(requestError instanceof Error ? requestError.message : 'Matrix generation failed.');
    } finally {
      setLoading(false);
    }
  }

  async function runAdvancedVrp(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const [start, ...stops] = locations;
      if (!start || stops.length === 0) throw new Error('At least one start and one stop are required for the VRP probe.');
      const request: VrpAdvancedCompareRequest = {
        start: { lat: start.lat, lon: start.lon },
        stops: stops.map(({ lat, lon }) => ({ lat, lon })),
        return_to_start: false,
        matrix_algorithm: algorithm === 'astar' ? 'bidirectional_astar' : algorithm,
        use_cache: useCache,
        two_opt_max_iterations: 100,
        two_opt_improvement_tolerance_m: 0.001,
        lns_max_iterations: 500,
        lns_destroy_fraction: 0.3,
        lns_no_improvement_limit: 100,
        lns_random_seed: 0,
        keep_trace: true,
      };
      setAdvanced(await compareAdvancedStops(request));
    } catch (requestError) {
      setAdvanced(null);
      setError(requestError instanceof Error ? requestError.message : 'Advanced VRP probe failed.');
    } finally {
      setLoading(false);
    }
  }

  return <>
    <section className="engine-grid">
      <PanelSection title="Optimization architecture" subtitle="The actual source components behind the product-facing Deliveries workflow.">
        <ArchitectureBlock label="Core" items={architecture?.core?.filter((item) => /distance_matrix|greedy_nearest|two_opt|lns|vrp_improvement/i.test(item)) ?? []} />
        <ArchitectureBlock label="Services" items={architecture?.services?.filter((item) => /matrix|greedy|vrp/i.test(item)) ?? []} />
        <ArchitectureBlock label="Infrastructure" items={architecture?.infrastructure?.filter((item) => /redis|resilience/i.test(item)) ?? []} />
      </PanelSection>
      <PanelSection title="Optimization chain" subtitle="Execution model verified by the source/roadmap.">
        <div className="engine-flow">
          <FlowNode eyebrow="01" title="N locations" detail="road coordinates" />
          <span className="flow-arrow">→</span>
          <FlowNode eyebrow="02" title="Matrix" detail="road distance / ETA" />
          <span className="flow-arrow">→</span>
          <FlowNode eyebrow="03" title="Greedy" detail="deterministic baseline" />
          <span className="flow-arrow">→</span>
          <FlowNode eyebrow="04" title="2-Opt / LNS" detail="local + metaheuristic improvement" />
        </div>
      </PanelSection>
    </section>

    <section className="engine-grid">
      <PanelSection title="Distance Matrix Lab — PROBE" subtitle="Builds an actual N×N matrix through POST /matrix. No synthetic numbers.">
        <div className="probe-table">
          <div className="probe-table-head"><span>ID</span><span>Latitude</span><span>Longitude</span><span /></div>
          {locations.map((location, index) => <div className="probe-table-row" key={`${location.id}-${index}`}>
            <input value={location.id} onChange={(event) => updateLocation(index, 'id', event.target.value)} aria-label={`Location ${index + 1} id`} />
            <input type="number" step="0.000001" value={location.lat} onChange={(event) => updateLocation(index, 'lat', event.target.value)} />
            <input type="number" step="0.000001" value={location.lon} onChange={(event) => updateLocation(index, 'lon', event.target.value)} />
            <button className="icon-button" type="button" onClick={() => removeLocation(index)} disabled={locations.length <= 2}>×</button>
          </div>)}
        </div>
        <div className="option-grid">
          <label className="field-label">Matrix algorithm<select value={algorithm} onChange={(event) => setAlgorithm(event.target.value as typeof algorithm)}><option value="source_dijkstra">Source Dijkstra</option><option value="bidirectional_astar">Bidirectional A*</option><option value="astar">A*</option></select></label>
          <label className="toggle-row"><input type="checkbox" checked={useCache} onChange={(event) => setUseCache(event.target.checked)} /> Use Redis/cache path</label>
        </div>
        <div className="action-row">
          <button className="secondary-button" type="button" onClick={addLocation} disabled={locations.length >= MAX_MATRIX_PROBE_LOCATIONS}>Add location</button>
          <button className="primary-button" type="button" onClick={() => void runMatrix()} disabled={loading || locations.length < 2}>{loading ? 'Running…' : 'Generate matrix'}</button>
        </div>
        {error && <div className="error-box">{error}</div>}
        {matrix && <MatrixProbeResult result={matrix} />}
      </PanelSection>
      <PanelSection title="Advanced VRP Lab — PROBE" subtitle="Uses the selected locations as start + stops and runs Greedy → 2-Opt → LNS.">
        <div className="notice-box">This is an engineering probe. It does not modify the Product Deliveries workflow.</div>
        <button className="primary-button" type="button" onClick={() => void runAdvancedVrp()} disabled={loading || locations.length < 2}>{loading ? 'Running…' : 'Run advanced comparison'}</button>
        {advanced && <div className="metric-grid metric-grid-4" style={{ marginTop: 8 }}>
          <Metric label="Greedy" value={`${formatMetric(advanced.greedy.total_distance_m / 1000)} km`} />
          <Metric label="2-Opt" value={`${formatMetric(advanced.two_opt.total_distance_m / 1000)} km`} />
          <Metric label="LNS" value={`${formatMetric(advanced.lns.total_distance_m / 1000)} km`} />
          <Metric label="LNS improvement" value={`${formatMetric(advanced.comparison.lns_improvement_pct)}%`} />
          <Metric label="Matrix time" value={formatMilliseconds(advanced.matrix_generation_time_ms)} />
          <Metric label="Total time" value={formatMilliseconds(advanced.total_time_ms)} />
          <Metric label="LNS iterations" value={formatNumber(advanced.lns.iterations_run)} />
          <Metric label="Seed" value={advanced.lns.random_seed === null ? '—' : String(advanced.lns.random_seed)} mono />
        </div>}
      </PanelSection>
    </section>
  </>;
}

function DispatchEngineView({ architecture }: { architecture: ArchitectureInventory | null }) {
  const [driverJson, setDriverJson] = useState(JSON.stringify([
    { driver_id: 'D1', lat: 26.465, lon: 80.33, current_load: 0, max_capacity: 2 },
    { driver_id: 'D2', lat: 26.47, lon: 80.345, current_load: 0, max_capacity: 2 },
  ], null, 2));
  const [orderJson, setOrderJson] = useState(JSON.stringify([
    { order_id: 'O1', pickup_lat: 26.458, pickup_lon: 80.35 },
    { order_id: 'O2', pickup_lat: 26.475, pickup_lon: 80.338 },
  ], null, 2));
  const [algorithm, setAlgorithm] = useState<'haversine' | 'source_dijkstra'>('haversine');
  const [useCache, setUseCache] = useState(true);
  const [returnCostBreakdown, setReturnCostBreakdown] = useState(true);
  const [result, setResult] = useState<DispatchCompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runDispatchProbe(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const drivers = safeJsonParse<DispatchDriverRequest[]>(driverJson, 'Drivers');
      const orders = safeJsonParse<DispatchOrderRequest[]>(orderJson, 'Orders');
      setResult(await compareDispatch({
        drivers,
        orders,
        matrix_algorithm: algorithm,
        use_cache: useCache,
        load_penalty_m: 0,
        slot_penalty_m: 0,
        return_cost_breakdown: returnCostBreakdown,
      }));
    } catch (requestError) {
      setResult(null);
      setError(requestError instanceof Error ? requestError.message : 'Dispatch probe failed.');
    } finally {
      setLoading(false);
    }
  }

  return <>
    <section className="engine-grid">
      <PanelSection title="Dispatch architecture" subtitle="Current source components behind assignment and road-network cost calculation.">
        <ArchitectureBlock label="Core" items={architecture?.core?.filter((item) => /dispatch|hungarian/i.test(item)) ?? []} />
        <ArchitectureBlock label="Services" items={architecture?.services?.filter((item) => /dispatch/i.test(item)) ?? []} />
        <ArchitectureBlock label="Infrastructure / runtime" items={[...(architecture?.infrastructure ?? []), ...(architecture?.middleware ?? [])].filter((item) => /redis|resilience|timeout|concurrency/i.test(item))} />
      </PanelSection>
      <PanelSection title="Dispatch chain" subtitle="Assignment is evaluated independently from delivery-order optimization.">
        <div className="engine-flow">
          <FlowNode eyebrow="01" title="Drivers + orders" detail="capacity + coordinates" />
          <span className="flow-arrow">→</span>
          <FlowNode eyebrow="02" title="Cost matrix" detail="Haversine or real directed roads" />
          <span className="flow-arrow">→</span>
          <FlowNode eyebrow="03" title="Greedy" detail="baseline assignment" />
          <span className="flow-arrow">→</span>
          <FlowNode eyebrow="04" title="Hungarian" detail="global assignment + fairness" />
        </div>
      </PanelSection>
    </section>

    <section className="engine-grid engine-grid-top">
      <PanelSection title="Dispatch probe input — PROBE" subtitle="Structured inputs make the engineering operation reproducible.">
        <label className="field-label">Drivers JSON<textarea className="engineering-code-input" value={driverJson} onChange={(event) => setDriverJson(event.target.value)} rows={9} /></label>
        <label className="field-label">Orders JSON<textarea className="engineering-code-input" value={orderJson} onChange={(event) => setOrderJson(event.target.value)} rows={8} /></label>
        <div className="option-grid">
          <label className="field-label">Cost source<select value={algorithm} onChange={(event) => setAlgorithm(event.target.value as typeof algorithm)}><option value="haversine">Haversine</option><option value="source_dijkstra">Source Dijkstra / road network</option></select></label>
          <div>
            <label className="toggle-row"><input type="checkbox" checked={useCache} onChange={(event) => setUseCache(event.target.checked)} /> Enable cache</label>
            <label className="toggle-row"><input type="checkbox" checked={returnCostBreakdown} onChange={(event) => setReturnCostBreakdown(event.target.checked)} /> Return cost breakdown</label>
          </div>
        </div>
        <button className="primary-button" type="button" onClick={() => void runDispatchProbe()} disabled={loading}>{loading ? 'Running…' : 'Run dispatch comparison'}</button>
        {error && <div className="error-box">{error}</div>}
      </PanelSection>
      <PanelSection title="Dispatch result — PROBE" subtitle="Actual /dispatch/compare response.">
        {result ? <>
          <div className="metric-grid metric-grid-4">
            <Metric label="Drivers" value={formatNumber(result.driver_count)} />
            <Metric label="Orders" value={formatNumber(result.order_count)} />
            <Metric label="Assigned" value={formatNumber(result.assigned_order_count)} />
            <Metric label="Unassigned" value={formatNumber(result.unassigned_order_count)} />
            <Metric label="Greedy cost" value={`${formatMetric(result.greedy.total_cost)} m`} />
            <Metric label="Hungarian cost" value={`${formatMetric(result.hungarian.total_cost)} m`} />
            <Metric label="Saved" value={`${formatMetric(result.comparison.hungarian_vs_greedy_cost_saved)} m`} />
            <Metric label="Improvement" value={`${formatMetric(result.comparison.hungarian_vs_greedy_improvement_pct)}%`} />
          </div>
          <div className="detail-list">
            <div className="key-value"><span>Hungarian non-regression</span><strong>{String(result.comparison.hungarian_non_regression)}</strong></div>
            <div className="key-value"><span>Hungarian fairness</span><strong>{formatMetric(result.hungarian_fairness.fairness_score)}</strong></div>
            <div className="key-value"><span>Cost matrix build</span><strong>{formatMilliseconds(result.cost_matrix_build_time_ms)}</strong></div>
            <div className="key-value"><span>Total time</span><strong>{formatMilliseconds(result.total_time_ms)}</strong></div>
            <div className="key-value"><span>Cache</span><strong>{result.cache_status ?? '—'} · hit={String(result.cache_hit)}</strong></div>
          </div>
          {result.road_network && <pre className="dark-inspector">{JSON.stringify(result.road_network, null, 2)}</pre>}
        </> : <div className="empty-state">Run the probe to inspect an actual dispatch response.</div>}
      </PanelSection>
    </section>
  </>;
}

function RuntimeView({ snapshot, runtime, architecture, evidence }: any) {
  const warningProbes = evidence.filter((item: EvidenceSummary) => !item.overall_ok);
  return <>
    <section className="engine-grid engine-grid-top">
      <PanelSection title="Lifecycle — LIVE" subtitle="Current /health + /health/live + /health/ready contracts.">
        <div className="metric-grid metric-grid-4">
          <Metric label="Readiness" value={snapshot.readiness?.status ?? '—'} />
          <Metric label="Uptime" value={formatSeconds(snapshot.readiness?.uptime_s)} />
          <Metric label="Startup complete" value={formatBool(snapshot.readiness?.startup_complete)} />
          <Metric label="Accepting requests" value={formatBool(snapshot.readiness?.accepting_requests)} />
          <Metric label="Shutdown" value={formatBool(snapshot.readiness?.shutting_down)} />
          <Metric label="Liveness" value={snapshot.liveness?.status ?? '—'} />
          <Metric label="Legacy health" value={snapshot.health?.status ?? '—'} />
          <Metric label="Phase" value={snapshot.root?.phase_code ?? '—'} mono />
        </div>
      </PanelSection>
      <PanelSection title="Admission / resilience — LIVE" subtitle="Prometheus runtime gauges/counters exposed by the backend.">
        <div className="metric-grid metric-grid-4">
          <Metric label="Active" value={formatMetric(runtime.active)} />
          <Metric label="Waiting" value={formatMetric(runtime.waiting)} />
          <Metric label="Max active" value={formatMetric(runtime.maxActive)} />
          <Metric label="Max waiting" value={formatMetric(runtime.maxWaiting)} />
          <Metric label="Rejections" value={formatMetric(runtime.rejections)} />
          <Metric label="Overload" value={formatMetric(runtime.overload)} />
          <Metric label="Redis" value={formatMetric(runtime.redis)} />
          <Metric label="Timeouts" value={formatMetric(runtime.timeouts)} />
        </div>
      </PanelSection>
    </section>
    <section className="engine-grid">
      <PanelSection title="Runtime source inventory" subtitle="Implementation components verified in the supplied source archive.">
        <ArchitectureBlock label="Core" items={architecture?.core?.filter((item: string) => /concurrency|timeout/i.test(item)) ?? []} />
        <ArchitectureBlock label="Middleware" items={architecture?.middleware ?? []} />
        <ArchitectureBlock label="Infrastructure" items={architecture?.infrastructure ?? []} />
        <ArchitectureBlock label="Observability" items={architecture?.observability ?? []} />
      </PanelSection>
      <PanelSection title="Current readiness semantics" subtitle="Only current readiness response is shown here.">
        {(snapshot.readiness?.degraded_dependencies?.length ?? 0) > 0 ? <div className="notice-box">Degraded dependencies: {snapshot.readiness.degraded_dependencies.join(', ')}</div> : <div className="success-box">No degraded dependencies reported by the current readiness endpoint.</div>}
        {(snapshot.readiness?.failure_reasons?.length ?? 0) > 0 && <div className="error-box"><strong>Current failure reasons</strong><ul>{snapshot.readiness.failure_reasons.map((reason: string) => <li key={reason}>{reason}</li>)}</ul></div>}
      </PanelSection>
    </section>
    <section className="engine-grid">
      <PanelSection title="Archived resilience probes" subtitle="Historical evidence, not current runtime state.">
        {warningProbes.length === 0 ? <div className="success-box">No warning-status Phase 11 probes are present in the supplied archive.</div> : warningProbes.map((item: EvidenceSummary) => <div className="benchmark-phase-row" key={item.benchmark}><div><strong>{item.benchmark}</strong><small>{item.validation_errors.length} validation issue(s) recorded in the historical artifact.</small></div><StatusPill label="ARCHIVE WARNING" state="warn" /></div>)}
      </PanelSection>
      <PanelSection title="What is intentionally not shown" subtitle="Avoiding invented platform telemetry.">
        <ul className="engineering-principles"><li>No synthetic CPU or memory charts.</li><li>No fabricated request rates or p95s.</li><li>No claim that an archived test run represents the current build.</li><li>No historical benchmark number is shown as live telemetry.</li></ul>
      </PanelSection>
    </section>
  </>;
}

function EvidenceView({ evidence, tests, benchmarkCatalog }: { evidence: EvidenceSummary[]; tests: TestInventory | null; benchmarkCatalog: Array<{ phase: string; file_count: number; json_count: number; python_count: number; text_count: number }> }) {
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [phaseFilter, setPhaseFilter] = useState<string>('all');
  const filtered = phaseFilter === 'all' ? evidence : evidence.filter((item) => item.phase_code === phaseFilter);
  const phase11Pass = evidence.filter((item) => item.overall_ok).length;
  const phase11Warn = evidence.length - phase11Pass;

  return <>
    <section className="engine-grid engine-grid-three">
      <PanelSection title="Phase 11 archive" subtitle="Supplied historical reliability probes.">
        <div className="metric-grid metric-grid-3"><Metric label="Probes" value={formatNumber(evidence.length)} /><Metric label="Recorded OK" value={formatNumber(phase11Pass)} /><Metric label="Recorded warning" value={formatNumber(phase11Warn)} /></div>
      </PanelSection>
      <PanelSection title="Test inventory" subtitle="Source-archive structure, not current pass/fail state.">
        <div className="metric-grid metric-grid-3"><Metric label="Modules" value={formatNumber(tests?.test_file_count)} /><Metric label="Explicit test_*" value={formatNumber(tests?.explicit_test_function_count)} /><Metric label="Recorded runs" value={formatNumber(tests?.recorded_run_counts?.length)} /></div>
      </PanelSection>
      <PanelSection title="Benchmark archive" subtitle="Artifact inventory from the supplied benchmark ZIP.">
        <div className="metric-grid metric-grid-3"><Metric label="Phases" value={formatNumber(benchmarkCatalog.length)} /><Metric label="Files" value={formatNumber(benchmarkCatalog.reduce((sum, item) => sum + item.file_count, 0))} /><Metric label="Probe Python" value={formatNumber(benchmarkCatalog.reduce((sum, item) => sum + item.python_count, 0))} /></div>
      </PanelSection>
    </section>

    <section className="engine-grid">
      <PanelSection title="Evidence explorer" subtitle="Validation errors and warnings remain intact instead of being converted to false PASS states.">
        <div className="segmented-control three">
          <button type="button" className={phaseFilter === 'all' ? 'segment-active' : ''} onClick={() => setPhaseFilter('all')}>All</button>
          <button type="button" className={phaseFilter === 'tier4_phase11' ? 'segment-active' : ''} onClick={() => setPhaseFilter('tier4_phase11')}>Tier 4 / 11</button>
          <button type="button" className={phaseFilter === 'tier4_phase10' ? 'segment-active' : ''} onClick={() => setPhaseFilter('tier4_phase10')}>Tier 4 / 10</button>
        </div>
        <div className="evidence-list">
          {filtered.map((item) => {
            const open = openEvidence === item.benchmark;
            return <div className="evidence-card" key={item.benchmark}>
              <button type="button" className="evidence-header" onClick={() => setOpenEvidence(open ? null : item.benchmark)}>
                <span><strong>{item.benchmark}</strong><small>{item.phase_code} · {item.target ?? 'artifact'}</small></span>
                <StatusPill label={item.overall_ok ? 'PASS' : 'WARNING'} state={item.overall_ok ? 'ok' : 'warn'} />
              </button>
              {open && <div className="evidence-body">
                <div className="evidence-paths"><CodeTag>{item.raw_result_path ?? 'no raw path'}</CodeTag><CodeTag>{item.summary_result_path ?? 'no summary path'}</CodeTag></div>
                {item.validation_errors.length > 0 && <div className="error-box"><strong>Recorded validation errors</strong><ul>{item.validation_errors.map((message) => <li key={message}>{message}</li>)}</ul></div>}
                {item.warnings.length > 0 && <div className="notice-box"><strong>Recorded warnings</strong><ul>{item.warnings.map((message) => <li key={message}>{message}</li>)}</ul></div>}
                <pre className="evidence-json">{JSON.stringify(item.details, null, 2)}</pre>
              </div>}
            </div>;
          })}
        </div>
      </PanelSection>
      <PanelSection title="Benchmark phase inventory" subtitle="The archive is evidence of artifacts, not proof that every artifact passed.">
        <div className="benchmark-phase-list">{benchmarkCatalog.map((item) => <div className="benchmark-phase-row" key={item.phase}><div><strong>{item.phase}</strong><small>{item.file_count} files · {item.json_count} JSON · {item.python_count} Python · {item.text_count} text</small></div><CodeTag>ARCHIVE</CodeTag></div>)}</div>
      </PanelSection>
    </section>

    <section className="engine-grid">
      <PanelSection title="Recorded historical test runs" subtitle="Only runs explicitly recorded inside supplied artifacts.">
        <div className="recorded-runs">{tests?.recorded_run_counts?.map((item) => <div className="recorded-run" key={item.source}><CodeTag>{item.source}</CodeTag><strong>{item.passed === null ? 'count unavailable' : `${item.passed} passed`}</strong></div>)}</div>
        <div className="notice-box">{tests?.note ?? 'No additional test inventory note supplied.'}</div>
      </PanelSection>
      <PanelSection title="Evidence rules" subtitle="What this dashboard refuses to claim.">
        <ul className="engineering-principles"><li>Archive ≠ live state.</li><li>Source inventory ≠ execution proof.</li><li>Explicit test definitions ≠ current passed count.</li><li>Historical warnings stay attached to the exact artifact that reported them.</li><li>Missing current evidence is shown as missing, not inferred.</li></ul>
      </PanelSection>
    </section>
  </>;
}

function MatrixProbeResult({ result }: { result: MatrixResponse }) {
  return <div className="matrix-probe-result">
    <div className="metric-grid metric-grid-4" style={{ marginTop: 8 }}>
      <Metric label="N" value={formatNumber(result.n)} />
      <Metric label="Pairs" value={formatNumber(result.pair_count)} />
      <Metric label="Computed" value={formatNumber(result.computed_pairs)} />
      <Metric label="Failed" value={formatNumber(result.failed_pairs)} />
      <Metric label="Generation" value={formatMilliseconds(result.generation_time_ms)} />
      <Metric label="Workers" value={formatNumber(result.parallel_workers)} />
      <Metric label="Cache" value={result.cache.hit ? 'HIT' : result.cache.enabled ? 'MISS' : 'DISABLED'} />
      <Metric label="Algorithm" value={result.algorithm} mono />
    </div>
    <div className="matrix-wrap">
      <table><thead><tr><th />{result.locations.map((location) => <th key={location.id}>{location.id}</th>)}</tr></thead><tbody>{result.matrix_distance_m.map((row, rowIndex) => <tr key={result.locations[rowIndex]?.id ?? rowIndex}><th>{result.locations[rowIndex]?.id ?? rowIndex}</th>{row.map((value, columnIndex) => <td key={columnIndex}>{value === null ? '∅' : Math.round(value).toLocaleString()}</td>)}</tr>)}</tbody></table>
    </div>
    {result.failures.length > 0 && <div className="error-box" style={{ marginTop: 8 }}>Failed pairs: {result.failures.map((failure) => `${failure.from_id}→${failure.to_id}: ${failure.error}`).join(' · ')}</div>}
  </div>;
}

function FlowNode({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return <div className="flow-node"><span>{eyebrow}</span><strong>{title}</strong><small>{detail}</small></div>;
}

function StackStage({ label, detail }: { label: string; detail: string }) {
  return <div className="stack-stage"><strong>{label}</strong><span>{detail}</span></div>;
}

function EngineTile({ title, code, description, onClick }: { title: string; code: string; description: string; onClick: () => void }) {
  return <button type="button" className="engine-tile" onClick={onClick}><div><span className="engine-tile-code">{code}</span><h3>{title}</h3><p>{description}</p></div><span className="engine-tile-arrow">↗</span></button>;
}

function ArchitectureBlock({ label, items }: { label: string; items: string[] }) {
  return <div className="architecture-block"><div className="architecture-label">{label}</div><div className="tag-cloud">{items.length === 0 ? <span className="source-note">No supplied source entry.</span> : items.map((item) => <CodeTag key={item}>{item}</CodeTag>)}</div></div>;
}

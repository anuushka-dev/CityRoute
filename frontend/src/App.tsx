import { useEffect, useMemo, useState } from 'react';
import { compareAdvancedStops, compareDispatch, compareRoute, createMatrix, getGraphStats, getReadiness, getRoute, snapGraphCoordinate, validateGraphCoordinate, optimizeStops, compareStops } from './api/cityRouteApi';
import { EngineeringDashboard } from './engineering/EngineeringDashboard';
import { MapView } from './components/MapView';
import { Metric } from './components/Metric';
import { CodeTag, PanelSection, StatusPill } from './components/PanelPrimitives';
import type { AdvancedCompareResponse, Coordinate, DispatchCompareResponse, DispatchDriverRequest, DispatchMarker, DispatchMatrixAlgorithm, DispatchOrderRequest, GraphStatsResponse, MatrixResponse, RouteComparisonResponse, RouteResponse, RouteSegment, VrpCompareResponse, VrpGreedyResponse, VrpMatrixAlgorithm, VrpStrategy } from './types/domain';
import { formatDistance, formatMilliseconds, formatNumber, formatPct, formatSeconds } from './utils/format';
import { CITYROUTE_BOUNDS, isInsideCityRouteBounds } from './utils/validation';

const MAX_VRP_STOPS = 24;
const MAX_MATRIX_LOCATIONS = 25;
const DEFAULT_ROUTE_COMPARE = false;
const DEFAULT_RETURN_TO_START = false;
const DEFAULT_VRP_MATRIX_ALGORITHM: VrpMatrixAlgorithm = 'source_dijkstra';
const DEFAULT_DISPATCH_MATRIX_ALGORITHM: DispatchMatrixAlgorithm = 'haversine';
const DEFAULT_USE_CACHE = true;
const DEFAULT_LNS_ITERATIONS = 500;
const DEFAULT_LNS_DESTROY_FRACTION = 0.3;
const DEFAULT_LNS_NO_IMPROVEMENT_LIMIT = 100;
const DEFAULT_TWO_OPT_ITERATIONS = 100;
const DEFAULT_TWO_OPT_TOLERANCE_M = 0.001;
const DEFAULT_DRIVER_CAPACITY = 1;
const DEFAULT_DRIVER_LOAD = 0;
const DEFAULT_LOAD_PENALTY_M = 0;
const DEFAULT_SLOT_PENALTY_M = 0;
const MAP_ROUTE_LIMIT = MAX_MATRIX_LOCATIONS - 1;

type Page = 'product' | 'engineering';
type ProductMode = 'route' | 'deliveries' | 'dispatch' | 'operations';
type PickTarget = 'start' | 'end' | 'stop' | 'driver' | 'order';
type AssignmentView = 'hungarian' | 'greedy';
type MatrixView = 'distance' | 'eta';

interface OperationDriverPlan {
  driverId: string;
  assignedOrderIds: string[];
  optimizedOrderIds: string[];
  totalDistanceMeters: number;
  routeSegments: RouteSegment[];
  optimizationTimeMs: number | null;
  strategy: VrpStrategy;
}

export default function App() {
  const [page, setPage] = useState<Page>('product');
  const [mode, setMode] = useState<ProductMode>('route');
  const [pickTarget, setPickTarget] = useState<PickTarget>('start');

  const [start, setStart] = useState<Coordinate | null>(null);
  const [end, setEnd] = useState<Coordinate | null>(null);
  const [stops, setStops] = useState<Coordinate[]>([]);
  const [drivers, setDrivers] = useState<DispatchDriverRequest[]>([]);
  const [orders, setOrders] = useState<DispatchOrderRequest[]>([]);

  const [routeResponse, setRouteResponse] = useState<RouteResponse | null>(null);
  const [routeComparison, setRouteComparison] = useState<RouteComparisonResponse | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeCompareLoading, setRouteCompareLoading] = useState(false);

  const [vrpStrategy, setVrpStrategy] = useState<VrpStrategy>('greedy');
  const [returnToStart, setReturnToStart] = useState(DEFAULT_RETURN_TO_START);
  const [vrpMatrixAlgorithm, setVrpMatrixAlgorithm] = useState<VrpMatrixAlgorithm>(DEFAULT_VRP_MATRIX_ALGORITHM);
  const [useVrpCache, setUseVrpCache] = useState(DEFAULT_USE_CACHE);
  const [vrpLoading, setVrpLoading] = useState(false);
  const [greedyResponse, setGreedyResponse] = useState<VrpGreedyResponse | null>(null);
  const [vrpComparison, setVrpComparison] = useState<VrpCompareResponse | null>(null);
  const [advancedComparison, setAdvancedComparison] = useState<AdvancedCompareResponse | null>(null);
  const [selectedVrpStrategy, setSelectedVrpStrategy] = useState<VrpStrategy>('greedy');
  const [routeSegments, setRouteSegments] = useState<RouteSegment[]>([]);
  const [keepOptimizationTrace, setKeepOptimizationTrace] = useState(true);

  const [matrixResponse, setMatrixResponse] = useState<MatrixResponse | null>(null);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [matrixView, setMatrixView] = useState<MatrixView>('distance');

  const [dispatchMatrixAlgorithm, setDispatchMatrixAlgorithm] = useState<DispatchMatrixAlgorithm>(DEFAULT_DISPATCH_MATRIX_ALGORITHM);
  const [useDispatchCache, setUseDispatchCache] = useState(DEFAULT_USE_CACHE);
  const [assignmentView, setAssignmentView] = useState<AssignmentView>('hungarian');
  const [dispatchResponse, setDispatchResponse] = useState<DispatchCompareResponse | null>(null);
  const [dispatchLoading, setDispatchLoading] = useState(false);
  const [dispatchLines, setDispatchLines] = useState<Array<{ from: Coordinate; to: Coordinate; id: string }>>([]);

  const [operationsOrigin, setOperationsOrigin] = useState<Coordinate | null>(null);
  const [operationDrivers, setOperationDrivers] = useState<DispatchDriverRequest[]>([]);
  const [operationOrders, setOperationOrders] = useState<DispatchOrderRequest[]>([]);
  const [operationDispatchResponse, setOperationDispatchResponse] = useState<DispatchCompareResponse | null>(null);
  const [operationPlan, setOperationPlan] = useState<OperationDriverPlan[]>([]);
  const [operationSegments, setOperationSegments] = useState<RouteSegment[]>([]);
  const [operationLoading, setOperationLoading] = useState(false);
  const [operationMatrixAlgorithm, setOperationMatrixAlgorithm] = useState<DispatchMatrixAlgorithm>('haversine');
  const [operationVrpStrategy, setOperationVrpStrategy] = useState<VrpStrategy>('lns');
  const [operationVrpMatrixAlgorithm, setOperationVrpMatrixAlgorithm] = useState<VrpMatrixAlgorithm>('source_dijkstra');
  const [operationUseCache, setOperationUseCache] = useState(true);
  const [operationReturnToStart, setOperationReturnToStart] = useState(false);
  const [operationDriverCapacity, setOperationDriverCapacity] = useState(4);
  const [operationDispatchLines, setOperationDispatchLines] = useState<Array<{ from: Coordinate; to: Coordinate; id: string }>>([]);
  const [readinessReady, setReadinessReady] = useState<boolean | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);
  const [routeTechnicalDetailsOpen, setRouteTechnicalDetailsOpen] = useState(false);
  const [deliveryDetailsOpen, setDeliveryDetailsOpen] = useState(false);
  const [dispatchDetailsOpen, setDispatchDetailsOpen] = useState(false);

  const [probeCoordinate, setProbeCoordinate] = useState<Coordinate>({ lat: CITYROUTE_BOUNDS.south + 0.02, lon: CITYROUTE_BOUNDS.west + 0.05 });
  const [probeResult, setProbeResult] = useState<Record<string, unknown> | null>(null);
  const [graphStats, setGraphStats] = useState<GraphStatsResponse | null>(null);
  const [graphStatsLoading, setGraphStatsLoading] = useState(false);

  useEffect(() => {
    getReadiness().then((response) => setReadinessReady(response.ready)).catch(() => setReadinessReady(false));
  }, []);

  const mapLocations = useMemo(() => {
    if (mode === 'route') return [
      ...(start ? [{ id: 'route-start', label: 'Start', coordinate: start }] : []),
      ...(end ? [{ id: 'route-end', label: 'Destination', coordinate: end }] : []),
    ];
    if (mode === 'deliveries') return [
      ...(start ? [{ id: 'depot', label: 'Start / Depot', coordinate: start }] : []),
      ...stops.map((stop, index) => ({ id: `stop-${index}`, label: `Stop ${index + 1}`, coordinate: stop })),
    ];
    if (mode === 'operations') return [
      ...(operationsOrigin ? [{ id: 'operations-origin', label: 'Origin / Start', coordinate: operationsOrigin }] : []),
    ];
    return [];
  }, [mode, start, end, stops, operationsOrigin]);

  const driverMarkers = useMemo<DispatchMarker[]>(() => drivers.map((driver) => ({ id: driver.driver_id, label: driver.driver_id, coordinate: { lat: driver.lat, lon: driver.lon } })), [drivers]);
  const orderMarkers = useMemo<DispatchMarker[]>(() => orders.map((order) => ({ id: order.order_id, label: order.order_id, coordinate: { lat: order.pickup_lat, lon: order.pickup_lon } })), [orders]);
  const operationDriverMarkers = useMemo<DispatchMarker[]>(() => operationDrivers.map((driver) => ({ id: driver.driver_id, label: driver.driver_id, coordinate: { lat: driver.lat, lon: driver.lon } })), [operationDrivers]);
  const operationOrderMarkers = useMemo<DispatchMarker[]>(() => operationOrders.map((order) => ({ id: order.order_id, label: order.order_id, coordinate: { lat: order.pickup_lat, lon: order.pickup_lon } })), [operationOrders]);

  const routeGeometry = routeComparison?.astar.geometry ?? routeResponse?.geometry ?? [];
  const comparisonGeometry = routeComparison?.bidirectional_astar.geometry ?? [];

  function resetProductResultState(): void {
    setMapError(null);
    setRouteResponse(null);
    setRouteComparison(null);
    setGreedyResponse(null);
    setVrpComparison(null);
    setAdvancedComparison(null);
    setSelectedVrpStrategy(vrpStrategy);
    setRouteSegments([]);
    setMatrixResponse(null);
    setDispatchResponse(null);
    setDispatchLines([]);
  }

  function handleMapSelect(coordinate: Coordinate): void {
    if (!isInsideCityRouteBounds(coordinate)) {
      setMapError(`Coordinate outside loaded graph area. Allowed bbox: ${CITYROUTE_BOUNDS.west}–${CITYROUTE_BOUNDS.east} longitude, ${CITYROUTE_BOUNDS.south}–${CITYROUTE_BOUNDS.north} latitude.`);
      return;
    }
    setMapError(null);

    if (mode === 'route') {
      if (pickTarget === 'start') { setStart(coordinate); setPickTarget('end'); return; }
      setEnd(coordinate);
      return;
    }
    if (mode === 'operations') {
      if (pickTarget === 'start') { setOperationsOrigin(coordinate); setPickTarget('driver'); return; }
      if (pickTarget === 'driver') {
        setOperationDrivers((current) => [...current, { driver_id: `Driver ${current.length + 1}`, lat: coordinate.lat, lon: coordinate.lon, current_load: 0, max_capacity: operationDriverCapacity }]);
        return;
      }
      setOperationOrders((current) => [...current, { order_id: `Order ${current.length + 1}`, pickup_lat: coordinate.lat, pickup_lon: coordinate.lon }]);
      return;
    }
    if (mode === 'deliveries') {
      if (pickTarget === 'start') { setStart(coordinate); setPickTarget('stop'); return; }
      if (stops.length >= MAX_VRP_STOPS) { setMapError(`CityRoute allows a maximum of ${MAX_VRP_STOPS} delivery stops.`); return; }
      setStops((current) => [...current, coordinate]);
      return;
    }
    if (pickTarget === 'driver') {
      setDrivers((current) => [...current, { driver_id: `Driver ${current.length + 1}`, lat: coordinate.lat, lon: coordinate.lon, current_load: DEFAULT_DRIVER_LOAD, max_capacity: DEFAULT_DRIVER_CAPACITY }]);
      setPickTarget('order');
      return;
    }
    setOrders((current) => [...current, { order_id: `Order ${current.length + 1}`, pickup_lat: coordinate.lat, pickup_lon: coordinate.lon }]);
  }

  function switchMode(nextMode: ProductMode): void {
    setMode(nextMode);
    setMapError(null);
    if (nextMode === 'route') setPickTarget(start ? 'end' : 'start');
    if (nextMode === 'deliveries') setPickTarget(start ? 'stop' : 'start');
    if (nextMode === 'dispatch') setPickTarget(drivers.length > 0 ? 'order' : 'driver');
    if (nextMode === 'operations') setPickTarget(operationsOrigin ? 'driver' : 'start');
  }

  async function calculateRoute(): Promise<void> {
    if (!start || !end) return;
    setMapError(null); setRouteLoading(true); setRouteComparison(null);
    try { setRouteResponse(await getRoute(start, end)); }
    catch (error) { setRouteResponse(null); setMapError(error instanceof Error ? error.message : 'Route calculation failed.'); }
    finally { setRouteLoading(false); }
  }

  async function compareRoutingAlgorithms(): Promise<void> {
    if (!start || !end) return;
    setMapError(null); setRouteCompareLoading(true);
    try { setRouteComparison(await compareRoute(start, end)); }
    catch (error) { setRouteComparison(null); setMapError(error instanceof Error ? error.message : 'Routing comparison failed.'); }
    finally { setRouteCompareLoading(false); }
  }

  async function runDeliveries(): Promise<void> {
    if (!start || stops.length === 0) return;
    setVrpLoading(true); setMapError(null); setRouteSegments([]); setMatrixResponse(null);
    try {
      if (vrpStrategy === 'greedy') {
        const response = await optimizeStops({ start, stops, return_to_start: returnToStart, matrix_algorithm: vrpMatrixAlgorithm, use_cache: useVrpCache });
        setGreedyResponse(response); setVrpComparison(null); setAdvancedComparison(null); setSelectedVrpStrategy('greedy');
        await drawStopOrder(response.optimized_order);
      } else if (vrpStrategy === 'two_opt') {
        const response = await compareStops({ start, stops, return_to_start: returnToStart, matrix_algorithm: vrpMatrixAlgorithm, use_cache: useVrpCache, ttl_seconds: null, two_opt_max_iterations: DEFAULT_TWO_OPT_ITERATIONS, improvement_tolerance_m: DEFAULT_TWO_OPT_TOLERANCE_M, keep_trace: keepOptimizationTrace });
        setVrpComparison(response); setGreedyResponse(null); setAdvancedComparison(null); setSelectedVrpStrategy('two_opt');
        await drawStopOrder(response.two_opt.optimized_order);
      } else {
        const response = await compareAdvancedStops({ start, stops, return_to_start: returnToStart, matrix_algorithm: vrpMatrixAlgorithm, use_cache: useVrpCache, two_opt_max_iterations: DEFAULT_TWO_OPT_ITERATIONS, two_opt_improvement_tolerance_m: DEFAULT_TWO_OPT_TOLERANCE_M, lns_max_iterations: DEFAULT_LNS_ITERATIONS, lns_destroy_fraction: DEFAULT_LNS_DESTROY_FRACTION, lns_no_improvement_limit: DEFAULT_LNS_NO_IMPROVEMENT_LIMIT, lns_random_seed: 42, keep_trace: keepOptimizationTrace });
        setAdvancedComparison(response); setGreedyResponse(null); setVrpComparison(null); setSelectedVrpStrategy('lns');
        await drawStopOrder(response.lns.optimized_order);
      }
    } catch (error) { setMapError(error instanceof Error ? error.message : 'Delivery optimization failed.'); }
    finally { setVrpLoading(false); }
  }

  async function drawStopOrder(order: number[]): Promise<void> {
    if (!start) return;
    let current = start;
    const ordered = order.map((index) => stops[index]).filter(Boolean);
    const targets = returnToStart ? [...ordered, start] : ordered;
    const segments: RouteSegment[] = [];
    for (const target of targets) {
      const route = await getRoute(current, target);
      segments.push({ id: `delivery-${segments.length}`, geometry: route.geometry });
      current = target;
    }
    setRouteSegments(segments);
  }

  async function generateMatrix(): Promise<void> {
    if (!start || stops.length === 0 || stops.length + 1 > MAX_MATRIX_LOCATIONS) return;
    setMatrixLoading(true); setMapError(null);
    try {
      const locations = [{ id: 'depot', ...start }, ...stops.map((coordinate, index) => ({ id: `stop-${index + 1}`, ...coordinate }))];
      setMatrixResponse(await createMatrix({ locations, algorithm: vrpMatrixAlgorithm, use_cache: useVrpCache }));
    } catch (error) { setMatrixResponse(null); setMapError(error instanceof Error ? error.message : 'Matrix generation failed.'); }
    finally { setMatrixLoading(false); }
  }

  async function runDispatch(): Promise<void> {
    if (drivers.length === 0 || orders.length === 0) return;
    setDispatchLoading(true); setMapError(null);
    try {
      const response = await compareDispatch({ drivers, orders, matrix_algorithm: dispatchMatrixAlgorithm, use_cache: useDispatchCache, load_penalty_m: DEFAULT_LOAD_PENALTY_M, slot_penalty_m: DEFAULT_SLOT_PENALTY_M, return_cost_breakdown: true });
      setDispatchResponse(response); setAssignmentView('hungarian'); setDispatchLines(buildDispatchLines(response.hungarian.assignments));
    } catch (error) { setDispatchResponse(null); setDispatchLines([]); setMapError(error instanceof Error ? error.message : 'Dispatch comparison failed.'); }
    finally { setDispatchLoading(false); }
  }

  async function buildOperationOptimizationOrder(stops: Coordinate[]): Promise<{ order: number[]; distanceMeters: number; timeMs: number }> {
    if (!operationsOrigin) throw new Error('Operations origin is required.');
    if (operationVrpStrategy === 'greedy') {
      const response = await optimizeStops({ start: operationsOrigin, stops, return_to_start: operationReturnToStart, matrix_algorithm: operationVrpMatrixAlgorithm, use_cache: operationUseCache });
      return { order: response.optimized_order, distanceMeters: response.total_distance_m, timeMs: response.optimization_time_ms };
    }
    if (operationVrpStrategy === 'two_opt') {
      const response = await compareStops({ start: operationsOrigin, stops, return_to_start: operationReturnToStart, matrix_algorithm: operationVrpMatrixAlgorithm, use_cache: operationUseCache, ttl_seconds: null, two_opt_max_iterations: DEFAULT_TWO_OPT_ITERATIONS, improvement_tolerance_m: DEFAULT_TWO_OPT_TOLERANCE_M, keep_trace: false });
      return { order: response.two_opt.optimized_order, distanceMeters: response.two_opt.total_distance_m, timeMs: response.two_opt.optimization_time_ms };
    }
    const response = await compareAdvancedStops({ start: operationsOrigin, stops, return_to_start: operationReturnToStart, matrix_algorithm: operationVrpMatrixAlgorithm, use_cache: operationUseCache, two_opt_max_iterations: DEFAULT_TWO_OPT_ITERATIONS, two_opt_improvement_tolerance_m: DEFAULT_TWO_OPT_TOLERANCE_M, lns_max_iterations: DEFAULT_LNS_ITERATIONS, lns_destroy_fraction: DEFAULT_LNS_DESTROY_FRACTION, lns_no_improvement_limit: DEFAULT_LNS_NO_IMPROVEMENT_LIMIT, lns_random_seed: 42, keep_trace: false });
    return { order: response.lns.optimized_order, distanceMeters: response.lns.total_distance_m, timeMs: response.lns.optimization_time_ms };
  }

  function buildOperationDispatchLines(assignments: Array<{ driver_id: string; order_id: string }>): Array<{ from: Coordinate; to: Coordinate; id: string }> {
    return assignments.flatMap((assignment) => {
      const driver = operationDrivers.find((candidate) => candidate.driver_id === assignment.driver_id);
      const order = operationOrders.find((candidate) => candidate.order_id === assignment.order_id);
      if (!driver || !order) return [];
      return [{ id: `operation-assignment-${assignment.driver_id}-${assignment.order_id}`, from: { lat: driver.lat, lon: driver.lon }, to: { lat: order.pickup_lat, lon: order.pickup_lon } }];
    });
  }

  async function runOperationsPlan(): Promise<void> {
    if (!operationsOrigin || operationDrivers.length === 0 || operationOrders.length === 0) return;
    const operationsStart = operationsOrigin;
    setOperationLoading(true);
    setMapError(null);
    setOperationPlan([]);
    setOperationSegments([]);
    try {
      const dispatch = await compareDispatch({
        drivers: operationDrivers,
        orders: operationOrders,
        matrix_algorithm: operationMatrixAlgorithm,
        use_cache: operationUseCache,
        load_penalty_m: DEFAULT_LOAD_PENALTY_M,
        slot_penalty_m: DEFAULT_SLOT_PENALTY_M,
        return_cost_breakdown: true,
      });
      setOperationDispatchResponse(dispatch);
      setOperationDispatchLines(buildOperationDispatchLines(dispatch.hungarian.assignments));

      const assignmentsByDriver = new Map<string, DispatchOrderRequest[]>();
      for (const assignment of dispatch.hungarian.assignments) {
        const order = operationOrders.find((candidate) => candidate.order_id === assignment.order_id);
        if (!order) continue;
        const current = assignmentsByDriver.get(assignment.driver_id) ?? [];
        assignmentsByDriver.set(assignment.driver_id, [...current, order]);
      }

      const plans: OperationDriverPlan[] = [];
      const allSegments: RouteSegment[] = [];
      for (const driver of operationDrivers) {
        const assignedOrders = assignmentsByDriver.get(driver.driver_id) ?? [];
        if (assignedOrders.length === 0) {
          plans.push({ driverId: driver.driver_id, assignedOrderIds: [], optimizedOrderIds: [], totalDistanceMeters: 0, routeSegments: [], optimizationTimeMs: null, strategy: operationVrpStrategy });
          continue;
        }

        const stopsForDriver = assignedOrders.map((order) => ({ lat: order.pickup_lat, lon: order.pickup_lon }));
        const optimizedOrder = await buildOperationOptimizationOrder(stopsForDriver);
        const optimizedOrders = optimizedOrder.order.map((index) => assignedOrders[index]).filter(Boolean);
        let current = operationsStart;
        const segments: RouteSegment[] = [];
        const targets = operationReturnToStart ? [...optimizedOrders.map((order) => ({ lat: order.pickup_lat, lon: order.pickup_lon })), current] : optimizedOrders.map((order) => ({ lat: order.pickup_lat, lon: order.pickup_lon }));
        for (const target of targets) {
          const route = await getRoute(current, target);
          const segment = { id: `operation-${driver.driver_id}-${segments.length}`, geometry: route.geometry };
          segments.push(segment);
          allSegments.push(segment);
          current = target;
        }

        plans.push({
          driverId: driver.driver_id,
          assignedOrderIds: assignedOrders.map((order) => order.order_id),
          optimizedOrderIds: optimizedOrders.map((order) => order.order_id),
          totalDistanceMeters: optimizedOrder.distanceMeters,
          routeSegments: segments,
          optimizationTimeMs: optimizedOrder.timeMs,
          strategy: operationVrpStrategy,
        });
      }

      setOperationPlan(plans);
      setOperationSegments(allSegments);
    } catch (error) {
      setMapError(error instanceof Error ? error.message : 'Operations plan failed.');
    } finally {
      setOperationLoading(false);
    }
  }

  function buildDispatchLines(assignments: Array<{ driver_id: string; order_id: string }>): Array<{ from: Coordinate; to: Coordinate; id: string }> {
    return assignments.flatMap((assignment) => {
      const driver = drivers.find((candidate) => candidate.driver_id === assignment.driver_id);
      const order = orders.find((candidate) => candidate.order_id === assignment.order_id);
      if (!driver || !order) return [];
      return [{ id: `${assignment.driver_id}-${assignment.order_id}`, from: { lat: driver.lat, lon: driver.lon }, to: { lat: order.pickup_lat, lon: order.pickup_lon } }];
    });
  }

  function setAssignment(next: AssignmentView): void {
    setAssignmentView(next);
    if (dispatchResponse) setDispatchLines(buildDispatchLines(dispatchResponse[next].assignments));
  }

  async function probeGraph(): Promise<void> {
    setGraphStatsLoading(true); setMapError(null); setProbeResult(null);
    try {
      const [stats, validation, snap] = await Promise.all([getGraphStats(), validateGraphCoordinate(probeCoordinate), snapGraphCoordinate(probeCoordinate)]);
      setGraphStats(stats); setProbeResult({ validation, snap });
    } catch (error) { setMapError(error instanceof Error ? error.message : 'Graph probe failed.'); }
    finally { setGraphStatsLoading(false); }
  }

  const routeDetail = routeComparison?.astar ?? routeResponse;
  const selectedVrp = vrpStrategy === 'greedy' ? greedyResponse : vrpStrategy === 'two_opt' ? vrpComparison?.two_opt : advancedComparison?.lns;
  const selectedVrpOrder = selectedVrp?.optimized_order ?? [];
  const selectedVrpDistance = selectedVrp?.total_distance_m ?? null;
  const selectedVrpTime = selectedVrp?.optimization_time_ms ?? null;
  const dispatchResult = dispatchResponse?.[assignmentView] ?? null;
  const dispatchFairness = assignmentView === 'hungarian' ? dispatchResponse?.hungarian_fairness : dispatchResponse?.greedy_fairness;

  const operationAssignedCount = operationDispatchResponse?.hungarian.assigned_count ?? 0;
  const operationUnassignedCount = operationDispatchResponse?.hungarian.unassigned_order_ids.length ?? 0;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block"><span className="brand-mark">C</span><div><h1>CityRoute</h1><p>Open-source last-mile routing & dispatch engine</p></div></div>
        <div className="topbar-controls">
          <nav className="page-switch"><button type="button" className={page === 'product' ? 'page-switch-active' : ''} onClick={() => setPage('product')}>Product</button><button type="button" className={page === 'engineering' ? 'page-switch-active' : ''} onClick={() => setPage('engineering')}>Engineering</button></nav>
          <StatusPill label={readinessReady === true ? 'Backend ready' : readinessReady === false ? 'Backend unavailable' : 'Checking'} state={readinessReady === true ? 'ok' : readinessReady === false ? 'bad' : 'neutral'} />
        </div>
      </header>

      {page === 'engineering' ? <EngineeringDashboard /> : (
        <section className="product-workspace">
          <aside className="product-sidebar">
            <div className="mode-tabs mode-tabs-four"><button type="button" className={mode === 'route' ? 'mode-tab-active' : ''} onClick={() => switchMode('route')}>Route</button><button type="button" className={mode === 'deliveries' ? 'mode-tab-active' : ''} onClick={() => switchMode('deliveries')}>Deliveries</button><button type="button" className={mode === 'dispatch' ? 'mode-tab-active' : ''} onClick={() => switchMode('dispatch')}>Dispatch</button><button type="button" className={mode === 'operations' ? 'mode-tab-active' : ''} onClick={() => switchMode('operations')}>Operations</button></div>
            {mapError && <div className="error-box global-error">{mapError}</div>}
            {mode === 'route' && <RouteProductPanel {...{ start, end, pickTarget, routeResponse, routeComparison, routeDetail, routeLoading, routeCompareLoading, routeTechnicalDetailsOpen, setRouteTechnicalDetailsOpen, calculateRoute, compareRoutingAlgorithms, setPickTarget }} />}
            {mode === 'deliveries' && <DeliveriesProductPanel {...{ start, stops, pickTarget, vrpStrategy, vrpMatrixAlgorithm, useVrpCache, returnToStart, keepOptimizationTrace, selectedVrp, selectedVrpOrder, selectedVrpDistance, selectedVrpTime, greedyResponse, vrpComparison, advancedComparison, matrixResponse, matrixView, setMatrixView, vrpLoading, matrixLoading, deliveryDetailsOpen, setDeliveryDetailsOpen, setVrpStrategy, setVrpMatrixAlgorithm, setUseVrpCache, setReturnToStart, setKeepOptimizationTrace, runDeliveries, generateMatrix, setPickTarget, setStops, setStart, setMatrixResponse, setSelectedVrpStrategy: setSelectedVrpStrategy, selectedVrpStrategy }} />}
            {mode === 'dispatch' && <DispatchProductPanel {...{ drivers, orders, pickTarget, dispatchMatrixAlgorithm, useDispatchCache, dispatchResponse, dispatchResult, dispatchFairness, assignmentView, dispatchLoading, dispatchDetailsOpen, setDispatchDetailsOpen, setDispatchMatrixAlgorithm, setUseDispatchCache, setAssignment, runDispatch, setPickTarget, setDrivers, setOrders, setDispatchResponse, setDispatchLines }} />}
            {mode === 'operations' && <OperationsProductPanel origin={operationsOrigin} drivers={operationDrivers} orders={operationOrders} pickTarget={pickTarget} matrixAlgorithm={operationMatrixAlgorithm} useCache={operationUseCache} returnToStart={operationReturnToStart} driverCapacity={operationDriverCapacity} vrpStrategy={operationVrpStrategy} vrpMatrixAlgorithm={operationVrpMatrixAlgorithm} onVrpStrategyChange={setOperationVrpStrategy} onVrpMatrixAlgorithmChange={setOperationVrpMatrixAlgorithm} onDriverCapacityChange={setOperationDriverCapacity} dispatchResponse={operationDispatchResponse} plan={operationPlan} assignedCount={operationAssignedCount} unassignedCount={operationUnassignedCount} loading={operationLoading} onMatrixAlgorithmChange={setOperationMatrixAlgorithm} onUseCacheChange={setOperationUseCache} onReturnToStartChange={setOperationReturnToStart} onChooseOrigin={() => setPickTarget('start')} onAddDriver={() => setPickTarget('driver')} onAddOrder={() => setPickTarget('order')} onRun={() => void runOperationsPlan()} onClear={() => { setOperationsOrigin(null); setOperationDrivers([]); setOperationOrders([]); setOperationDispatchResponse(null); setOperationPlan([]); setOperationSegments([]); setOperationDispatchLines([]); setPickTarget('start'); }} onRemoveDriver={(index) => setOperationDrivers(operationDrivers.filter((_value, itemIndex) => itemIndex !== index))} onRemoveOrder={(index) => setOperationOrders(operationOrders.filter((_value, itemIndex) => itemIndex !== index))} />}
          </aside>
          <section className="product-map-shell">
            <div className="map-hud">
              <div><strong>{mode === 'route' ? 'Point-to-point routing' : mode === 'deliveries' ? 'Multi-stop delivery optimization' : mode === 'dispatch' ? 'Driver-order dispatch' : 'Operations story'}</strong><span>{mode === 'route' ? `Click to set ${pickTarget === 'start' ? 'start' : 'destination'}` : mode === 'deliveries' ? `Click to ${pickTarget === 'start' ? 'set start' : 'add stop'} · ${stops.length}/${MAX_VRP_STOPS} stops` : mode === 'dispatch' ? `Click to ${pickTarget === 'driver' ? 'place driver' : 'place order'}` : `Compose dispatch → delivery optimization → routing`}</span></div>
              <div className="map-hud-tags"><CodeTag>Kanpur Central</CodeTag>{routeComparison && <CodeTag>A* + Bi-A*</CodeTag>}{advancedComparison && <CodeTag>Greedy + 2-Opt + LNS</CodeTag>}{dispatchResponse && <CodeTag>Greedy + Hungarian</CodeTag>}{operationDispatchResponse && <CodeTag>Dispatch → LNS → Route</CodeTag>}</div>
            </div>
            <MapView routeGeometry={mode === 'route' ? routeGeometry : []} comparisonGeometry={mode === 'route' ? comparisonGeometry : []} additionalSegments={(mode === 'deliveries' ? routeSegments : mode === 'operations' ? operationSegments : []).map((segment) => segment.geometry)} locations={mapLocations} dispatchDrivers={mode === 'dispatch' ? driverMarkers : mode === 'operations' ? operationDriverMarkers : []} dispatchOrders={mode === 'dispatch' ? orderMarkers : mode === 'operations' ? operationOrderMarkers : []} dispatchLines={mode === 'dispatch' ? dispatchLines : mode === 'operations' ? operationDispatchLines : []} interactive onMapSelect={handleMapSelect} />
          </section>
        </section>
      )}
    </main>
  );
}

interface RouteProductPanelProps {
  start: Coordinate | null; end: Coordinate | null; pickTarget: PickTarget; routeResponse: RouteResponse | null; routeComparison: RouteComparisonResponse | null; routeDetail: RouteResponse | null; routeLoading: boolean; routeCompareLoading: boolean; routeTechnicalDetailsOpen: boolean; setRouteTechnicalDetailsOpen: (value: boolean) => void; calculateRoute: () => Promise<void>; compareRoutingAlgorithms: () => Promise<void>; setPickTarget: (value: PickTarget) => void;
}

function RouteProductPanel(props: RouteProductPanelProps) {
  const { start, end, pickTarget, routeResponse, routeComparison, routeDetail, routeLoading, routeCompareLoading, routeTechnicalDetailsOpen, setRouteTechnicalDetailsOpen, calculateRoute, compareRoutingAlgorithms, setPickTarget } = props;
  return <div className="panel-stack">
    <PanelSection title="Route" subtitle="Real road-network route, snapped graph endpoints, ETA and routing comparison.">
      <LocationButton label="Start" coordinate={start} onClick={() => setPickTarget('start')} active={pickTarget === 'start'} />
      <LocationButton label="Destination" coordinate={end} onClick={() => setPickTarget('end')} active={pickTarget === 'end'} />
      <div className="action-row"><button className="primary-button" type="button" onClick={() => void calculateRoute()} disabled={!start || !end || routeLoading}>{routeLoading ? 'Routing…' : 'Calculate route'}</button><button className="secondary-button" type="button" onClick={() => void compareRoutingAlgorithms()} disabled={!start || !end || routeCompareLoading}>{routeCompareLoading ? 'Comparing…' : 'Compare A* / Bi-A*'}</button></div>
    </PanelSection>

    {routeDetail && <PanelSection title="Route result" subtitle="Live response from /route or /route/compare"><div className="metric-grid metric-grid-2"><Metric label="Road distance" value={formatDistance(routeDetail.distance_m)} /><Metric label="ETA" value={formatSeconds(routeDetail.eta_seconds)} /><Metric label="Path nodes" value={formatNumber(routeDetail.path_node_count)} /><Metric label="Nodes expanded" value={formatNumber(routeDetail.nodes_expanded)} /><Metric label="Route time" value={formatMilliseconds(routeDetail.route_time_ms)} /><Metric label="Total time" value={formatMilliseconds(routeResponse?.total_time_ms)} /></div><button className="text-button" type="button" onClick={() => setRouteTechnicalDetailsOpen(!routeTechnicalDetailsOpen)}>{routeTechnicalDetailsOpen ? 'Hide routing details' : 'Show routing details'}</button>{routeTechnicalDetailsOpen && <TechnicalRouteDetails routeDetail={routeDetail} routeComparison={routeComparison} />}</PanelSection>}

    {routeComparison && <PanelSection title="Algorithm comparison" subtitle="Same snapped endpoints; actual A* and Bidirectional A* response"><div className="comparison-table"><div className="table-head"><span>Metric</span><span>A*</span><span>Bidirectional A*</span></div><ComparisonRow label="Distance" a={formatDistance(routeComparison.astar.distance_m)} b={formatDistance(routeComparison.bidirectional_astar.distance_m)} /><ComparisonRow label="Nodes expanded" a={formatNumber(routeComparison.astar.nodes_expanded)} b={formatNumber(routeComparison.bidirectional_astar.nodes_expanded)} /><ComparisonRow label="Route time" a={formatMilliseconds(routeComparison.astar.route_time_ms)} b={formatMilliseconds(routeComparison.bidirectional_astar.route_time_ms)} /><ComparisonRow label="ETA" a={formatSeconds(routeComparison.astar.eta_seconds)} b={formatSeconds(routeComparison.bidirectional_astar.eta_seconds)} /></div><div className="result-footnote">Node reduction: {formatPct(routeComparison.comparison.nodes_expanded_reduction_pct)} · route-time reduction: {formatPct(routeComparison.comparison.route_time_reduction_pct)} · same distance: {String(routeComparison.comparison.same_distance)}</div></PanelSection>}
  </div>;
}

function TechnicalRouteDetails({ routeDetail, routeComparison }: { routeDetail: RouteResponse; routeComparison: RouteComparisonResponse | null }) {
  const start = routeComparison?.start ?? routeDetail.start;
  const end = routeComparison?.end ?? routeDetail.end;
  return <div className="detail-list"><KeyValue label="Start snapped node" value={String(start?.snapped_node ?? '—')} /><KeyValue label="Start snap distance" value={formatDistance(start?.snap_distance_m)} /><KeyValue label="Start snap method" value={start?.snap_method ?? '—'} /><KeyValue label="End snapped node" value={String(end?.snapped_node ?? '—')} /><KeyValue label="End snap distance" value={formatDistance(end?.snap_distance_m)} /><KeyValue label="End snap method" value={end?.snap_method ?? '—'} /></div>;
}

interface DeliveriesProductPanelProps {
  start: Coordinate | null; stops: Coordinate[]; pickTarget: PickTarget; vrpStrategy: VrpStrategy; vrpMatrixAlgorithm: VrpMatrixAlgorithm; useVrpCache: boolean; returnToStart: boolean; keepOptimizationTrace: boolean; selectedVrp: VrpGreedyResponse | VrpCompareResponse['two_opt'] | AdvancedCompareResponse['lns'] | null; selectedVrpOrder: number[]; selectedVrpDistance: number | null; selectedVrpTime: number | null; greedyResponse: VrpGreedyResponse | null; vrpComparison: VrpCompareResponse | null; advancedComparison: AdvancedCompareResponse | null; matrixResponse: MatrixResponse | null; matrixView: MatrixView; setMatrixView: (value: MatrixView) => void; vrpLoading: boolean; matrixLoading: boolean; deliveryDetailsOpen: boolean; setDeliveryDetailsOpen: (value: boolean) => void; setVrpStrategy: (value: VrpStrategy) => void; setVrpMatrixAlgorithm: (value: VrpMatrixAlgorithm) => void; setUseVrpCache: (value: boolean) => void; setReturnToStart: (value: boolean) => void; setKeepOptimizationTrace: (value: boolean) => void; runDeliveries: () => Promise<void>; generateMatrix: () => Promise<void>; setPickTarget: (value: PickTarget) => void; setStops: (value: Coordinate[]) => void; setStart: (value: Coordinate | null) => void; setMatrixResponse: (value: MatrixResponse | null) => void; selectedVrpStrategy: VrpStrategy; setSelectedVrpStrategy: (value: VrpStrategy) => void;
}

function DeliveriesProductPanel(props: DeliveriesProductPanelProps) {
  const { start, stops, pickTarget, vrpStrategy, vrpMatrixAlgorithm, useVrpCache, returnToStart, keepOptimizationTrace, selectedVrp, selectedVrpOrder, selectedVrpDistance, selectedVrpTime, greedyResponse, vrpComparison, advancedComparison, matrixResponse, matrixView, setMatrixView, vrpLoading, matrixLoading, deliveryDetailsOpen, setDeliveryDetailsOpen, setVrpStrategy, setVrpMatrixAlgorithm, setUseVrpCache, setReturnToStart, setKeepOptimizationTrace, runDeliveries, generateMatrix, setPickTarget, setStops, setStart, setMatrixResponse, selectedVrpStrategy, setSelectedVrpStrategy } = props;
  return <div className="panel-stack">
    <PanelSection title="Deliveries" subtitle="Depot + delivery stops. Maximum 24 stops because the backend matrix supports 25 total locations including the depot.">
      <LocationButton label="Depot / Start" coordinate={start} onClick={() => setPickTarget('start')} active={pickTarget === 'start'} />
      <div className="stop-list">{stops.map((stop: Coordinate, index: number) => <div className="list-row" key={`${stop.lat}-${stop.lon}-${index}`}><span className="stop-number">{index + 1}</span><span className="grow"><strong>Stop {index + 1}</strong><small>{stop.lat.toFixed(5)}, {stop.lon.toFixed(5)}</small></span><button className="icon-button" type="button" onClick={() => setStops(stops.filter((_value: Coordinate, itemIndex: number) => itemIndex !== index))}>×</button></div>)}{stops.length === 0 && <div className="empty-state">No stops yet. Click the map after selecting the depot.</div>}</div>
      <div className="segmented-control three"><button type="button" className={vrpStrategy === 'greedy' ? 'segment-active' : ''} onClick={() => setVrpStrategy('greedy')}>Greedy</button><button type="button" className={vrpStrategy === 'two_opt' ? 'segment-active' : ''} onClick={() => setVrpStrategy('two_opt')}>2-Opt</button><button type="button" className={vrpStrategy === 'lns' ? 'segment-active' : ''} onClick={() => setVrpStrategy('lns')}>LNS</button></div>
      <label className="field-label">Matrix algorithm<select value={vrpMatrixAlgorithm} onChange={(event) => setVrpMatrixAlgorithm(event.target.value as VrpMatrixAlgorithm)}><option value="source_dijkstra">Source Dijkstra</option><option value="bidirectional_astar">Bidirectional A*</option></select></label>
      <div className="option-grid"><label className="toggle-row"><input type="checkbox" checked={returnToStart} onChange={(event) => setReturnToStart(event.target.checked)} /> Return to depot</label><label className="toggle-row"><input type="checkbox" checked={useVrpCache} onChange={(event) => setUseVrpCache(event.target.checked)} /> Matrix cache</label><label className="toggle-row"><input type="checkbox" checked={keepOptimizationTrace} onChange={(event) => setKeepOptimizationTrace(event.target.checked)} /> Keep trace</label></div>
      <div className="action-row"><button className="primary-button" type="button" disabled={!start || stops.length === 0 || vrpLoading} onClick={() => void runDeliveries()}>{vrpLoading ? 'Optimizing…' : 'Run optimizer'}</button><button className="secondary-button" type="button" disabled={!start || stops.length === 0 || matrixLoading} onClick={() => void generateMatrix()}>{matrixLoading ? 'Generating…' : 'Generate matrix'}</button></div>
      <div className="action-row"><button className="secondary-button" type="button" onClick={() => { setStart(null); setStops([]); setMatrixResponse(null); }} disabled={!start && stops.length === 0}>Clear</button></div>
    </PanelSection>

    {selectedVrp && <PanelSection title="Selected optimization" subtitle="Actual optimizer response rendered on the map"><div className="metric-grid metric-grid-3"><Metric label="Distance" value={formatDistance(selectedVrpDistance)} /><Metric label="Optimization" value={formatMilliseconds(selectedVrpTime)} /><Metric label="Stops" value={formatNumber(stops.length)} /></div><div className="order-line"><span>Visit order</span><strong>{selectedVrpOrder.map((index: number) => index + 1).join(' → ')}</strong></div><button className="text-button" type="button" onClick={() => setDeliveryDetailsOpen(!deliveryDetailsOpen)}>{deliveryDetailsOpen ? 'Hide optimization internals' : 'Show optimization internals'}</button>{deliveryDetailsOpen && <DeliveryDetails {...{ vrpStrategy, greedyResponse, vrpComparison, advancedComparison }} />}</PanelSection>}

    {matrixResponse && <PanelSection title="Distance matrix" subtitle="Direct response from POST /matrix"><div className="metric-grid metric-grid-4"><Metric label="N" value={formatNumber(matrixResponse.n)} /><Metric label="Pairs" value={formatNumber(matrixResponse.pair_count)} /><Metric label="Computed" value={formatNumber(matrixResponse.computed_pairs)} /><Metric label="Failed" value={formatNumber(matrixResponse.failed_pairs)} /><Metric label="Generation" value={formatMilliseconds(matrixResponse.generation_time_ms)} /><Metric label="Workers" value={formatNumber(matrixResponse.parallel_workers)} /><Metric label="Cache" value={matrixResponse.cache.hit ? 'HIT' : matrixResponse.cache.enabled ? 'MISS' : 'DISABLED'} /><Metric label="Algorithm" value={matrixResponse.algorithm} /></div><div className="segmented-control two"><button type="button" className={matrixView === 'distance' ? 'segment-active' : ''} onClick={() => setMatrixView('distance')}>Distance m</button><button type="button" className={matrixView === 'eta' ? 'segment-active' : ''} onClick={() => setMatrixView('eta')}>ETA s</button></div><MatrixTable response={matrixResponse} view={matrixView} /></PanelSection>}

    {advancedComparison && <PanelSection title="Algorithm progression" subtitle="Greedy → 2-Opt → LNS"><div className="comparison-table"><div className="table-head"><span>Stage</span><span>Distance</span><span>Improvement</span></div><ComparisonRow label="Greedy" a={formatDistance(advancedComparison.greedy.total_distance_m)} b="baseline" /><ComparisonRow label="2-Opt" a={formatDistance(advancedComparison.two_opt.total_distance_m)} b={formatPct(advancedComparison.comparison.two_opt_vs_greedy_improvement_pct)} /><ComparisonRow label="LNS" a={formatDistance(advancedComparison.lns.total_distance_m)} b={formatPct(advancedComparison.comparison.lns_vs_greedy_improvement_pct)} /></div><div className="result-footnote">2-Opt non-regression: {String(advancedComparison.comparison.two_opt_non_regression)} · LNS non-regression: {String(advancedComparison.comparison.lns_non_regression)}</div></PanelSection>}
  </div>;
}

function DeliveryDetails({ vrpStrategy, greedyResponse, vrpComparison, advancedComparison }: { vrpStrategy: VrpStrategy; greedyResponse: VrpGreedyResponse | null; vrpComparison: VrpCompareResponse | null; advancedComparison: AdvancedCompareResponse | null }) {
  if (vrpStrategy === 'greedy' && greedyResponse) return <div className="detail-list"><KeyValue label="Matrix generation" value={formatMilliseconds(greedyResponse.matrix_generation_time_ms)} /><KeyValue label="Optimization time" value={formatMilliseconds(greedyResponse.optimization_time_ms)} /><KeyValue label="Total time" value={formatMilliseconds(greedyResponse.total_time_ms)} /><KeyValue label="Cache status" value={greedyResponse.cache_status ?? '—'} /><KeyValue label="Cache hits" value={formatNumber(greedyResponse.cache_hits)} /><KeyValue label="Cache misses" value={formatNumber(greedyResponse.cache_misses)} /></div>;
  if (vrpStrategy === 'two_opt' && vrpComparison) return <div className="detail-list"><KeyValue label="Iterations" value={formatNumber(vrpComparison.two_opt.iterations)} /><KeyValue label="Swaps" value={formatNumber(vrpComparison.two_opt.swaps_applied)} /><KeyValue label="Converged" value={String(vrpComparison.two_opt.converged)} /><KeyValue label="Distance saved" value={formatDistance(vrpComparison.improvement.distance_saved_m)} /><KeyValue label="Improvement" value={formatPct(vrpComparison.improvement.improvement_pct)} /><KeyValue label="Trace entries" value={formatNumber(vrpComparison.convergence_trace.length)} /></div>;
  if (vrpStrategy === 'lns' && advancedComparison) return <div className="detail-list"><KeyValue label="Iterations" value={formatNumber(advancedComparison.lns.iterations_run)} /><KeyValue label="Improvements applied" value={formatNumber(advancedComparison.lns.improvements_applied)} /><KeyValue label="Converged" value={String(advancedComparison.lns.converged)} /><KeyValue label="Random seed" value={advancedComparison.lns.random_seed === null ? 'none' : String(advancedComparison.lns.random_seed)} /><KeyValue label="Trace entries" value={formatNumber(advancedComparison.lns.trace.length)} /><KeyValue label="Total time" value={formatMilliseconds(advancedComparison.total_time_ms)} /></div>;
  return null;
}

interface DispatchProductPanelProps {
  drivers: DispatchDriverRequest[]; orders: DispatchOrderRequest[]; pickTarget: PickTarget; dispatchMatrixAlgorithm: DispatchMatrixAlgorithm; useDispatchCache: boolean; dispatchResponse: DispatchCompareResponse | null; dispatchResult: DispatchCompareResponse['hungarian'] | DispatchCompareResponse['greedy'] | null; dispatchFairness: DispatchCompareResponse['hungarian_fairness'] | DispatchCompareResponse['greedy_fairness'] | null; assignmentView: AssignmentView; dispatchLoading: boolean; dispatchDetailsOpen: boolean; setDispatchDetailsOpen: (value: boolean) => void; setDispatchMatrixAlgorithm: (value: DispatchMatrixAlgorithm) => void; setUseDispatchCache: (value: boolean) => void; setAssignment: (value: AssignmentView) => void; runDispatch: () => Promise<void>; setPickTarget: (value: PickTarget) => void; setDrivers: (value: DispatchDriverRequest[]) => void; setOrders: (value: DispatchOrderRequest[]) => void; setDispatchResponse: (value: DispatchCompareResponse | null) => void; setDispatchLines: (value: Array<{ from: Coordinate; to: Coordinate; id: string }>) => void;
}

function DispatchProductPanel(props: DispatchProductPanelProps) {
  const { drivers, orders, pickTarget, dispatchMatrixAlgorithm, useDispatchCache, dispatchResponse, dispatchResult, dispatchFairness, assignmentView, dispatchLoading, dispatchDetailsOpen, setDispatchDetailsOpen, setDispatchMatrixAlgorithm, setUseDispatchCache, setAssignment, runDispatch, setPickTarget, setDrivers, setOrders, setDispatchResponse, setDispatchLines } = props;
  return <div className="panel-stack">
    <PanelSection title="Dispatch" subtitle="Driver-order assignment using the backend's greedy and Hungarian cost models.">
      <ListEditor title="Drivers" items={drivers.map((driver: DispatchDriverRequest) => ({ id: driver.driver_id, subtitle: `${driver.lat.toFixed(4)}, ${driver.lon.toFixed(4)} · ${driver.max_capacity - driver.current_load} slots` }))} color="driver" onAdd={() => setPickTarget('driver')} onRemove={(index: number) => setDrivers(drivers.filter((_value: DispatchDriverRequest, itemIndex: number) => itemIndex !== index))} />
      <ListEditor title="Orders" items={orders.map((order: DispatchOrderRequest) => ({ id: order.order_id, subtitle: `${order.pickup_lat.toFixed(4)}, ${order.pickup_lon.toFixed(4)}` }))} color="order" onAdd={() => setPickTarget('order')} onRemove={(index: number) => setOrders(orders.filter((_value: DispatchOrderRequest, itemIndex: number) => itemIndex !== index))} />
      <label className="field-label">Cost matrix<select value={dispatchMatrixAlgorithm} onChange={(event) => setDispatchMatrixAlgorithm(event.target.value as DispatchMatrixAlgorithm)}><option value="haversine">Haversine</option><option value="source_dijkstra">Source Dijkstra / road network</option></select></label>
      <label className="toggle-row"><input type="checkbox" checked={useDispatchCache} onChange={(event) => setUseDispatchCache(event.target.checked)} /> Dispatch cache</label>
      <button className="primary-button" type="button" disabled={drivers.length === 0 || orders.length === 0 || dispatchLoading} onClick={() => void runDispatch()}>{dispatchLoading ? 'Assigning…' : 'Run dispatch comparison'}</button>
      <button className="secondary-button" type="button" onClick={() => { setDrivers([]); setOrders([]); setDispatchResponse(null); setDispatchLines([]); }} disabled={drivers.length === 0 && orders.length === 0}>Clear dispatch</button>
    </PanelSection>
    {dispatchResponse && dispatchResult && dispatchFairness && <PanelSection title="Assignment result" subtitle="Compare Greedy vs Hungarian and inspect fairness / feasibility"><div className="segmented-control two"><button type="button" className={assignmentView === 'greedy' ? 'segment-active' : ''} onClick={() => setAssignment('greedy')}>Greedy</button><button type="button" className={assignmentView === 'hungarian' ? 'segment-active' : ''} onClick={() => setAssignment('hungarian')}>Hungarian</button></div><div className="metric-grid metric-grid-4"><Metric label="Assigned" value={formatNumber(dispatchResult.assigned_count)} /><Metric label="Unassigned" value={formatNumber(dispatchResult.unassigned_order_ids.length)} /><Metric label="Total cost" value={formatDistance(dispatchResult.total_cost)} /><Metric label="Total time" value={formatMilliseconds(dispatchResponse.total_time_ms)} /><Metric label="Fairness" value={dispatchFairness.fairness_score.toFixed(3)} /><Metric label="Utilization max" value={formatPct(dispatchFairness.max_utilization_pct)} /><Metric label="Available slots" value={formatNumber(dispatchResponse.available_slot_count)} /><Metric label="Unused slots" value={formatNumber(dispatchResponse.unused_slot_count)} /></div><div className="assignment-list">{dispatchResult.assignments.map((assignment) => <div className="assignment-row" key={`${assignment.driver_id}-${assignment.order_id}`}><span>{assignment.driver_id}</span><strong>→</strong><span>{assignment.order_id}</span><span>{formatDistance(assignment.cost)}</span></div>)}</div><div className="result-footnote">Hungarian vs Greedy: {formatPct(dispatchResponse.comparison.hungarian_vs_greedy_improvement_pct)} cost improvement · non-regression={String(dispatchResponse.comparison.hungarian_non_regression)}</div><button className="text-button" type="button" onClick={() => setDispatchDetailsOpen(!dispatchDetailsOpen)}>{dispatchDetailsOpen ? 'Hide dispatch internals' : 'Show dispatch internals'}</button>{dispatchDetailsOpen && <DispatchDetails response={dispatchResponse} fairness={dispatchFairness} />}</PanelSection>}
  </div>;
}

function DispatchDetails({ response, fairness }: { response: DispatchCompareResponse; fairness: DispatchCompareResponse['hungarian_fairness'] }) {
  return <div className="detail-list"><KeyValue label="Matrix algorithm" value={response.matrix_algorithm} /><KeyValue label="Cache status" value={response.cache_status ?? '—'} /><KeyValue label="Cache hit" value={String(response.cache_hit)} /><KeyValue label="Cost-matrix build" value={formatMilliseconds(response.cost_matrix_build_time_ms)} /><KeyValue label="Road network" value={response.road_network ? `${response.road_network.matrix_source}, ${response.road_network.reachable_pair_count}/${response.road_network.pair_count} reachable` : 'not used / not returned'} /><KeyValue label="Fairness score" value={fairness.fairness_score.toFixed(3)} /><KeyValue label="Projected load range" value={String(fairness.projected_load_range)} /><KeyValue label="Max utilization" value={formatPct(fairness.max_utilization_pct)} /></div>;
}

interface OperationsProductPanelProps {
  origin: Coordinate | null;
  drivers: DispatchDriverRequest[];
  orders: DispatchOrderRequest[];
  pickTarget: PickTarget;
  matrixAlgorithm: DispatchMatrixAlgorithm;
  useCache: boolean;
  returnToStart: boolean;
  driverCapacity: number;
  vrpStrategy: VrpStrategy;
  vrpMatrixAlgorithm: VrpMatrixAlgorithm;
  onDriverCapacityChange: (value: number) => void;
  onVrpStrategyChange: (value: VrpStrategy) => void;
  onVrpMatrixAlgorithmChange: (value: VrpMatrixAlgorithm) => void;
  dispatchResponse: DispatchCompareResponse | null;
  plan: OperationDriverPlan[];
  assignedCount: number;
  unassignedCount: number;
  loading: boolean;
  onMatrixAlgorithmChange: (value: DispatchMatrixAlgorithm) => void;
  onUseCacheChange: (value: boolean) => void;
  onReturnToStartChange: (value: boolean) => void;
  onChooseOrigin: () => void;
  onAddDriver: () => void;
  onAddOrder: () => void;
  onRun: () => void;
  onClear: () => void;
  onRemoveDriver: (index: number) => void;
  onRemoveOrder: (index: number) => void;
}

function OperationsProductPanel(props: OperationsProductPanelProps) {
  const { origin, drivers, orders, pickTarget, matrixAlgorithm, useCache, returnToStart, driverCapacity, vrpStrategy, vrpMatrixAlgorithm, onDriverCapacityChange, onVrpStrategyChange, onVrpMatrixAlgorithmChange, dispatchResponse, plan, assignedCount, unassignedCount, loading, onMatrixAlgorithmChange, onUseCacheChange, onReturnToStartChange, onChooseOrigin, onAddDriver, onAddOrder, onRun, onClear, onRemoveDriver, onRemoveOrder } = props;
  const canRun = Boolean(origin) && drivers.length > 0 && orders.length > 0 && !loading;
  return <div className="panel-stack">
    <PanelSection title="Operations story" subtitle="Compose the independent CityRoute engines into one scenario without merging their backend responsibilities.">
      <div className="operation-flow"><span>1 Dispatch</span><span>→</span><span>2 Optimize stops</span><span>→</span><span>3 Route legs</span></div>
      <label className="field-label">Driver capacity<select value={driverCapacity} onChange={(event) => onDriverCapacityChange(Number(event.target.value))}>{[1,2,3,4,5,6,8,10].map((value) => <option key={value} value={value}>{value} orders / driver</option>)}</select></label>
      <div className="option-grid"><label className="field-label">Delivery optimizer<select value={vrpStrategy} onChange={(event) => onVrpStrategyChange(event.target.value as VrpStrategy)}><option value="greedy">Greedy</option><option value="two_opt">2-Opt</option><option value="lns">LNS</option></select></label><label className="field-label">Delivery matrix<select value={vrpMatrixAlgorithm} onChange={(event) => onVrpMatrixAlgorithmChange(event.target.value as VrpMatrixAlgorithm)}><option value="source_dijkstra">Source Dijkstra</option><option value="bidirectional_astar">Bidirectional A*</option></select></label></div>
      <LocationButton label="Origin / Start" coordinate={origin} onClick={onChooseOrigin} active={pickTarget === 'start'} />
      <ListEditor title="Drivers" items={drivers.map((driver) => ({ id: driver.driver_id, subtitle: `${driver.lat.toFixed(4)}, ${driver.lon.toFixed(4)} · capacity ${driver.max_capacity}` }))} color="driver" onAdd={onAddDriver} onRemove={onRemoveDriver} />
      <ListEditor title="Orders" items={orders.map((order) => ({ id: order.order_id, subtitle: `${order.pickup_lat.toFixed(4)}, ${order.pickup_lon.toFixed(4)}` }))} color="order" onAdd={onAddOrder} onRemove={onRemoveOrder} />
      <div className="option-grid"><label className="field-label">Dispatch cost<select value={matrixAlgorithm} onChange={(event) => onMatrixAlgorithmChange(event.target.value as DispatchMatrixAlgorithm)}><option value="haversine">Haversine</option><option value="source_dijkstra">Road network / Source Dijkstra</option></select></label><label className="toggle-row"><input type="checkbox" checked={useCache} onChange={(event) => onUseCacheChange(event.target.checked)} /> Cache</label></div>
      <label className="toggle-row"><input type="checkbox" checked={returnToStart} onChange={(event) => onReturnToStartChange(event.target.checked)} /> Return each driver to start</label>
      <div className="action-row"><button className="primary-button" type="button" disabled={!canRun} onClick={onRun}>{loading ? 'Building plan…' : 'Build delivery plan'}</button><button className="secondary-button" type="button" disabled={drivers.length === 0 && orders.length === 0 && !origin} onClick={onClear}>Clear</button></div>
    </PanelSection>

    {dispatchResponse && <PanelSection title="Stage 1 · Dispatch" subtitle="Real /dispatch/compare result used to allocate orders to drivers."><div className="metric-grid metric-grid-3"><Metric label="Assigned" value={formatNumber(assignedCount)} /><Metric label="Unassigned" value={formatNumber(unassignedCount)} /><Metric label="Cost" value={formatDistance(dispatchResponse.hungarian.total_cost)} /></div><div className="result-footnote">Hungarian improvement vs Greedy: {formatPct(dispatchResponse.comparison.hungarian_vs_greedy_improvement_pct)}</div></PanelSection>}

    {plan.length > 0 && <PanelSection title="Stage 2–3 · Driver plans" subtitle="Dispatch assigns orders first; each driver's assigned orders are then optimized from the shared origin and converted into actual road-route segments."><div className="operation-plan-list">{plan.map((item) => <div className="operation-driver-plan" key={item.driverId}><div className="section-heading"><strong>{item.driverId}</strong><span className="code-tag">{item.assignedOrderIds.length} orders</span></div><div className="result-footnote">Assigned: {item.assignedOrderIds.length ? item.assignedOrderIds.join(' → ') : 'none'}</div>{item.optimizedOrderIds.length > 0 && <><div className="result-footnote">Optimized ({item.strategy.toUpperCase()}): {item.optimizedOrderIds.join(' → ')}</div><div className="metric-grid metric-grid-2"><Metric label="Optimized distance" value={formatDistance(item.totalDistanceMeters)} /><Metric label="LNS time" value={formatMilliseconds(item.optimizationTimeMs)} /></div></>} {item.assignedOrderIds.length === 0 && <div className="empty-state">No orders assigned.</div>}</div>)}</div></PanelSection>}
  </div>;
}

function LocationButton({ label, coordinate, onClick, active }: { label: string; coordinate: Coordinate | null; onClick: () => void; active: boolean }) {
  return <button className={`location-button ${active ? 'location-button-active' : ''}`} type="button" onClick={onClick}><span className="location-dot" /><span className="grow"><strong>{label}</strong><small>{coordinate ? `${coordinate.lat.toFixed(5)}, ${coordinate.lon.toFixed(5)}` : 'Choose on map'}</small></span></button>;
}

function ListEditor({ title, items, color, onAdd, onRemove }: { title: string; items: Array<{ id: string; subtitle: string }>; color: 'driver' | 'order'; onAdd: () => void; onRemove: (index: number) => void }) {
  return <section className="compact-section"><div className="section-heading"><div><h3>{title}</h3></div><button className="text-button" type="button" onClick={onAdd}>Add on map</button></div>{items.map((item, index) => <div className="list-row" key={item.id}><span className={`dispatch-swatch dispatch-swatch-${color}`} /><span className="grow"><strong>{item.id}</strong><small>{item.subtitle}</small></span><button className="icon-button" type="button" onClick={() => onRemove(index)}>×</button></div>)}{items.length === 0 && <div className="empty-state">None.</div>}</section>;
}

function MatrixTable({ response, view }: { response: MatrixResponse; view: MatrixView }) {
  const matrix = view === 'distance' ? response.matrix_distance_m : response.matrix_eta_s;
  return <div className="matrix-wrap"><table><thead><tr><th>From / To</th>{response.locations.map((location) => <th key={location.id}>{location.id}</th>)}</tr></thead><tbody>{matrix.map((row, rowIndex) => <tr key={response.locations[rowIndex].id}><th>{response.locations[rowIndex].id}</th>{row.map((value, columnIndex) => <td key={`${rowIndex}-${columnIndex}`}>{value === null ? '∅' : value.toFixed(1)}</td>)}</tr>)}</tbody></table>{response.failures.length > 0 && <div className="notice-box">Failed pairs: {response.failures.map((failure) => `${failure.from_id}→${failure.to_id}`).join(', ')}</div>}</div>;
}

function ComparisonRow({ label, a, b }: { label: string; a: string; b: string }) { return <div className="table-row"><span>{label}</span><span>{a}</span><span>{b}</span></div>; }
function KeyValue({ label, value }: { label: string; value: string }) { return <div className="key-value"><span>{label}</span><strong>{value}</strong></div>; }

import { get, post } from './client';
import type {
  AdvancedCompareResponse,
  Coordinate,
  DispatchCompareResponse,
  DispatchRequest,
  GraphSnapResponse,
  GraphStatsResponse,
  GraphValidationResponse,
  LegacyHealthResponse,
  LivenessResponse,
  MatrixRequest,
  MatrixResponse,
  ReadinessResponse,
  RouteComparisonResponse,
  RouteResponse,
  RootResponse,
  VrpAdvancedCompareRequest,
  VrpCompareRequest,
  VrpCompareResponse,
  VrpGreedyResponse,
  VrpRequest,
} from '../types/domain';

const ROOT_PATH = '/';
const HEALTH_PATH = '/health';
const LIVE_PATH = '/health/live';
const READY_PATH = '/health/ready';
const GRAPH_STATS_PATH = '/graph/stats';
const GRAPH_VALIDATE_PATH = '/graph/validate';
const GRAPH_SNAP_PATH = '/graph/snap';
const ROUTE_PATH = '/route';
const ROUTE_COMPARE_PATH = '/route/compare';
const MATRIX_PATH = '/matrix';
const VRP_GREEDY_PATH = '/vrp/greedy';
const VRP_COMPARE_PATH = '/vrp/compare';
const VRP_ADVANCED_COMPARE_PATH = '/vrp/compare/advanced';
const DISPATCH_COMPARE_PATH = '/dispatch/compare';
const METRICS_PATH = '/metrics';

export function getRoot(): Promise<RootResponse> { return get<RootResponse>(ROOT_PATH); }
export function getHealth(): Promise<LegacyHealthResponse> { return get<LegacyHealthResponse>(HEALTH_PATH); }
export function getLiveness(): Promise<LivenessResponse> { return get<LivenessResponse>(LIVE_PATH); }
export function getReadiness(): Promise<ReadinessResponse> { return get<ReadinessResponse>(READY_PATH); }
export function getGraphStats(): Promise<GraphStatsResponse> { return get<GraphStatsResponse>(GRAPH_STATS_PATH); }

function buildCoordinateQuery(coordinate: Coordinate, prefix: string): string {
  return `${prefix}_lat=${encodeURIComponent(coordinate.lat)}&${prefix}_lon=${encodeURIComponent(coordinate.lon)}`;
}

function buildRouteQuery(start: Coordinate, end: Coordinate): string {
  return [buildCoordinateQuery(start, 'start'), buildCoordinateQuery(end, 'end')].join('&');
}

export function validateGraphCoordinate(coordinate: Coordinate): Promise<GraphValidationResponse> {
  return get<GraphValidationResponse>(`${GRAPH_VALIDATE_PATH}?lat=${coordinate.lat}&lon=${coordinate.lon}`);
}

export function snapGraphCoordinate(coordinate: Coordinate): Promise<GraphSnapResponse> {
  return get<GraphSnapResponse>(`${GRAPH_SNAP_PATH}?lat=${coordinate.lat}&lon=${coordinate.lon}`);
}

export function getRoute(start: Coordinate, end: Coordinate): Promise<RouteResponse> {
  return get<RouteResponse>(`${ROUTE_PATH}?${buildRouteQuery(start, end)}`);
}

export function compareRoute(start: Coordinate, end: Coordinate): Promise<RouteComparisonResponse> {
  return get<RouteComparisonResponse>(`${ROUTE_COMPARE_PATH}?${buildRouteQuery(start, end)}`);
}

export function createMatrix(request: MatrixRequest): Promise<MatrixResponse> {
  return post<MatrixRequest, MatrixResponse>(MATRIX_PATH, request);
}

export function optimizeStops(request: VrpRequest): Promise<VrpGreedyResponse> {
  return post<VrpRequest, VrpGreedyResponse>(VRP_GREEDY_PATH, request);
}

export function compareStops(request: VrpCompareRequest): Promise<VrpCompareResponse> {
  return post<VrpCompareRequest, VrpCompareResponse>(VRP_COMPARE_PATH, request);
}

export function compareAdvancedStops(request: VrpAdvancedCompareRequest): Promise<AdvancedCompareResponse> {
  return post<VrpAdvancedCompareRequest, AdvancedCompareResponse>(VRP_ADVANCED_COMPARE_PATH, request);
}

export function compareDispatch(request: DispatchRequest): Promise<DispatchCompareResponse> {
  return post<DispatchRequest, DispatchCompareResponse>(DISPATCH_COMPARE_PATH, request);
}

export async function getMetricsText(): Promise<string> {
  const response = await fetch(`${import.meta.env.VITE_API_PREFIX ?? '/api'}${METRICS_PATH}`, {
    headers: { Accept: 'text/plain' },
  });
  const body = await response.text();
  if (!response.ok) throw new Error(`Metrics request failed with HTTP ${response.status}.`);
  return body;
}

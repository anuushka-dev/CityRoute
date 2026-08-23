export interface Coordinate {
  lat: number;
  lon: number;
}

export interface RouteEndpoint {
  input: Coordinate;
  snapped_node: number;
  snapped: boolean;
  snap_distance_m: number | null;
  snap_method: string | null;
  snap_time_ms: number | null;
}

export interface RouteResponse {
  status: 'ok';
  algorithm: 'astar';
  start: RouteEndpoint;
  end: RouteEndpoint;
  distance_m: number;
  distance_km: number;
  eta_seconds: number;
  eta_minutes: number;
  path_node_count: number;
  nodes_expanded: number;
  route_time_ms: number;
  total_time_ms: number;
  geometry: Coordinate[];
}

export interface RouteAlgorithmResult {
  algorithm: 'astar' | 'bidirectional_astar';
  distance_m: number;
  distance_km: number;
  eta_seconds: number;
  eta_minutes: number;
  path_node_count: number;
  nodes_expanded: number;
  route_time_ms: number;
  geometry: Coordinate[];
  forward_nodes_expanded?: number;
  backward_nodes_expanded?: number;
  meeting_node?: number;
}

export interface RouteComparisonSummary {
  distance_delta_m: number;
  same_distance: boolean;
  astar_route_time_ms: number;
  bidirectional_route_time_ms: number;
  route_time_delta_ms: number;
  astar_faster: boolean;
  bidirectional_faster: boolean;
  astar_nodes_expanded: number;
  bidirectional_nodes_expanded: number;
  nodes_expanded_delta: number;
  nodes_expanded_reduction_pct: number;
  route_time_reduction_pct: number;
}

export interface RouteComparisonResponse {
  status: 'ok';
  start: RouteEndpoint;
  end: RouteEndpoint;
  astar: RouteAlgorithmResult;
  bidirectional_astar: RouteAlgorithmResult;
  comparison: RouteComparisonSummary;
  compare_total_time_ms: number;
}

export type VrpMatrixAlgorithm = 'source_dijkstra' | 'bidirectional_astar';
export type VrpStrategy = 'greedy' | 'two_opt' | 'lns';

export interface VrpRequest {
  start: Coordinate;
  stops: Coordinate[];
  return_to_start: boolean;
  matrix_algorithm: VrpMatrixAlgorithm;
  use_cache: boolean;
}

export interface VrpCompareRequest extends VrpRequest {
  ttl_seconds: number | null;
  two_opt_max_iterations: number;
  improvement_tolerance_m: number;
  keep_trace: boolean;
}

export interface VrpAdvancedCompareRequest extends VrpRequest {
  two_opt_max_iterations: number;
  two_opt_improvement_tolerance_m: number;
  lns_max_iterations: number;
  lns_destroy_fraction: number;
  lns_no_improvement_limit: number;
  lns_random_seed: number | null;
  keep_trace: boolean;
}

export interface VrpLeg {
  from_type: 'start' | 'stop';
  from_index: number | null;
  to_type: 'start' | 'stop';
  to_index: number | null;
  distance_m: number;
}

export interface VrpGreedyResponse {
  status: 'ok';
  phase: 'tier2_phase6';
  algorithm: 'nearest_neighbor_greedy';
  matrix_algorithm: VrpMatrixAlgorithm;
  stop_count: number;
  optimized_order: number[];
  total_distance_m: number;
  return_to_start: boolean;
  legs: VrpLeg[];
  matrix_generation_time_ms: number;
  optimization_time_ms: number;
  total_time_ms: number;
  cache_used: boolean | null;
  cache_status: string | null;
  cache_hits: number;
  cache_misses: number;
}

export interface VrpRouteSummary {
  algorithm: 'nearest_neighbor_greedy' | 'two_opt';
  optimized_order: number[];
  total_distance_m: number;
  legs: VrpLeg[];
  optimization_time_ms: number;
  iterations: number;
  swaps_applied: number;
  converged: boolean;
}

export interface VrpImprovementSummary {
  baseline_distance_m: number;
  optimized_distance_m: number;
  distance_saved_m: number;
  improvement_pct: number;
  improved: boolean;
  non_regression: boolean;
}

export interface TwoOptTraceItem {
  iteration: number;
  distance_m: number;
  improved: boolean;
  swap_i: number | null;
  swap_j: number | null;
}

export interface VrpCompareResponse {
  status: 'ok';
  phase: 'tier2_phase7';
  comparison: 'greedy_vs_two_opt';
  matrix_algorithm: VrpMatrixAlgorithm;
  stop_count: number;
  return_to_start: boolean;
  greedy: VrpRouteSummary;
  two_opt: VrpRouteSummary;
  improvement: VrpImprovementSummary;
  convergence_trace: TwoOptTraceItem[];
  matrix_generation_time_ms: number;
  total_time_ms: number;
  cache_used: boolean | null;
  cache_status: 'hit' | 'miss' | 'partial' | 'disabled' | 'unknown';
  cache_hits: number;
  cache_misses: number;
}

export interface AdvancedRouteLeg {
  from_type: string;
  from_index: number | null;
  to_type: string;
  to_index: number | null;
  distance_m: number;
}

export interface AdvancedGreedyResult {
  algorithm: 'nearest_neighbor_greedy';
  optimized_order: number[];
  total_distance_m: number;
  legs: AdvancedRouteLeg[];
  optimization_time_ms: number;
}

export interface AdvancedTwoOptTraceItem {
  iteration: number;
  best_distance_m: number;
  improved: boolean;
}

export interface AdvancedTwoOptResult {
  algorithm: 'two_opt';
  optimized_order: number[];
  total_distance_m: number;
  initial_distance_m: number;
  distance_saved_m: number;
  improvement_pct: number;
  iterations_run: number;
  swaps_applied: number;
  converged: boolean;
  legs: AdvancedRouteLeg[];
  optimization_time_ms: number;
  trace: AdvancedTwoOptTraceItem[];
}

export interface AdvancedLNSTraceItem {
  iteration: number;
  best_distance_m: number;
  candidate_distance_m: number;
  improved: boolean;
  removed_count: number;
}

export interface AdvancedLNSResult {
  algorithm: 'large_neighborhood_search';
  optimized_order: number[];
  total_distance_m: number;
  initial_distance_m: number;
  distance_saved_m: number;
  improvement_pct: number;
  iterations_run: number;
  improvements_applied: number;
  converged: boolean;
  random_seed: number | null;
  legs: AdvancedRouteLeg[];
  optimization_time_ms: number;
  trace: AdvancedLNSTraceItem[];
}

export interface AdvancedComparisonSummary {
  two_opt_vs_greedy_distance_saved_m: number;
  two_opt_vs_greedy_improvement_pct: number;
  lns_vs_two_opt_distance_saved_m: number;
  lns_vs_two_opt_improvement_pct: number;
  lns_vs_greedy_distance_saved_m: number;
  lns_vs_greedy_improvement_pct: number;
  two_opt_non_regression: boolean;
  lns_non_regression: boolean;
}

export interface AdvancedCompareResponse {
  status: 'ok';
  phase: 'tier3_phase8';
  matrix_algorithm: VrpMatrixAlgorithm;
  stop_count: number;
  return_to_start: boolean;
  greedy: AdvancedGreedyResult;
  two_opt: AdvancedTwoOptResult;
  lns: AdvancedLNSResult;
  comparison: AdvancedComparisonSummary;
  matrix_generation_time_ms: number;
  cache_used: boolean;
  cache_status: string | null;
  cache_hits: number;
  cache_misses: number;
  total_time_ms: number;
}

export interface DispatchDriverRequest {
  driver_id: string;
  lat: number;
  lon: number;
  current_load: number;
  max_capacity: number;
}

export interface DispatchOrderRequest {
  order_id: string;
  pickup_lat: number;
  pickup_lon: number;
}

export type DispatchMatrixAlgorithm = 'haversine' | 'source_dijkstra';

export interface DispatchRequest {
  drivers: DispatchDriverRequest[];
  orders: DispatchOrderRequest[];
  matrix_algorithm: DispatchMatrixAlgorithm;
  use_cache: boolean;
  load_penalty_m: number;
  slot_penalty_m: number;
  return_cost_breakdown: boolean;
}

export interface DispatchAssignment {
  driver_id: string;
  order_id: string;
  row_index: number;
  col_index: number;
  cost: number;
}

export interface DispatchAlgorithmResult {
  algorithm: string;
  assignments: DispatchAssignment[];
  total_cost: number;
  assigned_count: number;
  unassigned_driver_slot_rows: number[];
  unassigned_order_ids: string[];
}

export interface DriverFairnessMetric {
  driver_id: string;
  current_load: number;
  max_capacity: number;
  available_slots: number;
  assigned_orders: number;
  projected_load: number;
  remaining_capacity: number;
  utilization_pct: number;
}

export interface DispatchFairness {
  driver_metrics: DriverFairnessMetric[];
  driver_count: number;
  total_assigned_orders: number;
  total_available_slots: number;
  assigned_order_min: number;
  assigned_order_max: number;
  assigned_order_range: number;
  assigned_order_mean: number;
  assigned_order_std_dev: number;
  projected_load_min: number;
  projected_load_max: number;
  projected_load_range: number;
  projected_load_mean: number;
  projected_load_std_dev: number;
  max_utilization_pct: number;
  min_utilization_pct: number;
  fairness_score: number;
}

export interface DispatchComparison {
  hungarian_non_regression: boolean;
  hungarian_vs_greedy_cost_saved: number;
  hungarian_vs_greedy_improvement_pct: number;
}

export interface DispatchCostBreakdown {
  row_index: number;
  col_index: number;
  driver_id: string;
  order_id: string;
  distance_m: number;
  load_penalty_m: number;
  slot_penalty_m: number;
  total_cost: number;
  allowed: boolean;
}

export interface DispatchRoadNetwork {
  matrix_source: 'computed' | 'cache';
  snapped_driver_count: number;
  snapped_order_count: number;
  unique_driver_node_count: number;
  unique_order_node_count: number;
  source_search_count: number;
  pair_count: number;
  reachable_pair_count: number;
  unreachable_pair_count: number;
  all_pairs_reachable: boolean;
  unreachable_cost_m: number;
  snap_time_ms: number;
}

export interface DispatchCompareResponse {
  status: 'ok';
  phase: 'tier3_phase9' | 'tier3_phase9_1' | 'tier3_phase10';
  driver_count: number;
  order_count: number;
  available_slot_count: number;
  assigned_order_count: number;
  unassigned_order_count: number;
  unused_slot_count: number;
  matrix_algorithm: DispatchMatrixAlgorithm;
  cache_used: boolean;
  cache_hit: boolean;
  cache_key: string | null;
  cache_status: 'disabled' | 'hit' | 'miss' | null;
  cache_hits: number | null;
  cache_misses: number | null;
  cache_error: string | null;
  cost_matrix_build_time_ms: number;
  total_time_ms: number;
  greedy: DispatchAlgorithmResult;
  hungarian: DispatchAlgorithmResult;
  comparison: DispatchComparison;
  greedy_fairness: DispatchFairness;
  hungarian_fairness: DispatchFairness;
  cost_breakdown: DispatchCostBreakdown[];
  road_network: DispatchRoadNetwork | null;
}

export interface ReadinessComponents {
  graph: 'ready' | 'degraded' | 'unavailable' | 'not_ready' | 'not_initialized' | 'not_required';
  snap_index: 'ready' | 'degraded' | 'unavailable' | 'not_ready' | 'not_initialized' | 'not_required';
  dispatch_adjacency: 'ready' | 'degraded' | 'unavailable' | 'not_ready' | 'not_initialized' | 'not_required';
  redis: 'ready' | 'degraded' | 'unavailable' | 'not_ready' | 'not_initialized' | 'not_required';
}

export interface ReadinessResponse {
  status: 'ready' | 'degraded' | 'not_ready' | 'shutting_down';
  ready: boolean;
  phase: string;
  uptime_s: number;
  startup_complete: boolean;
  accepting_requests: boolean;
  shutting_down: boolean;
  components: ReadinessComponents;
  degraded_dependencies: string[];
  failure_reasons: string[];
}

export interface LegacyHealthResponse {
  status: 'ok' | 'degraded' | 'starting' | 'shutting_down';
  graph_loaded: boolean;
  uptime_s: number;
}

export interface LivenessResponse {
  status: 'alive';
  phase: string;
  uptime_s: number;
}

export interface GraphStatsResponse {
  city: string;
  graph_loaded: boolean;
  nodes: number;
  edges: number;
  load_time_s: number | null;
  graph_path: string;
  graph_file_size_mb: number | null;
  memory_mb: number | null;
  [key: string]: unknown;
}

export interface GraphValidationResponse {
  valid: boolean;
  lat: number;
  lon: number;
  message: string;
}

export interface GraphSnapResponse {
  status: 'ok';
  message: string;
  [key: string]: unknown;
}

export type MatrixAlgorithm = 'source_dijkstra' | 'bidirectional_astar' | 'astar';

export interface MatrixLocation {
  id: string;
  lat: number;
  lon: number;
}

export interface MatrixRequest {
  locations: MatrixLocation[];
  algorithm: MatrixAlgorithm;
  use_cache: boolean;
}

export interface MatrixCacheMetadata {
  enabled: boolean;
  hit: boolean;
  key: string | null;
  ttl_seconds: number;
  error: string | null;
}

export interface MatrixPairFailure {
  from_index: number;
  to_index: number;
  from_id: string;
  to_id: string;
  error: string;
}

export interface MatrixResponse {
  status: string;
  n: number;
  algorithm: string;
  cache: MatrixCacheMetadata;
  locations: MatrixLocation[];
  matrix_distance_m: Array<Array<number | null>>;
  matrix_eta_s: Array<Array<number | null>>;
  pair_count: number;
  computed_pairs: number;
  failed_pairs: number;
  failures: MatrixPairFailure[];
  generation_time_ms: number;
  parallel_workers: number;
}

export interface RootResponse {
  status: string;
  service: string;
  version: string;
  phase: string;
  phase_code: string;
  docs: string;
  health: string;
  liveness: string;
  readiness: string;
  [key: string]: unknown;
}

export interface MetricSample {
  name: string;
  value: number;
  labels: Record<string, string>;
}

export interface EvidenceSummary {
  benchmark: string;
  phase_code: string;
  phase_name: string;
  overall_ok: boolean;
  validation_errors: string[];
  warnings: string[];
  target: string | undefined;
  raw_result_path: string | undefined;
  summary_result_path: string | undefined;
  details: Record<string, unknown>;
}

export interface TestInventory {
  test_file_count: number;
  explicit_test_function_count: number;
  note: string;
  recorded_run_counts: Array<{ source: string; passed: number | null; text: string }>;
}

export interface ArchitectureInventory {
  api: string[];
  core: string[];
  services: string[];
  infrastructure: string[];
  middleware: string[];
  observability: string[];
  schemas: string[];
  utils: string[];
  models: string[];
}

export interface DispatchMarker {
  id: string;
  label: string;
  coordinate: Coordinate;
}

export interface MapLocation {
  id: string;
  label: string;
  coordinate: Coordinate;
}

export interface RouteSegment {
  id: string;
  geometry: Coordinate[];
}

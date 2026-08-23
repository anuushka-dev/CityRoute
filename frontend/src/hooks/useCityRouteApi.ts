import { useCallback, useState } from 'react';
import {
  compareAdvancedStops,
  compareDispatch,
  compareRoute,
  compareStops,
  getRoute,
  optimizeStops,
} from '../api/cityRouteApi';
import type {
  AdvancedCompareResponse,
  Coordinate,
  DispatchCompareResponse,
  DispatchRequest,
  RouteComparisonResponse,
  RouteResponse,
  VrpCompareRequest,
  VrpCompareResponse,
  VrpGreedyResponse,
  VrpRequest,
  VrpAdvancedCompareRequest,
} from '../types/domain';

interface AsyncState<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: string | null;
}

const INITIAL_ASYNC_STATE: AsyncState<never> = {
  data: null,
  loading: false,
  error: null,
};

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

function useAsyncRequest<TResponse, TRequest>() {
  const [state, setState] = useState<AsyncState<TResponse>>(INITIAL_ASYNC_STATE);

  const run = useCallback(async (requestFunction: (request: TRequest) => Promise<TResponse>, request: TRequest) => {
    setState({ data: null, loading: true, error: null });
    try {
      const data = await requestFunction(request);
      setState({ data, loading: false, error: null });
      return data;
    } catch (error) {
      const message = getErrorMessage(error, 'The CityRoute request failed.');
      setState({ data: null, loading: false, error: message });
      return null;
    }
  }, []);

  return { ...state, run };
}

export function useRouteRequest() {
  return useDirectRequest<RouteResponse, [Coordinate, Coordinate]>(getRoute, 'Route request failed.');
}

export function useRouteComparison() {
  return useDirectRequest<RouteComparisonResponse, [Coordinate, Coordinate]>(compareRoute, 'Routing comparison failed.');
}

export function useStopOptimization() {
  const state = useAsyncRequest<VrpGreedyResponse, VrpRequest>();
  return {
    ...state,
    run: (request: VrpRequest) => state.run(optimizeStops, request),
  };
}

export function useStopComparison() {
  const state = useAsyncRequest<VrpCompareResponse, VrpCompareRequest>();
  return {
    ...state,
    run: (request: VrpCompareRequest) => state.run(compareStops, request),
  };
}

export function useAdvancedStopComparison() {
  const state = useAsyncRequest<AdvancedCompareResponse, VrpAdvancedCompareRequest>();
  return {
    ...state,
    run: (request: VrpAdvancedCompareRequest) => state.run(compareAdvancedStops, request),
  };
}

export function useDispatchRequest() {
  const state = useAsyncRequest<DispatchCompareResponse, DispatchRequest>();
  return {
    ...state,
    run: (request: DispatchRequest) => state.run(compareDispatch, request),
  };
}

function useDirectRequest<TResponse, TArguments extends readonly unknown[]>(
  requestFunction: (...args: TArguments) => Promise<TResponse>,
  fallbackError: string,
) {
  const [state, setState] = useState<AsyncState<TResponse>>(INITIAL_ASYNC_STATE);

  const run = useCallback(async (...args: TArguments) => {
    setState({ data: null, loading: true, error: null });
    try {
      const data = await requestFunction(...args);
      setState({ data, loading: false, error: null });
      return data;
    } catch (error) {
      const message = getErrorMessage(error, fallbackError);
      setState({ data: null, loading: false, error: message });
      return null;
    }
  }, [fallbackError, requestFunction]);

  return { ...state, run };
}

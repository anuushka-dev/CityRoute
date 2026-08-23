const API_PREFIX = import.meta.env.VITE_API_PREFIX ?? '/api';
const JSON_CONTENT_TYPE = 'application/json';
const DEFAULT_ERROR_MESSAGE = 'The CityRoute API request failed.';

export class ApiRequestError extends Error {
  readonly status: number;
  readonly path: string;
  readonly detail: unknown;

  constructor(status: number, path: string, detail: unknown) {
    super(extractErrorMessage(detail));
    this.name = 'ApiRequestError';
    this.status = status;
    this.path = path;
    this.detail = detail;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function extractErrorMessage(detail: unknown): string {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (!isRecord(detail)) return DEFAULT_ERROR_MESSAGE;
  for (const key of ['message', 'error', 'detail']) {
    const value = detail[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return DEFAULT_ERROR_MESSAGE;
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes(JSON_CONTENT_TYPE)) return response.json();
  return response.text();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      ...init,
      headers: {
        Accept: JSON_CONTENT_TYPE,
        ...(init?.body ? { 'Content-Type': JSON_CONTENT_TYPE } : {}),
        ...init?.headers,
      },
    });
  } catch (error) {
    throw new ApiRequestError(0, path, error instanceof Error ? error.message : error);
  }

  const body = await parseResponseBody(response);
  if (!response.ok) throw new ApiRequestError(response.status, path, body);
  return body as T;
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function post<TRequest, TResponse>(path: string, payload: TRequest): Promise<TResponse> {
  return request<TResponse>(path, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

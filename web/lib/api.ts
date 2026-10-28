// API configuration and utility functions

// Get API base URL from environment variable
// This is automatically set by start_web.py based on config/main.yaml
// The .env.local file is auto-generated on startup with the correct backend port
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE || "/";

/**
 * Construct a full API URL from a path
 * @param path - API path (e.g., '/api/v1/knowledge/list')
 * @returns Full URL (e.g., 'http://localhost:8000/api/v1/knowledge/list')
 */
export function apiUrl(path: string): string {
  // Remove leading slash if present to avoid double slashes
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  // Remove trailing slash from base URL if present
  const base = API_BASE_URL.endsWith("/")
    ? API_BASE_URL.slice(0, -1)
    : API_BASE_URL;

  return `${base}${normalizedPath}`;
}

/**
 * Construct a WebSocket URL from a path
 * @param path - WebSocket path (e.g., '/api/v1/solve')
 * @returns WebSocket URL (e.g., 'ws://localhost:{backend_port}/api/v1/solve')
 * Note: backend_port is configured in config/main.yaml
 */
export function wsUrl(path: string): string {
  let base = API_BASE_URL;
  if (typeof window !== "undefined" && (!base || base.startsWith("/"))) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    base = `${protocol}//${window.location.host}${base}`;
  } else {
    base = base.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
  }

  // Remove leading slash if present to avoid double slashes
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  // Remove trailing slash from base URL if present
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;

  return `${normalizedBase}${normalizedPath}`;
}

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return fetch(input, init);
}

/** Decode API failures without hiding proxy errors behind a JSON SyntaxError. */
export async function readApiResponse(response: Response): Promise<any> {
  const body = await response.text();
  let data: any;
  try {
    data = JSON.parse(body);
  } catch {
    throw new Error(`API request failed (${response.status}). ${[502, 504, 524].includes(response.status) ? "The server or upstream proxy timed out. A background task may still be running; check its status before retrying." : "The server returned an invalid response."}`);
  }
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : `API request failed (${response.status})`);
  }
  return data;
}

/** Poll slow LLM probes so external HTTP proxies never hold a 300s request. */
export async function connectionTest(url: string, init: RequestInit, background = false): Promise<Response> {
  const response = await apiFetch(background ? `${url}?background=true` : url, init);
  if (!background) return response;
  const started = await readApiResponse(response);
  const deadline = Date.now() + 330_000;
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 1000));
    const poll = await apiFetch(apiUrl(`/api/v1/config/llm-tests/${encodeURIComponent(started.test_id)}`));
    const state = await readApiResponse(poll);
    if (state.status === "completed") return new Response(JSON.stringify(state.result), { headers: { "Content-Type": "application/json" } });
  }
  throw new Error("Model test did not finish within 330 seconds. Retry when the server is ready.");
}

import { apiFetch } from '@/lib/api';
import { NextRequest, NextResponse } from "next/server";
import http from "node:http";
import https from "node:https";

const PRESENTON_INTERNAL_URL = (
  process.env.PRESENTON_INTERNAL_URL || "http://presenton"
).replace(/\/+$/, "");

const PRESENTON_FASTAPI_INTERNAL_URL = (
  process.env.PRESENTON_FASTAPI_INTERNAL_URL || PRESENTON_INTERNAL_URL
).replace(/\/+$/, "");

const PRESENTON_BASE_PATH = (
  process.env.PRESENTON_BASE_PATH || "/slide_pro/_presenton"
).replace(/\/+$/, "");

function sanitizeApiBase(value: string | undefined) {
  const normalized = (value || "").replace(/\/+$/, "");
  if (!normalized) return "";
  if (normalized.includes("__NEXT_PUBLIC_API_BASE_PLACEHOLDER__")) return "";
  return normalized;
}

const EDUNOTE_API_BASE = sanitizeApiBase(
  process.env.NEXT_PUBLIC_API_BASE_EXTERNAL ||
    process.env.PRESENTON_EDUNOTE_API_BASE ||
    process.env.NEXT_PUBLIC_API_BASE,
);

const BACKEND_PORT = process.env.BACKEND_PORT || "8001";
const EDUNOTE_API_ROOT = (
  EDUNOTE_API_BASE.replace(/\/api\/v1$/i, "").replace(/\/api$/i, "") ||
  `http://localhost:${BACKEND_PORT}`
).replace(/\/+$/, "");

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const revalidate = 0;

type BufferedUpstreamResponse = {
  status: number;
  statusText: string;
  headers: Headers;
  body: Blob;
};

const UPSTREAM_SOCKET_TIMEOUT_MS = 30 * 60 * 1000;

function buildTargetUrl(pathSegments: string[], search: string) {
  const joined = pathSegments.join("/");

  if (joined.startsWith("edunote-api/")) {
    const downstreamPath = joined.slice("edunote-api/".length);
    return `${EDUNOTE_API_ROOT}/${downstreamPath}${search}`;
  }

  if (joined.startsWith("api/v1/")) {
    return `${PRESENTON_FASTAPI_INTERNAL_URL}/${joined}${search}`;
  }

  if (joined.startsWith("app_data/") || joined.startsWith("static/")) {
    return `${PRESENTON_INTERNAL_URL}/${joined}${search}`;
  }

  const suffix = joined ? `/${joined}` : "";
  return `${PRESENTON_INTERNAL_URL}${PRESENTON_BASE_PATH}${suffix}${search}`;
}

function normalizeRedirectTarget(location: string, currentTarget: string) {
  let resolved: URL;

  try {
    resolved = new URL(location, currentTarget);
  } catch {
    return null;
  }

  const pathname = resolved.pathname || "/";
  const search = resolved.search || "";

  const internalHosts = new Set(["presenton", "localhost", "127.0.0.1"]);
  const isInternalHost = internalHosts.has(resolved.hostname);
  const isFastApiPort = resolved.port === "8000";

  if (
    (isInternalHost && (isFastApiPort || !resolved.port)) ||
    pathname.startsWith("/api/v1/")
  ) {
    if (
      pathname.startsWith("/api/v1/") ||
      pathname.startsWith("/app_data/") ||
      pathname.startsWith("/static/")
    ) {
      if (pathname.startsWith("/api/v1/")) {
        return `${PRESENTON_FASTAPI_INTERNAL_URL}${pathname}${search}`;
      }
      return `${PRESENTON_INTERNAL_URL}${pathname}${search}`;
    }

    if (pathname.startsWith(`${PRESENTON_BASE_PATH}/`)) {
      return `${PRESENTON_INTERNAL_URL}${pathname}${search}`;
    }
  }

  return null;
}

function appendNodeHeaders(target: Headers, source: http.IncomingHttpHeaders) {
  for (const [key, value] of Object.entries(source)) {
    if (typeof value === "undefined") continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        target.append(key, item);
      }
      continue;
    }
    target.set(key, value);
  }
}

function normalizeProxyResponseHeaders(
  sourceHeaders: Headers,
  targetUrl: string,
) {
  const responseHeaders = new Headers(sourceHeaders);
  const responseLocation = responseHeaders.get("location");

  responseHeaders.delete("content-length");
  responseHeaders.delete("transfer-encoding");

  if (!responseLocation) {
    return responseHeaders;
  }

  const normalizedLocation = normalizeRedirectTarget(responseLocation, targetUrl);
  if (!normalizedLocation) {
    return responseHeaders;
  }

  const normalizedUrl = new URL(normalizedLocation);
  responseHeaders.set(
    "location",
    `${PRESENTON_BASE_PATH}${normalizedUrl.pathname.replace(
      PRESENTON_BASE_PATH,
      "",
    )}${normalizedUrl.search}`,
  );

  return responseHeaders;
}

async function requestBufferedUpstream(
  targetUrl: string,
  method: string,
  headers: Headers,
  bodyBuffer?: Blob,
): Promise<BufferedUpstreamResponse> {
  const url = new URL(targetUrl);
  const client = url.protocol === "https:" ? https : http;
  const body =
    bodyBuffer && bodyBuffer.size > 0
      ? new Uint8Array(await bodyBuffer.arrayBuffer())
      : undefined;

  return new Promise((resolve, reject) => {
    const requestHeaders = Object.fromEntries(headers.entries());
    if (body) {
      requestHeaders["content-length"] = String(body.byteLength);
    } else {
      delete requestHeaders["content-length"];
    }

    const upstreamRequest = client.request(
      {
        protocol: url.protocol,
        hostname: url.hostname,
        port: url.port,
        path: `${url.pathname}${url.search}`,
        method,
        headers: requestHeaders,
        agent: false,
      },
      (upstreamResponse) => {
        const chunks: Buffer[] = [];

        upstreamResponse.on("data", (chunk) => {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
        });

        upstreamResponse.on("end", () => {
          const responseHeaders = new Headers();
          appendNodeHeaders(responseHeaders, upstreamResponse.headers);
          resolve({
            status: upstreamResponse.statusCode || 502,
            statusText: upstreamResponse.statusMessage || "",
            headers: responseHeaders,
            body: new Blob([Buffer.concat(chunks)]),
          });
        });

        upstreamResponse.on("error", reject);
      },
    );

    upstreamRequest.setTimeout(UPSTREAM_SOCKET_TIMEOUT_MS, () => {
      upstreamRequest.destroy(
        new Error(
          `Upstream request timed out after ${UPSTREAM_SOCKET_TIMEOUT_MS}ms`,
        ),
      );
    });

    upstreamRequest.on("error", reject);

    if (body) {
      upstreamRequest.write(body);
    }

    upstreamRequest.end();
  });
}

async function requestBufferedUpstreamWithRedirects(
  targetUrl: string,
  method: string,
  headers: Headers,
  bodyBuffer?: Blob,
  maxRedirects = 5,
): Promise<BufferedUpstreamResponse> {
  let currentUrl = targetUrl;
  let currentMethod = method;
  let currentBody = bodyBuffer;

  for (let attempt = 0; attempt <= maxRedirects; attempt += 1) {
    const upstream = await requestBufferedUpstream(
      currentUrl,
      currentMethod,
      headers,
      currentBody,
    );
    const location = upstream.headers.get("location");
    const isRedirect =
      upstream.status === 301 ||
      upstream.status === 302 ||
      upstream.status === 303 ||
      upstream.status === 307 ||
      upstream.status === 308;

    if (!isRedirect || !location) {
      return upstream;
    }

    const redirectedTarget = normalizeRedirectTarget(location, currentUrl);
    if (!redirectedTarget) {
      return upstream;
    }

    currentUrl = redirectedTarget;

    if (
      upstream.status === 301 ||
      upstream.status === 302 ||
      upstream.status === 303
    ) {
      currentMethod = "GET";
      currentBody = undefined;
    }
  }

  throw new Error(`Too many upstream redirects while proxying ${targetUrl}`);
}

async function fetchUpstreamWithRedirects(
  targetUrl: string,
  init: RequestInit,
  maxRedirects = 5,
): Promise<Response> {
  let currentUrl = targetUrl;
  let currentInit = init;

  for (let attempt = 0; attempt <= maxRedirects; attempt += 1) {
    const upstream = await apiFetch(currentUrl, {
      ...currentInit,
      redirect: "manual",
    });

    const location = upstream.headers.get("location");
    const isRedirect =
      upstream.status === 301 ||
      upstream.status === 302 ||
      upstream.status === 303 ||
      upstream.status === 307 ||
      upstream.status === 308;

    if (!isRedirect || !location) {
      return upstream;
    }

    const redirectedTarget = normalizeRedirectTarget(location, currentUrl);
    if (!redirectedTarget) {
      return upstream;
    }

    currentUrl = redirectedTarget;

    if (
      upstream.status === 301 ||
      upstream.status === 302 ||
      upstream.status === 303
    ) {
      currentInit = {
        ...currentInit,
        method: "GET",
        body: undefined,
      };
    }
  }

  throw new Error(`Too many upstream redirects while proxying ${targetUrl}`);
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> },
) {
  const { path = [] } = await context.params;
  const joinedPath = path.join("/");
  const targetUrl = buildTargetUrl(path, request.nextUrl.search);
  const upstreamHeaders = new Headers(request.headers);
  let bodyBuffer: Blob | undefined;

  // Fetch decompresses upstream bodies; request identity to avoid duplicate decoding.
  upstreamHeaders.set("accept-encoding", "identity");
  upstreamHeaders.delete("connection");
  upstreamHeaders.delete("content-length");

  const init: RequestInit = {
    method: request.method,
    headers: upstreamHeaders,
    cache: "no-store",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    const body = await request.arrayBuffer();
    if (body.byteLength > 0) {
      bodyBuffer = new Blob([body]);
      init.body = bodyBuffer;
    }
  }

  try {
    const shouldUseBufferedProxy =
      request.method !== "GET" &&
      request.method !== "HEAD" &&
      joinedPath.startsWith("api/v1/");

    if (shouldUseBufferedProxy) {
      const upstream = await requestBufferedUpstreamWithRedirects(
        targetUrl,
        request.method,
        upstreamHeaders,
        bodyBuffer,
      );

      return new NextResponse(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: normalizeProxyResponseHeaders(upstream.headers, targetUrl),
      });
    }

    const upstream = await fetchUpstreamWithRedirects(targetUrl, {
      ...init,
      body: bodyBuffer,
    });

    const responseHeaders = normalizeProxyResponseHeaders(upstream.headers, targetUrl);
    // Node fetch already decoded gzip/br, even if upstream ignored identity.
    responseHeaders.delete("content-encoding");
    return new NextResponse(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error("Slide Generator proxy request failed", targetUrl, error);
    return new NextResponse("Bad Gateway", { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
export const HEAD = proxy;

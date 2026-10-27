import { apiFetch } from '@/lib/api';
import { NextRequest, NextResponse } from "next/server";

const LOCAL_BASE_PATH = "/research/_quiz_gen_plus";
const QUIZ_GEN_PLUS_UPSTREAM = new URL(
  process.env.QUIZ_GEN_PLUS_UPSTREAM_URL ||
    "https://banacumbe27.github.io/pdf_quiz_generator/",
);
const UPSTREAM_ORIGIN = QUIZ_GEN_PLUS_UPSTREAM.origin;
const UPSTREAM_BASE_PATH = QUIZ_GEN_PLUS_UPSTREAM.pathname.replace(/\/+$/, "");

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const revalidate = 0;

function buildTargetUrl(pathSegments: string[], search: string) {
  const joined = pathSegments.join("/");
  const suffix = joined ? `/${joined}` : "/";
  return `${UPSTREAM_ORIGIN}${UPSTREAM_BASE_PATH}${suffix}${search}`;
}

function normalizeRedirectTarget(location: string, currentTarget: string) {
  let resolved: URL;

  try {
    resolved = new URL(location, currentTarget);
  } catch {
    return null;
  }

  if (resolved.origin !== UPSTREAM_ORIGIN) {
    return null;
  }

  if (!resolved.pathname.startsWith(UPSTREAM_BASE_PATH)) {
    return null;
  }

  const downstreamPath = resolved.pathname.slice(UPSTREAM_BASE_PATH.length) || "/";
  return `${LOCAL_BASE_PATH}${downstreamPath}${resolved.search}`;
}

function normalizeProxyResponseHeaders(sourceHeaders: Headers, targetUrl: string) {
  const responseHeaders = new Headers(sourceHeaders);
  const responseLocation = responseHeaders.get("location");

  responseHeaders.delete("content-length");
  responseHeaders.delete("transfer-encoding");
  responseHeaders.delete("content-security-policy");
  responseHeaders.delete("content-security-policy-report-only");
  responseHeaders.delete("x-frame-options");
  responseHeaders.delete("frame-options");

  if (!responseLocation) {
    return responseHeaders;
  }

  const normalizedLocation = normalizeRedirectTarget(responseLocation, targetUrl);
  if (!normalizedLocation) {
    return responseHeaders;
  }

  responseHeaders.set("location", normalizedLocation);
  return responseHeaders;
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

    currentUrl = buildTargetUrl(
      redirectedTarget.replace(`${LOCAL_BASE_PATH}/`, "").split("/").filter(Boolean),
      new URL(location, currentUrl).search,
    );

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
  const targetUrl = buildTargetUrl(path, request.nextUrl.search);
  const upstreamHeaders = new Headers(request.headers);

  upstreamHeaders.delete("connection");
  upstreamHeaders.delete("content-length");
  upstreamHeaders.delete("host");

  const init: RequestInit = {
    method: request.method,
    headers: upstreamHeaders,
    cache: "no-store",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    const body = await request.arrayBuffer();
    if (body.byteLength > 0) {
      init.body = body;
    }
  }

  try {
    const upstream = await fetchUpstreamWithRedirects(targetUrl, init);

    return new NextResponse(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: normalizeProxyResponseHeaders(upstream.headers, targetUrl),
    });
  } catch (error) {
    console.error("Quiz Gen Plus proxy request failed", targetUrl, error);
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

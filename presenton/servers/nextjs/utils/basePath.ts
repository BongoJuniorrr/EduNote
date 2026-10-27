const DEFAULT_PROXY_BASE_PATH = "/slide_pro/_presenton";
const rawBasePath = process.env.NEXT_PUBLIC_BASE_PATH || DEFAULT_PROXY_BASE_PATH;

export const SLIDES_BASE_PATH = rawBasePath.replace(/\/+$/, "");

function normalizeProjectPath(path: string): string {
  if (!path) return path;
  if (/^(?:app_data|static|api|edunote-api)\//.test(path)) {
    return `/${path}`;
  }
  return path;
}

export function withBasePath(path: string): string {
  if (!path) return path;
  const normalizedPath = normalizeProjectPath(path);
  if (/^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(normalizedPath)) return normalizedPath;
  if (normalizedPath.startsWith("data:") || normalizedPath.startsWith("blob:")) return normalizedPath;
  if (!normalizedPath.startsWith("/")) return normalizedPath;
  if (!SLIDES_BASE_PATH) return normalizedPath;
  if (
    normalizedPath === SLIDES_BASE_PATH ||
    normalizedPath.startsWith(`${SLIDES_BASE_PATH}/`)
  ) {
    return normalizedPath;
  }
  return `${SLIDES_BASE_PATH}${normalizedPath}`;
}

export function buildLocalAppUrl(path: string): string {
  return `http://localhost${withBasePath(path)}`;
}

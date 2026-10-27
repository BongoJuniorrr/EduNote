export function safeImageUrl(value: string | null | undefined): string {
  if (!value) return "";
  if (/^data:image\/(?:png|jpe?g|gif|webp|svg\+xml);base64,[A-Za-z0-9+/=\s]+$/i.test(value)) return value;
  try {
    const parsed = new URL(value, typeof window !== "undefined" ? window.location.origin : "http://localhost");
    if (parsed.protocol === "https:" || parsed.protocol === "http:" || parsed.protocol === "blob:") return parsed.href;
  } catch { /* Invalid or executable URLs are not image sources. */ }
  return "";
}

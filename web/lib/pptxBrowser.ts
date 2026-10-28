// Use the distribution built for browsers; the ESM entry imports Node fs/https.
let loading: Promise<typeof import("pptxgenjs").default> | null = null;
export function loadPptxGenJS(): Promise<typeof import("pptxgenjs").default> {
  if (!loading) loading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/vendor/pptxgen.bundle.js";
    script.onload = () => {
      const constructor = (window as unknown as { PptxGenJS?: typeof import("pptxgenjs").default }).PptxGenJS;
      if (constructor) resolve(constructor);
      else { loading = null; script.remove(); reject(new Error("PowerPoint export library failed to initialize")); }
    };
    script.onerror = () => { loading = null; script.remove(); reject(new Error("Cannot load PowerPoint export library")); };
    document.head.appendChild(script);
  });
  return loading;
}

import { copyFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const root = new URL("../", import.meta.url);
await mkdir(new URL("public/vendor/", root), { recursive: true });
await copyFile(new URL("node_modules/pptxgenjs/dist/pptxgen.bundle.js", root), new URL("public/vendor/pptxgen.bundle.js", root));

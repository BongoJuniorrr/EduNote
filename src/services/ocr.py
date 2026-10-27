"""OCR policy and extraction adapters for the system queue."""

import os
from pathlib import Path
import subprocess
import tempfile


def ensure_ocr_allowed(mode: str, rank: str = "local", remote: bool = False) -> None:
    if mode not in {"basic", "heavy"}:
        raise ValueError("OCR mode must be basic or heavy")
    if remote and os.getenv("EDUNOTE_ALLOW_REMOTE_OCR", "false").lower() != "true":
        raise PermissionError("Remote OCR is disabled")


def extract_basic(path: Path) -> dict[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".rst"}:
        return {
            "text": path.read_text(encoding="utf-8", errors="ignore")[:100_000],
            "engine": "text",
        }
    if suffix == ".pdf":
        import fitz

        with fitz.open(path) as document:
            text = "\n\n".join(page.get_text("text") for page in document)
        if text.strip():
            return {"text": text[:100_000], "engine": "pymupdf"}
        return _ocr_image_pdf(path)
    return _ocr_image(path)


def _ocr_image(path: Path) -> dict[str, str]:
    try:
        from PIL import Image
        import pytesseract

        return {
            "text": pytesseract.image_to_string(Image.open(path))[:100_000],
            "engine": "tesseract",
        }
    except ImportError:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as output:
            output_path = Path(output.name)
        try:
            subprocess.run(
                ["tesseract", str(path), str(output_path.with_suffix(""))],
                check=True,
                capture_output=True,
            )
            return {
                "text": output_path.read_text(encoding="utf-8", errors="ignore")[:100_000],
                "engine": "tesseract-cli",
            }
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise RuntimeError(
                "Install pytesseract/Pillow or the tesseract binary for basic OCR"
            ) from error
        finally:
            output_path.unlink(missing_ok=True)
            output_path.with_suffix(".txt").unlink(missing_ok=True)


def _ocr_image_pdf(path: Path) -> dict[str, str]:
    import fitz

    with tempfile.TemporaryDirectory(prefix="edunote-ocr-") as directory:
        image_paths = []
        with fitz.open(path) as document:
            for index, page in enumerate(document):
                image_path = Path(directory) / f"page-{index}.png"
                page.get_pixmap(matrix=fitz.Matrix(2, 2)).save(image_path)
                image_paths.append(image_path)
        results = [_ocr_image(image_path)["text"] for image_path in image_paths]
    return {"text": "\n\n".join(results)[:100_000], "engine": "tesseract-pdf"}


def extract_heavy(path: Path, gpu_index: int = 0) -> dict[str, str]:
    """Run the configured Transformers OCR model and unload it after the job."""
    model_name = os.getenv("EDUNOTE_HEAVY_OCR_MODEL", "microsoft/trocr-base-printed").strip()
    if not model_name:
        raise RuntimeError("EDUNOTE_HEAVY_OCR_MODEL is not configured")
    try:
        from PIL import Image
        import torch
        from transformers import AutoProcessor, VisionEncoderDecoderModel
    except ImportError as error:
        raise RuntimeError("Install torch, Pillow and transformers for heavy OCR") from error

    if path.suffix.lower() == ".pdf":
        import fitz

        with fitz.open(path) as document:
            images = []
            for page in document[:50]:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                images.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
    else:
        images = [Image.open(path).convert("RGB")]

    device = f"cuda:{gpu_index}" if torch.cuda.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(model_name)
    model = VisionEncoderDecoderModel.from_pretrained(model_name).to(device)
    model.eval()
    try:
        texts = []
        for image in images:
            inputs = processor(images=image, return_tensors="pt").pixel_values.to(device)
            with torch.inference_mode():
                generated = model.generate(inputs, max_new_tokens=256)
            texts.append(processor.batch_decode(generated, skip_special_tokens=True)[0].strip())
        return {"text": "\n\n".join(texts)[:100_000], "engine": model_name}
    finally:
        del model
        del processor
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

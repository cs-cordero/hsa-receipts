"""Convert receipt images and PDFs to PDF/A format for archival."""

import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

GS_BINARY = os.environ.get("GS_BINARY", "/var/task/bin/gs")

_CONTENT_TYPE_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def convert_to_pdfa(data: bytes, content_type: str) -> bytes:
    """Convert an image or PDF to PDF/A-2b format using Ghostscript.

    Images are first converted to PDF via Pillow, then Ghostscript produces PDF/A.
    PDFs go directly through Ghostscript.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        if content_type == "application/pdf":
            input_pdf = tmp / "input.pdf"
            input_pdf.write_bytes(data)
        else:
            input_pdf = tmp / "intermediate.pdf"
            suffix = _CONTENT_TYPE_SUFFIX.get(content_type, ".bin")
            image_path = tmp / f"input{suffix}"
            image_path.write_bytes(data)
            img = Image.open(image_path)
            img.save(str(input_pdf), "PDF", resolution=300.0)

        output_pdf = tmp / "output.pdf"

        result = subprocess.run(
            [
                GS_BINARY,
                "-dPDFA=2",
                "-dBATCH",
                "-dNOPAUSE",
                "-sColorConversionStrategy=UseDeviceIndependentColor",
                "-sDEVICE=pdfwrite",
                f"-sOutputFile={output_pdf}",
                str(input_pdf),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Ghostscript failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout.decode(errors='replace')}\n"
                f"stderr: {result.stderr.decode(errors='replace')}"
            )

        return output_pdf.read_bytes()

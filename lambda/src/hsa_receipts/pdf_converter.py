"""Convert receipt images to PDF/A format for archival."""


def convert_to_pdfa(image_data: bytes, content_type: str) -> bytes:
    """Convert an image to PDF/A format.

    Uses Ghostscript for the PDF/A conversion.
    """
    raise NotImplementedError

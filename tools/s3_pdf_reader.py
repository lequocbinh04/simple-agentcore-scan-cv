"""Custom Strands tool to read PDF files from S3 and extract text content."""

import io
import boto3
from pypdf import PdfReader
from strands import tool


@tool
def read_pdf_from_s3(bucket: str, key: str) -> str:
    """Read a PDF file from S3 and extract its text content.

    Use this tool when you need to read and extract text from a PDF document
    stored in Amazon S3. Returns the full text content of the PDF.

    Args:
        bucket: The S3 bucket name where the PDF is stored.
        key: The S3 object key (path) to the PDF file.
    """
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=bucket, Key=key)
    pdf_bytes = response["Body"].read()

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            pages.append(f"--- Page {i + 1} ---\n{text}")

    if not pages:
        return "ERROR: Could not extract any text from the PDF. The file may be image-based or corrupted."

    return "\n\n".join(pages)

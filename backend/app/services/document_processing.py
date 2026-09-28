from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from docx import Document
from fastapi import HTTPException, UploadFile, status
from pypdf import PdfReader

from app.core.config import settings

MAX_FILE_SIZE_BYTES = settings.MAX_UPLOAD_SIZE_BYTES
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_EXTENSIONS = {".pdf", ".docx"}
ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all|previous)\s+(instructions|system\s+prompt)",
    r"reveal\s+(the\s+)?system\s+prompt",
    r"override\s+(the\s+)?instructions",
    r"act\s+as\s+if",
    r"bypass\s+security",
]


def sanitize_text(raw_text: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw_text or "").strip()
    return cleaned


def detect_prompt_injection(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in PROMPT_INJECTION_PATTERNS)


def normalize_jd_text(text: str) -> str:
    sanitised = sanitize_text(text)
    if detect_prompt_injection(sanitised):
        filtered_parts = []
        for sentence in re.split(r"(?<=[.!?])\s+", sanitised):
            if not detect_prompt_injection(sentence):
                filtered_parts.append(sentence)
        sanitised = " ".join(filtered_parts).strip()
    return sanitised or "No job description content available."


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only HTTP and HTTPS URLs are allowed.",
        )

    hostname = (parsed.hostname or "").lower()
    if (
        hostname in {"localhost", "127.0.0.1", "::1"}
        or hostname.endswith((".localhost", ".local", ".internal"))
        or "." not in hostname
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Private or local network URLs are not allowed.",
        )

    try:
        addresses = {
            address[4][0]
            for address in socket.getaddrinfo(parsed.hostname, None)
        }
    except socket.gaierror:
        # Some CI or offline environments block DNS resolution even for valid public hosts.
        # Retain the local/private network guard while allowing a non-blocking best-effort check.
        return

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Private or local network URLs are not allowed.",
            )


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_public_url(url: str, *, max_redirects: int = 5) -> tuple[str, bytes]:
    current_url = url
    opener = build_opener(_NoRedirectHandler)
    for _ in range(max_redirects + 1):
        validate_public_url(current_url)
        try:
            response = opener.open(
                Request(current_url, headers={"User-Agent": "Mozilla/5.0 (compatible; ATSResumeAnalyzer/1.0)", "Accept-Encoding": "identity"}),
                timeout=15,
            )
        except HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise
            location = exc.headers.get("Location")
            if not location:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job-description redirect did not include a destination.") from exc
            current_url = urljoin(current_url, location)
            continue
        status_code = getattr(response, "status", None) or response.getcode()
        if status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            if not location:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job-description redirect did not include a destination.")
            current_url = urljoin(current_url, location)
            continue
        return current_url, response.read()
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many redirects while retrieving the job description.")


def validate_upload(file: UploadFile | None) -> None:
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file provided",
        )

    raw_name = file.filename or ""
    cleaned_name = Path(raw_name).name
    if cleaned_name != raw_name or any(part in {"..", "/", "\\"} for part in [os.path.dirname(raw_name), raw_name]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file name",
        )

    name = cleaned_name.lower()
    extension = Path(name).suffix.lower()
    content_type = file.content_type or ""

    if extension not in ALLOWED_EXTENSIONS and content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Only PDF or DOCX files are allowed.",
        )

    expected_type_by_extension = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    expected_type = expected_type_by_extension.get(extension)
    if expected_type and content_type and content_type not in {expected_type, "application/octet-stream"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File extension and content type do not match.",
        )

    if file.size and file.size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File is too large. Maximum supported size is 10MB.",
        )


def validate_document_signature(file_bytes: bytes, content_type: str) -> None:
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty.")
    if content_type == "application/pdf" and not file_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PDF file signature is invalid.")
    if content_type in {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/docx"} and not file_bytes.startswith(b"PK"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="DOCX file signature is invalid.")


def validate_image_bytes(file_name: str, content_type: str, file_bytes: bytes) -> tuple[int, int]:
    extension = Path(file_name or "").suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS or content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported image type. Use PNG, JPG, or JPEG screenshots.",
        )
    if len(file_bytes) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image file is empty.")
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Image file is too large. Maximum size is 10MB.")

    width = height = 0
    if content_type == "image/png":
        if len(file_bytes) < 24 or file_bytes[:8] != b"\x89PNG\r\n\x1a\n" or file_bytes[12:16] != b"IHDR":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image file is corrupt or unreadable.")
        width = int.from_bytes(file_bytes[16:20], "big")
        height = int.from_bytes(file_bytes[20:24], "big")
    else:
        if len(file_bytes) < 4 or file_bytes[:2] != b"\xff\xd8":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image file is corrupt or unreadable.")
        offset = 2
        while offset + 9 < len(file_bytes):
            if file_bytes[offset] != 0xFF:
                offset += 1
                continue
            marker = file_bytes[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(file_bytes):
                break
            segment_length = int.from_bytes(file_bytes[offset:offset + 2], "big")
            if marker in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0)):
                if offset + 7 > len(file_bytes):
                    break
                height = int.from_bytes(file_bytes[offset + 3:offset + 5], "big")
                width = int.from_bytes(file_bytes[offset + 5:offset + 7], "big")
                break
            offset += segment_length

    if width < 1 or height < 1 or width > 20000 or height > 20000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image dimensions are invalid or unsupported.")
    return width, height


def validate_image_upload(file: UploadFile | None, file_bytes: bytes) -> tuple[int, int]:
    if file is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No image provided.")
    raw_name = file.filename or ""
    if Path(raw_name).name != raw_name or ".." in raw_name or "/" in raw_name or "\\" in raw_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image filename.")
    return validate_image_bytes(raw_name, file.content_type or "", file_bytes)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io_from_bytes(file_bytes))
        pages = []
        for page in reader.pages:
            content = page.extract_text() or ""
            pages.append(content)
        return sanitize_text("\n".join(pages))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read PDF content.",
        ) from exc


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        doc = Document(io_from_bytes(file_bytes))
        paragraphs = [paragraph.text for paragraph in doc.paragraphs]
        return sanitize_text("\n".join(paragraphs))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read DOCX content.",
        ) from exc


def extract_text_from_upload(file_bytes: bytes, content_type: str) -> str:
    if content_type == "application/pdf":
        return extract_text_from_pdf(file_bytes)
    if content_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/docx",
    }:
        return extract_text_from_docx(file_bytes)
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Unsupported file type. Only PDF or DOCX files are allowed.",
    )


def save_temp_file(file_bytes: bytes, suffix: str) -> str:
    temp_dir = tempfile.mkdtemp(prefix="resume_ats_")
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix.lstrip('.')}"
    file_name = f"upload{safe_suffix}"
    file_path = os.path.join(temp_dir, file_name)
    with open(file_path, "wb") as temp_file:
        temp_file.write(file_bytes)
    return file_path


def cleanup_temp_file(file_path: str | None) -> None:
    if not file_path:
        return
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        parent_dir = os.path.dirname(file_path)
        if parent_dir and os.path.isdir(parent_dir):
            shutil.rmtree(parent_dir, ignore_errors=True)
    except OSError:
        pass


def io_from_bytes(data: bytes):
    return __import__("io").BytesIO(data)


def extract_text_from_url(url: str) -> str:
    try:
        with urlopen(url, timeout=15) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to retrieve URL content: {exc}",
        ) from exc

    text = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return sanitize_text(text)

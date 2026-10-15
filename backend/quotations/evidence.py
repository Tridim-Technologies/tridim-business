"""Private expense evidence validation, storage, and malware scanning."""

import hashlib
import io
import os
import socket
import struct
import uuid
import warnings
from pathlib import Path

from django.conf import settings
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader


class EvidenceError(Exception):
    """A safe, user-facing evidence validation or scanner failure."""


class EvidenceScannerUnavailable(Exception):
    """The configured local malware scanner could not provide a safe result."""


def read_upload(upload):
    limit = settings.EXPENSE_EVIDENCE_MAX_FILE_BYTES
    if upload.size < 1 or upload.size > limit:
        raise EvidenceError("File is empty or exceeds the configured size limit.")
    chunks = []
    total = 0
    for chunk in upload.chunks():
        total += len(chunk)
        if total > limit:
            raise EvidenceError("File exceeds the maximum upload size.")
        chunks.append(chunk)
    content = b"".join(chunks)
    if len(content) != upload.size:
        raise EvidenceError("Upload size did not match the received file.")
    return content


def validate_content(filename, declared_type, content):
    extension = Path(filename or "").suffix.lower()
    if extension in {".jpg", ".jpeg"}:
        expected_type = "image/jpeg"
        if not content.startswith(b"\xff\xd8\xff"):
            raise EvidenceError("File content does not match a JPEG image.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    _validate_image(image)
                    image.verify()
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
        ):
            raise EvidenceError(
                "JPEG image is malformed or exceeds image limits."
            ) from None
        except Image.DecompressionBombWarning:
            raise EvidenceError("Image exceeds image limits.") from None
    elif extension == ".png":
        expected_type = "image/png"
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise EvidenceError("File content does not match a PNG image.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    _validate_image(image)
                    image.verify()
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
        ):
            raise EvidenceError(
                "PNG image is malformed or exceeds image limits."
            ) from None
        except Image.DecompressionBombWarning:
            raise EvidenceError("Image exceeds image limits.") from None
    elif extension == ".pdf":
        expected_type = "application/pdf"
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
            raise EvidenceError("File content does not match a complete PDF document.")
        try:
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise EvidenceError(
                    "Encrypted or password-protected PDFs are not accepted."
                )
            if not 1 <= len(reader.pages) <= 100:
                raise EvidenceError("PDF must contain between 1 and 100 pages.")
        except EvidenceError:
            raise
        except Exception:
            raise EvidenceError(
                "PDF is malformed or could not be safely parsed."
            ) from None
    else:
        raise EvidenceError("Only JPEG, PNG, and PDF files are accepted.")

    if (declared_type or "").lower() != expected_type:
        raise EvidenceError("Declared file type does not match inspected content.")
    return expected_type


def _validate_image(image):
    width, height = image.size
    if width < 1 or height < 1 or width * height > 40_000_000:
        raise EvidenceError("Image dimensions exceed the allowed limit.")


class PrivateLocalEvidenceStorage:
    """Private local storage for synthetic development data only."""

    def __init__(self, root=None):
        self.root = Path(root or settings.EXPENSE_EVIDENCE_STORAGE_ROOT).expanduser()

    def _check_root(self):
        if not self.root.is_absolute():
            raise EvidenceError("Private evidence storage path must be absolute.")
        if self.root.is_symlink():
            raise EvidenceError("Private evidence storage is unavailable.")
        resolved = self.root.resolve()
        if resolved == Path(resolved.anchor):
            raise EvidenceError("Private evidence storage path is unsafe.")
        base = Path(settings.BASE_DIR).resolve()
        forbidden = (base / "backend", base / "frontend", base / "static")
        if resolved == base or any(
            resolved == path or path in resolved.parents for path in forbidden
        ):
            raise EvidenceError(
                "Private evidence storage cannot be under a public or application directory."
            )
        for public_root in (
            getattr(settings, "STATIC_ROOT", None),
            getattr(settings, "MEDIA_ROOT", None),
        ):
            if public_root and (
                resolved == Path(public_root).resolve()
                or Path(public_root).resolve() in resolved.parents
            ):
                raise EvidenceError(
                    "Private evidence storage cannot be under a public or application directory."
                )
        return resolved

    def _path(self, key):
        if len(key) != 32 or any(char not in "0123456789abcdef" for char in key):
            raise EvidenceError("Invalid storage reference.")
        self._check_root()
        return self.root / f"{key}.evidence"

    def put(self, content):
        self._check_root()
        created_root = False
        try:
            self.root.mkdir(parents=True, mode=0o700)
            created_root = True
        except FileExistsError:
            if not self.root.is_dir():
                raise EvidenceError(
                    "Private evidence storage is unavailable."
                ) from None
        if created_root:
            os.chmod(self.root, 0o700)
        elif self.root.stat().st_mode & 0o077:
            raise EvidenceError("Private evidence directory permissions are too broad.")
        key = uuid.uuid4().hex
        path = self._path(key)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return key

    def get(self, key):
        try:
            path = self._path(key)
            if path.is_symlink():
                raise EvidenceError("Evidence is unavailable.")
            return path.read_bytes()
        except (FileNotFoundError, OSError):
            raise EvidenceError("Evidence is unavailable.") from None

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)

    def exists(self, key):
        return self._path(key).is_file()


class ClamAVUnixScanner:
    """Use a local ClamAV daemon's INSTREAM protocol; never fall back clean."""

    def __init__(self, socket_path=None, timeout=10):
        self.socket_path = socket_path or settings.EXPENSE_EVIDENCE_CLAMD_SOCKET
        self.timeout = timeout

    def scan(self, content):
        if not self.socket_path:
            raise EvidenceScannerUnavailable("Malware scanner is not configured.")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout)
                connection.connect(self.socket_path)
                connection.sendall(b"zINSTREAM\0")
                for offset in range(0, len(content), 64 * 1024):
                    chunk = content[offset : offset + 64 * 1024]
                    connection.sendall(struct.pack("!I", len(chunk)) + chunk)
                connection.sendall(b"\x00\x00\x00\x00")
                response = bytearray()
                while len(response) <= 1024:
                    part = connection.recv(256)
                    if not part:
                        break
                    response.extend(part)
                    if b"\x00" in part:
                        break
        except (OSError, TimeoutError) as error:
            raise EvidenceScannerUnavailable(
                "Malware scanner is unavailable."
            ) from error

        result = bytes(response).split(b"\x00", 1)[0].decode("ascii", errors="replace")
        if result.endswith(": OK"):
            return True
        if result.endswith("FOUND"):
            return False
        raise EvidenceScannerUnavailable("Malware scanner returned no safe result.")


def content_digest(content):
    return hashlib.sha256(content).hexdigest()

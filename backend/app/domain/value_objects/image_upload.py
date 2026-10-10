"""An image a human attaches to a topic. Validated from its bytes: the client-declared type is never trusted."""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.exceptions import ImageTooLarge, UnsupportedImageType

MAX_IMAGE_BYTES = 5 * 1024 * 1024


def sniff_image_type(body: bytes) -> tuple[str, str] | None:
    """(content type, file extension) from the leading magic bytes."""
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", "gif"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def display_filename(filename: str | None) -> str:
    # shown in the UI only; the storage key never contains it
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:200] or "image"


@dataclass(frozen=True)
class ImageUpload:
    filename: str
    content_type: str
    extension: str
    body: bytes

    @property
    def size(self) -> int:
        return len(self.body)

    @classmethod
    def validate(cls, filename: str | None, body: bytes) -> ImageUpload:
        if len(body) > MAX_IMAGE_BYTES:
            raise ImageTooLarge(MAX_IMAGE_BYTES)
        sniffed = sniff_image_type(body)
        if sniffed is None:
            raise UnsupportedImageType()
        content_type, extension = sniffed
        return cls(filename=display_filename(filename), content_type=content_type, extension=extension, body=body)

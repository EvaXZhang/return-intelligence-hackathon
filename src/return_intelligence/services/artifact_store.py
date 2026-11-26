from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

from PIL import Image

from ..domain.errors import ValidationError


class LocalPhotoStore:
    required = ("front", "left", "right")

    def __init__(self, root: Path):
        self.root = Path(root)

    def save(self, return_id: str, uploads: dict[str, bytes]):
        missing = set(self.required) - set(uploads)
        if missing:
            raise ValidationError("missing required photos: " + ", ".join(sorted(missing)))
        if sum(len(value) for value in uploads.values()) > 30 * 1024 * 1024:
            raise ValidationError("uploads exceed 30 MB total")
        target = self.root / return_id
        written = []
        records = []
        try:
            target.mkdir(parents=True, exist_ok=True)
            for angle, data in uploads.items():
                if angle not in self.required:
                    continue
                if len(data) > 10 * 1024 * 1024:
                    raise ValidationError(f"{angle} exceeds 10 MB")
                image = Image.open(io.BytesIO(data))
                image.verify()
                image = Image.open(io.BytesIO(data))
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValidationError(f"{angle} must be JPEG, PNG, or WebP")
                if image.width < 320 or image.height < 240:
                    raise ValidationError(f"{angle} must be at least 320×240")
                extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image.format]
                path = target / f"{uuid.uuid4().hex}{extension}"
                path.write_bytes(data)
                written.append(path)
                records.append(
                    {
                        "angle": angle,
                        "local_path": str(path),
                        "media_type": image.format,
                        "bytes": len(data),
                        "width": image.width,
                        "height": image.height,
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
            return records
        except Exception:
            for path in written:
                path.unlink(missing_ok=True)
            raise

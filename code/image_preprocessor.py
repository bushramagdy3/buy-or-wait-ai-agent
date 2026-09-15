"""Preprocess image files so their extensions match their byte signatures."""

import shutil
import sys
from pathlib import Path


def preprocess_images(media_dir=None, output_dir=None):
    """Copy images into preprocessed_images with extensions fixed by magic bytes."""
    if media_dir is None:
        media_path = Path(__file__).resolve().parent.parent / "dataset" / "media"
    else:
        media_path = Path(media_dir).expanduser().resolve()

    if output_dir is None:
        output_path = media_path / "preprocessed_images"
    else:
        output_path = Path(output_dir).expanduser().resolve()

    if not media_path.is_dir():
        print(f"Media path is not valid: {media_path}")
        sys.exit(1)

    if output_path == media_path:
        print(f"Output path cannot be the media path: {output_path}")
        sys.exit(1)

    output_path.mkdir(parents=True, exist_ok=True)

    image_signatures = {
        ".png": [b"\x89PNG\r\n\x1a\n"],
        ".jpg": [b"\xff\xd8\xff"],
        ".jpeg": [b"\xff\xd8\xff"],
        ".gif": [b"GIF87a", b"GIF89a"],
        ".bmp": [b"BM"],
        ".tif": [b"II*\x00", b"MM\x00*"],
        ".tiff": [b"II*\x00", b"MM\x00*"],
    }

    preferred_extensions = {
        ".jpeg": ".jpg",
        ".tiff": ".tif",
    }

    processed_files = {}

    for image_path in sorted(media_path.rglob("*")):
        if not image_path.is_file():
            continue
        if output_path in image_path.parents:
            continue

        try:
            with image_path.open("rb") as image_file:
                header = image_file.read(16)
        except OSError as error:
            print(f"Could not read {image_path.name}: {error}")
            sys.exit(1)

        actual_extension = None
        for extension, signatures in image_signatures.items():
            if any(header.startswith(signature) for signature in signatures):
                actual_extension = preferred_extensions.get(extension, extension)
                break

        # WEBP files start with RIFF but must also contain WEBP in bytes 8-11.
        if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            actual_extension = ".webp"

        if actual_extension is None:
            print(f"Unknown image byte signature: {image_path.name}")
            sys.exit(1)

        current_extension = image_path.suffix.lower()
        if current_extension in (".jpeg", ".jpg") and actual_extension == ".jpg":
            output_extension = current_extension
        elif current_extension in (".tif", ".tiff") and actual_extension == ".tif":
            output_extension = current_extension
        elif current_extension == actual_extension:
            output_extension = current_extension
        else:
            output_extension = actual_extension

        output_file = output_path / f"{image_path.stem}{output_extension}"
        shutil.copy2(image_path, output_file)
        processed_files[str(image_path)] = str(output_file)

    print(f"Preprocessed {len(processed_files)} images into {output_path}")
    return processed_files


if __name__ == "__main__":
    preprocess_images()

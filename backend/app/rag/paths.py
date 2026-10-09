"""Folder-upload paths are archive metadata, never server destination paths."""

import hashlib

from app.rag.schemas import ArchiveLocation


def normalize_relative_path(value: str) -> str:
    value = value.replace("\\", "/")
    parts = value.split("/")
    if (
        len(value) > 2048
        or any(part in {"", ".", ".."} or not part.strip() for part in parts)
        or any(ord(char) < 32 or char == ":" for char in value)
    ):
        raise ValueError("Upload paths must be relative, without empty or '..' segments.")
    return "/".join(parts)


def archive_location(relative_path: str, section: str, folder: str) -> ArchiveLocation:
    parts = normalize_relative_path(relative_path).split("/")
    if len(parts) == 1:
        return ArchiveLocation(section=section, folder=folder)
    root = parts[0]
    parents = parts[1:-1] if section in {"Unsorted", root} else parts[:-1]
    prefix = [] if folder == "General" else [folder]
    return ArchiveLocation(
        section=root if section == "Unsorted" else section,
        folder="/".join(prefix + parents) or "General",
    )


def file_source(relative_path: str) -> str:
    """Same-named files in different folders must not share trust by accident."""
    if len(relative_path) <= 255:
        return relative_path
    digest = hashlib.sha256(relative_path.encode()).hexdigest()[:24]
    return f"{relative_path[:230]}:{digest}"

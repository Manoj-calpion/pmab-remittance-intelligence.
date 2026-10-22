"""Safe expansion of uploaded ZIP archives.

Only remittance text members are returned for parsing. Unsafe paths, oversized
members, and unsupported names are rejected explicitly and are not extracted
onto disk.
"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from app.integrations.connectors import ALLOWED_SUFFIXES

MAX_ARCHIVE_MEMBERS = 40


class ArchiveError(Exception):
    pass


@dataclass
class ArchiveMember:
    filename: str
    content: bytes | None
    rejected_reason: str | None = None


def expand_upload(filename: str, content: bytes, *, max_member_bytes: int, max_total_bytes: int) -> list[ArchiveMember]:
    suffix = Path(filename).suffix.lower()
    if suffix != ".zip":
        return [ArchiveMember(filename=Path(filename).name or "upload.835", content=content)]
    try:
        archive = ZipFile(BytesIO(content))
    except BadZipFile as exc:
        raise ArchiveError("The ZIP archive could not be read.") from exc
    members: list[ArchiveMember] = []
    total = 0
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir() and not _ignored(info.filename)]
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            raise ArchiveError(f"The archive has more than {MAX_ARCHIVE_MEMBERS} files.")
        if not infos:
            raise ArchiveError("The archive does not contain any files.")
        for info in infos:
            _reject_unsafe_path(info.filename)
            name = Path(info.filename).name
            if info.flag_bits & 0x1:
                raise ArchiveError("Encrypted ZIP members are not accepted.")
            if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
                members.append(
                    ArchiveMember(
                        filename=name,
                        content=None,
                        rejected_reason="Unsupported file type inside the archive. It was not parsed.",
                    )
                )
                continue
            if info.file_size > max_member_bytes:
                raise ArchiveError(f"{name} exceeds the upload size limit.")
            total += info.file_size
            if total > max_total_bytes:
                raise ArchiveError("The uncompressed archive exceeds the configured size limit.")
            payload = archive.read(info)
            if len(payload) > max_member_bytes:
                raise ArchiveError(f"{name} exceeds the upload size limit.")
            members.append(ArchiveMember(filename=name, content=payload))
    if not members:
        raise ArchiveError("The archive does not contain any remittance files.")
    return members


def _ignored(name: str) -> bool:
    parts = Path(name).parts
    return any(part in {"__MACOSX", ".DS_Store"} or part.startswith("._") for part in parts)


def _reject_unsafe_path(name: str) -> None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or name.startswith(("/", "\\")):
        raise ArchiveError("The archive contains an unsafe path and was not extracted.")

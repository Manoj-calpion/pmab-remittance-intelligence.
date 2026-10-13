"""Read-only remittance source connectors.

The Central Reach API connector refuses every call. Approved endpoint
documentation was not provided, so no URLs are guessed.
"""

from dataclasses import dataclass
from pathlib import Path


class ConnectorError(Exception):
    pass


class IntegrationDisabledError(ConnectorError):
    pass


@dataclass
class EraMetadata:
    source_system: str
    source_record_id: str
    filename: str
    watermark: str
    content: bytes
    read_only: bool = True


ALLOWED_SUFFIXES = {".835", ".edi", ".txt", ".x12"}


class LocalFileConnector:
    source_system = "local_file"

    def __init__(self, root: Path) -> None:
        self.root = root

    def list_records(self, known_ids: set[str] | None = None) -> list[EraMetadata]:
        if not self.root.exists():
            raise ConnectorError(f"Ingestion directory does not exist: {self.root}")
        known = known_ids or set()
        records: list[EraMetadata] = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            record_id = path.name
            if record_id in known:
                continue
            records.append(
                EraMetadata(
                    source_system=self.source_system,
                    source_record_id=record_id,
                    filename=path.name,
                    watermark=path.name,
                    content=path.read_bytes(),
                )
            )
        return records


class MockCentralReachConnector:
    """Synthetic stand-in used only when demo mode explicitly selects it.

    It reads local fixture files. It never opens a network connection and it
    cannot modify a source system.
    """

    source_system = "mock_central_reach"

    def __init__(self, root: Path) -> None:
        self._files = LocalFileConnector(root)

    def list_records(self, known_ids: set[str] | None = None) -> list[EraMetadata]:
        records = self._files.list_records(known_ids)
        for record in records:
            record.source_system = self.source_system
        return records


class CentralReachAPIConnector:
    source_system = "central_reach_api"

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def list_records(self, known_ids: set[str] | None = None) -> list[EraMetadata]:
        del known_ids
        if not self.enabled:
            raise IntegrationDisabledError(
                "Central Reach API connector is disabled until approved integration documentation and credentials are available."
            )
        raise IntegrationDisabledError(
            "Central Reach API was marked enabled, but no approved endpoint specification is present in this build. The call was refused."
        )

    def download(self, record_id: str) -> bytes:
        del record_id
        self.list_records()
        raise IntegrationDisabledError("Central Reach downloads are not implemented.")


class SFTPConnector:
    """Optional read-only SFTP client. Disabled unless every setting is present."""

    source_system = "sftp"

    def __init__(self, *, enabled: bool, host: str, port: int, username: str, remote_dir: str, private_key_path: str) -> None:
        self.enabled = enabled
        self.host = host
        self.port = port
        self.username = username
        self.remote_dir = remote_dir
        self.private_key_path = private_key_path

    def list_records(self, known_ids: set[str] | None = None) -> list[EraMetadata]:
        del known_ids
        if not self.enabled:
            raise IntegrationDisabledError("SFTP connector is disabled. Central Reach SFTP access has not been confirmed.")
        missing = [
            name
            for name, value in (
                ("SFTP_HOST", self.host),
                ("SFTP_USERNAME", self.username),
                ("SFTP_REMOTE_DIR", self.remote_dir),
                ("SFTP_PRIVATE_KEY_PATH", self.private_key_path),
            )
            if not value
        ]
        if missing:
            raise IntegrationDisabledError("SFTP connector is incomplete: " + ", ".join(missing))
        try:
            import paramiko
        except ImportError as exc:
            raise IntegrationDisabledError(
                "SFTP settings are present, but the paramiko package is not installed. No connection was attempted."
            ) from exc
        records: list[EraMetadata] = []
        transport = paramiko.Transport((self.host, self.port))
        try:
            key = paramiko.RSAKey.from_private_key_file(self.private_key_path)
            transport.connect(username=self.username, pkey=key)
            sftp = paramiko.SFTPClient.from_transport(transport)
            if sftp is None:
                raise ConnectorError("SFTP session could not be opened")
            try:
                for entry in sorted(sftp.listdir_attr(self.remote_dir), key=lambda item: item.filename):
                    filename = entry.filename
                    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
                        continue
                    remote_path = f"{self.remote_dir.rstrip('/')}/{filename}"
                    with sftp.open(remote_path, "rb") as handle:
                        content = handle.read()
                    records.append(
                        EraMetadata(
                            source_system=self.source_system,
                            source_record_id=filename,
                            filename=filename,
                            watermark=filename,
                            content=content,
                        )
                    )
            finally:
                sftp.close()
        finally:
            transport.close()
        return records

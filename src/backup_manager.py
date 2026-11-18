import subprocess
from datetime import datetime
from pathlib import Path


# PostgreSQL 18 installation
PG_BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")
PG_DUMP = PG_BIN / "pg_dump.exe"
PG_RESTORE = PG_BIN / "pg_restore.exe"

# Keep these settings consistent with database.py
DB_NAME = "Football-Model1.0"
DB_USER = "postgres"
DB_HOST = "localhost"
DB_PORT = "5432"

# Store backups outside the project
BACKUP_FOLDER = Path.home() / "FootballIntelligenceBackups"

# Keep the three newest verified backups
MAX_BACKUPS = 3


def create_backup():
    temporary_file = None

    try:
        # Verify PostgreSQL tools exist
        if not PG_DUMP.exists():
            return False, f"pg_dump was not found:\n{PG_DUMP}"

        if not PG_RESTORE.exists():
            return False, f"pg_restore was not found:\n{PG_RESTORE}"

        BACKUP_FOLDER.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        final_file = (
            BACKUP_FOLDER
            / f"football_intelligence_{timestamp}.dump"
        )

        temporary_file = (
            BACKUP_FOLDER
            / f"football_intelligence_{timestamp}.tmp"
        )

        # Create PostgreSQL backup
        dump_command = [
            str(PG_DUMP),
            "-h", DB_HOST,
            "-p", DB_PORT,
            "-U", DB_USER,
            "-d", DB_NAME,
            "-F", "c",
            "-f", str(temporary_file),
            "-w",
        ]

        dump_result = subprocess.run(
            dump_command,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if dump_result.returncode != 0:
            raise RuntimeError(
                dump_result.stderr or "pg_dump failed."
            )

        if not temporary_file.exists() or temporary_file.stat().st_size == 0:
            raise RuntimeError("The backup file is missing or empty.")

        # Verify that PostgreSQL can read the archive
        verify_command = [
            str(PG_RESTORE),
            "--list",
            str(temporary_file),
        ]

        verify_result = subprocess.run(
            verify_command,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if verify_result.returncode != 0:
            raise RuntimeError(
                verify_result.stderr or "Backup verification failed."
            )

        # Only promote the backup after successful verification
        temporary_file.replace(final_file)

        # Rotate older backups, preserving the three newest
        backups = sorted(
            BACKUP_FOLDER.glob("football_intelligence_*.dump"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        cleanup_warnings = []

        for old_backup in backups[MAX_BACKUPS:]:
            try:
                old_backup.unlink()
            except OSError as error:
                cleanup_warnings.append(str(error))

        message = f"Verified backup created:\n{final_file}"

        if cleanup_warnings:
            message += (
                "\n\nSome older backups could not be deleted:\n"
                + "\n".join(cleanup_warnings)
            )

        return True, message

    except Exception as error:
        if temporary_file is not None:
            try:
                temporary_file.unlink(missing_ok=True)
            except OSError:
                pass

        return False, f"Backup failed:\n{error}"
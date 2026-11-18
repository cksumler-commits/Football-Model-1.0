import json
from pathlib import Path

SESSION_FILE = Path.home() / ".football_model_session.json"


def save_session(user):
    session = {
        "id": user["id"],
        "username": user["username"],
        "organization_id": user["organization_id"],
    }

    SESSION_FILE.write_text(
        json.dumps(session),
        encoding="utf-8",
    )


def load_session():
    if not SESSION_FILE.exists():
        return None

    try:
        session = json.loads(
            SESSION_FILE.read_text(encoding="utf-8")
        )

        required = {"id", "username", "organization_id"}
        if not required.issubset(session):
            clear_session()
            return None

        return session

    except (OSError, json.JSONDecodeError, TypeError):
        clear_session()
        return None


def clear_session():
    try:
        SESSION_FILE.unlink(missing_ok=True)
    except OSError:
        pass
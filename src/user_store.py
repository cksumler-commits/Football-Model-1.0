try:
    from .auth import hash_password, verify_password
    from .database import get_connection
except ImportError:
    from auth import hash_password, verify_password
    from database import get_connection


def create_user(username, password):
    username = username.strip()

    if not username:
        raise ValueError("Username cannot be empty.")

    if len(username) > 50:
        raise ValueError("Username cannot exceed 50 characters.")

    if not password or len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")

    password_hash = hash_password(password)
    organization_name = f"{username}'s Private Organization"

    try:
        # All three inserts belong to one transaction.
        with get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Create the account.
                cur.execute(
                    """
                    INSERT INTO app_users (username, password_hash)
                    VALUES (%s, %s)
                    RETURNING id
                    """,
                    (username, password_hash),
                )
                user_id = cur.fetchone()[0]

                # 2. Create this user's private organization.
                cur.execute(
                    """
                    INSERT INTO organizations (name)
                    VALUES (%s)
                    RETURNING id
                    """,
                    (organization_name,),
                )
                organization_id = cur.fetchone()[0]

                # 3. Make the user the owner of that organization.
                cur.execute(
                    """
                    INSERT INTO organization_members
                        (organization_id, user_id, role)
                    VALUES (%s, %s, %s)
                    """,
                    (organization_id, user_id, "owner"),
                )

        return user_id

    except Exception as error:
        # PostgreSQL unique-constraint violation.
        if getattr(error, "sqlstate", None) == "23505":
            constraint = getattr(error, "diag", None)
            constraint_name = (
                getattr(constraint, "constraint_name", None)
                if constraint is not None
                else None
            )

            if constraint_name == "app_users_username_lower_unique":
                raise ValueError(
                    "That username already exists."
                ) from error

        raise


def authenticate_user(username, password):
    username = username.strip()

    if not username or not password:
        return None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    u.id,
                    u.username,
                    u.password_hash,
                    m.organization_id
                FROM app_users AS u
                JOIN organization_members AS m
                    ON m.user_id = u.id
                WHERE LOWER(u.username) = LOWER(%s)
                """,
                (username,),
            )
            user = cur.fetchone()

    if user is None:
        return None

    user_id, stored_username, stored_hash, organization_id = user

    if not verify_password(password, stored_hash):
        return None

    return {
        "id": user_id,
        "username": stored_username,
        "organization_id": organization_id,
    }
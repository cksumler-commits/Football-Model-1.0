from src.user_store import create_user, authenticate_user

username = input("Test username: ").strip()
password = input("Test password (12+ characters): ")

try:
    user_id = create_user(username, password)
    print("Account created. ID:", user_id)
except ValueError as error:
    print("Account creation failed:", error)
    raise SystemExit(1)

login = authenticate_user(username, password)
print("Correct login:", login is not None)

wrong_login = authenticate_user(username, "DefinitelyWrongPassword!")
print("Wrong password rejected:", wrong_login is None)

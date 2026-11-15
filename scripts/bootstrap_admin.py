"""Create the first administrator locally, before allowing public registration.

Run from the repository root: python scripts/bootstrap_admin.py --email <address>.
The password is read securely from the terminal, never a command-line argument.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import ValidationError

from src.application.membership.service import MembershipError, MembershipService
from src.common.config import get_settings
from src.data.database import get_session_factory
from src.data.repository.membership import MembershipRepository
from src.presentation.api.routers.membership import RegisterIn


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", default="Administrator")
    args = parser.parse_args()
    password = getpass.getpass("New administrator password (12+ characters, at most 72 bytes): ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords did not match.", file=sys.stderr)
        return 1
    try:
        body = RegisterIn(email=args.email, password=password, display_name=args.display_name)
    except ValidationError:
        print("Invalid email, display name or password length.", file=sys.stderr)
        return 1
    settings = get_settings()
    with get_session_factory(settings)() as session:
        try:
            result = MembershipService(MembershipRepository(session), settings).bootstrap_admin(
                str(body.email),
                body.password.get_secret_value(),
                body.display_name,
            )
        except MembershipError as exc:
            print(exc.message, file=sys.stderr)
            return 1
    print(f"Administrator created (id={result['id']}). No credentials were printed or saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

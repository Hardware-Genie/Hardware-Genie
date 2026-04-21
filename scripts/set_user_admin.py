import argparse
import sys
from pathlib import Path

from sqlalchemy import select

# python scripts/set_user_admin.py colin@gmail.com
# python scripts/set_user_admin.py colin@gmail.com --clear

def _add_src_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / 'src'
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Set or clear a user admin flag by email.'
    )
    parser.add_argument('email', help='User email address')
    parser.add_argument(
        '--clear',
        action='store_true',
        help='Clear admin flag instead of setting it',
    )
    args = parser.parse_args()

    _add_src_to_path()

    from app import app, db
    from app.models import User

    target_email = (args.email or '').strip().lower()
    if not target_email:
        print('Email is required.')
        return 1

    with app.app_context():
        user = db.session.execute(
            select(User).where(User.email == target_email)
        ).scalar_one_or_none()

        if user is None:
            print(f'User not found: {target_email}')
            return 1

        user.is_admin = not args.clear
        db.session.commit()

        status = 'admin enabled' if user.is_admin else 'admin cleared'
        print(f'{status} for {target_email}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())

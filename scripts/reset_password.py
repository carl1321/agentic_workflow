#!/usr/bin/env python3
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Reset a user's password by username.
Usage: python scripts/reset_password.py <username> <new_password>
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.server.auth.db import UserDB
from src.server.auth.admin.users import UserAdminDB


def main():
    if len(sys.argv) != 3:
        print("Usage: python scripts/reset_password.py <username> <new_password>")
        sys.exit(1)
    username = sys.argv[1]
    new_password = sys.argv[2]

    user = UserDB.get_by_username(username)
    if not user:
        print(f"User not found: {username}")
        sys.exit(1)

    user_id = user["id"]
    ok = UserAdminDB.change_password(user_id, new_password)
    if ok:
        print(f"Password for user '{username}' has been reset successfully.")
    else:
        print("Failed to update password.")
        sys.exit(1)


if __name__ == "__main__":
    main()

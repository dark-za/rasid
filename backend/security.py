"""تشفير وفك تشفير الأسرار باستخدام Fernet (مفتاح تشفير متماثل).

الاستخدام:
    python -m security genkey                       # توليد مفتاح تشفير جديد
    python -m security encrypt "النص_ال sensitif"    # تشفير نص (يتطلب المفتاح)
    python -m security decrypt "gAAAAA..."           # فك تشفير

المفتاح يُمرَّر عبر متغيّر البيئة RASID_SECRETS_KEY أو عبر --key.
"""
import argparse
import os
import sys

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

load_dotenv()


def _resolve_key(cli_key: str | None = None) -> bytes:
    key = cli_key or os.getenv("RASID_SECRETS_KEY", "")
    if not key:
        print("خطأ: المفتاح غير متوفر. استخدم --key أو ضبط RASID_SECRETS_KEY", file=sys.stderr)
        raise SystemExit(2)
    return key.encode()


def generate_key() -> str:
    return Fernet.generate_key().decode()


def encrypt(secret: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(secret.encode()).decode()


def decrypt(token: str, key: str) -> str:
    try:
        return Fernet(key.encode()).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("تعذر فك التشفير: المفتاح غير صحيح أو البيانات تالفة") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="تشفير/فك تشفير الأسرار (Rasid)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("genkey", help="توليد مفتاح تشفير جديد")

    p_enc = sub.add_parser("encrypt", help="تشفير نص")
    p_enc.add_argument("secret")
    p_enc.add_argument("--key", default=None)

    p_dec = sub.add_parser("decrypt", help="فك تشفير نص")
    p_dec.add_argument("token")
    p_dec.add_argument("--key", default=None)

    args = parser.parse_args()

    if args.command == "genkey":
        print(generate_key())
    elif args.command == "encrypt":
        print(encrypt(args.secret, _resolve_key(args.key).decode()))
    elif args.command == "decrypt":
        try:
            print(decrypt(args.token, _resolve_key(args.key).decode()))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1)


if __name__ == "__main__":
    main()

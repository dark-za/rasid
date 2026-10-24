"""سكربت النسخ الاحتياطي لقاعدة بيانات راصد (SQLite).

يستخدم واجهة sqlite3.backup لأخذ نسخة متسقة دون إيقاف الخدمة،
مع التحقق من سلامة النسخة والاحتفاظ بآخر N نسخة.
"""
from __future__ import annotations

import argparse
import datetime
import os
from pathlib import Path
import sqlite3
import sys

# تحديد المسارات الافتراضية
BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_DB_FILE = Path(os.getenv("RASID_DB_FILE", str(BACKEND_DIR / "data" / "rasid.sqlite3")))
DEFAULT_BACKUP_DIR = Path(os.getenv("RASID_BACKUP_DIR", str(BACKEND_DIR / "backups")))
DEFAULT_RETENTION = int(os.getenv("RASID_BACKUP_RETENTION", "7"))


def create_backup(
    source_path: Path,
    backup_dir: Path,
    keep: int = DEFAULT_RETENTION,
) -> Path:
    """أخذ نسخة احتياطية من قاعدة SQLite والاحتفاظ بآخر N نسخة."""
    if not source_path.exists():
        raise FileNotFoundError(f"قاعدة البيانات المصدر غير موجودة: {source_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target_path = backup_dir / f"rasid_backup_{timestamp}.sqlite3"

    # النسخ الاحتياطي الحي والآمن عبر SQLite backup API
    with sqlite3.connect(str(source_path)) as src_conn:
        with sqlite3.connect(str(target_path)) as dst_conn:
            src_conn.backup(dst_conn)

    # التحقق من سلامة ملف النسخة الاحتياطية
    with sqlite3.connect(str(target_path)) as check_conn:
        cursor = check_conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()
        if not result or result[0] != "ok":
            if target_path.exists():
                target_path.unlink()
            raise RuntimeError(f"فشل التحقق من سلامة النسخة الاحتياطية: {result}")

    # تدوير النسخ القديمة والاحتفاظ بآخر keep نسخة
    prune_old_backups(backup_dir, keep=keep)

    return target_path


def prune_old_backups(backup_dir: Path, keep: int) -> list[Path]:
    """حذف النسخ الزائدة عن العدد المطلوب مع الإبقاء على الأحدث."""
    if keep <= 0:
        return []

    backups = sorted(
        backup_dir.glob("rasid_backup_*.sqlite3"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    deleted: list[Path] = []
    if len(backups) > keep:
        for old_backup in backups[keep:]:
            try:
                old_backup.unlink()
                deleted.append(old_backup)
            except OSError as err:
                print(f"[تحذير] تعذر حذف النسخة القديمة {old_backup.name}: {err}", file=sys.stderr)

    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="أداة النسخ الاحتياطي لقاعدة بيانات راصد")
    parser.add_argument(
        "--source",
        "-s",
        type=Path,
        default=DEFAULT_DB_FILE,
        help="مسار ملف قاعدة البيانات المصدر",
    )
    parser.add_argument(
        "--dest",
        "-d",
        type=Path,
        default=DEFAULT_BACKUP_DIR,
        help="مجلد حفظ النسخ الاحتياطية",
    )
    parser.add_argument(
        "--keep",
        "-k",
        type=int,
        default=DEFAULT_RETENTION,
        help="عدد أحدث النسخ التي يتم الاحتفاظ بها (افتراضياً 7)",
    )

    args = parser.parse_args()

    try:
        backup_file = create_backup(args.source, args.dest, keep=args.keep)
        print(f"تم إنشاء النسخة الاحتياطية بنجاح: {backup_file}")
        return 0
    except Exception as exc:
        print(f"خطأ أثناء النسخ الاحتياطي: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

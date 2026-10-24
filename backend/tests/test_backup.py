import sqlite3
from pathlib import Path
import pytest
from backup import create_backup, prune_old_backups


def test_backup_creates_valid_copy(tmp_path: Path):
    source_db = tmp_path / "test.sqlite3"
    with sqlite3.connect(str(source_db)) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO users (name) VALUES ('Alice'), ('Bob');")
        conn.commit()

    backup_dir = tmp_path / "backups"
    backup_file = create_backup(source_db, backup_dir, keep=3)

    assert backup_file.exists()
    assert backup_file.name.startswith("rasid_backup_")

    with sqlite3.connect(str(backup_file)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM users ORDER BY id;")
        rows = cursor.fetchall()
        assert rows == [("Alice",), ("Bob",)]


def test_backup_rotation_pruning(tmp_path: Path):
    source_db = tmp_path / "test.sqlite3"
    with sqlite3.connect(str(source_db)) as conn:
        conn.execute("CREATE TABLE t (x INT);")
        conn.commit()

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # إنشاء ملفات وهمية قديمة
    for i in range(10):
        fake_backup = backup_dir / f"rasid_backup_2026010{i}_000000.sqlite3"
        fake_backup.write_text("test")

    pruned = prune_old_backups(backup_dir, keep=5)
    remaining = list(backup_dir.glob("rasid_backup_*.sqlite3"))
    assert len(remaining) == 5
    assert len(pruned) == 5


def test_backup_fails_if_source_not_found(tmp_path: Path):
    missing_db = tmp_path / "missing.sqlite3"
    backup_dir = tmp_path / "backups"

    with pytest.raises(FileNotFoundError):
        create_backup(missing_db, backup_dir)

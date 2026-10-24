import sys
from pathlib import Path

# ضمان إمكانية استيراد وحدات الباكند (config, timeutils, ...) عند تشغيل pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

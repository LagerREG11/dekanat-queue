"""Өндірістік сервер (хостинг) үшін кіру нүктесі.

PythonAnywhere: Web қойындысындағы WSGI файлынан осы модуль импортталады
                (docs/06_хостинг.md қараңыз).
Windows:        waitress-serve --listen=0.0.0.0:8000 wsgi:app
Linux:          gunicorn -w 1 -b 0.0.0.0:8000 wsgi:app   (SQLite болғандықтан бір процесс)
"""
import os
import time

# Хостинг серверлері әдетте UTC уақытымен жұмыс істейді. Деканаттың жұмыс кестесі
# дұрыс есептелуі үшін Қызылорда уақыт белдеуін орнатамыз (UTC+5).
os.environ.setdefault("TZ", "Asia/Qyzylorda")
if hasattr(time, "tzset"):
    time.tzset()

from app.web import create_app  # noqa: E402  (TZ импорттан бұрын орнатылуы керек)

app = create_app()

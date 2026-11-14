"""Өндірістік сервер (хостинг) үшін кіру нүктесі.

PythonAnywhere: Web қойындысындағы WSGI файлынан осы модуль импортталады
                (docs/06_хостинг.md қараңыз).
Windows:        waitress-serve --listen=0.0.0.0:8000 wsgi:app
Linux:          gunicorn -w 1 -b 0.0.0.0:8000 wsgi:app   (SQLite болғандықтан бір процесс)

Уақыт белдеуі app/web.py ішінде zoneinfo арқылы қолданылады (APP_TIMEZONE,
әдепкі Asia/Qyzylorda), сондықтан сервер UTC-пен жұмыс істесе де кесте дұрыс.
"""
from app.web import create_app

app = create_app()

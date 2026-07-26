@echo off
echo ============================================
echo  PPE Management System - PostgreSQL
echo ============================================

pip install flask psycopg2-binary openpyxl python-dotenv alembic sqlalchemy --quiet

echo Starting...
echo Open browser: http://localhost:5001
echo First time: python init_database.py  (alembic upgrade head)
echo ============================================

python app.py
pause
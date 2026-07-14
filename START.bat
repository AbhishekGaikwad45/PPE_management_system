@echo off
echo ============================================
echo  PPE Management System - PostgreSQL
echo ============================================

pip install flask psycopg2-binary openpyxl python-dotenv --quiet

echo Starting...
echo Open browser: http://localhost:5001
echo First time: python manage_users.py
echo ============================================

python app.py
pause
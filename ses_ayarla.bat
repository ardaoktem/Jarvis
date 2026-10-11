@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === ElevenLabs icin uygun ses araniyor ve test ediliyor ===
if exist venv\Scripts\python.exe (venv\Scripts\python.exe eleven_ses_sec.py) else (py eleven_ses_sec.py)
echo.
echo Sonuc ses_test_sonuc.txt dosyasinda. Jarvis aciksa yeniden baslat.
pause

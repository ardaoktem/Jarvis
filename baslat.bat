@echo off
cd /d "%~dp0"
if not exist venv\Scripts\python.exe goto nosetup
venv\Scripts\python.exe jarvis_gui.py
if errorlevel 1 goto fail
exit /b 0
:nosetup
echo Once kurulum.bat dosyasini calistirmalisin.
pause
exit /b 1
:fail
echo.
echo JARVIS hata ile kapandi. Yukaridaki hata mesajini bana gonder.
pause
exit /b 1

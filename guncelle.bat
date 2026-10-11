@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === JARVIS guncelleme: yeni kutuphaneler kuruluyor ===
if not exist venv\Scripts\python.exe (
    echo venv yok, once kurulum.bat calistirilacak...
    call kurulum.bat
    exit /b
)
venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo HATA: Kutuphaneler kurulamadi. Yukaridaki kirmizi mesaji bana gonder.
    pause
    exit /b 1
)
echo.
echo Kutuphaneler tamam. Jarvis aciksa tepsideki simgeye sag tikla - Cikis, sonra baslat.bat ile yeniden ac.
echo Exe kullaniyorsan simdi build_exe.bat calistir (ayarlarin ve anahtarlarin korunur).
pause

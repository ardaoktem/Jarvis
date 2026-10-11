@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "MOD=%~1"
echo === JARVIS kurulum ===
echo Klasor: %CD%
if exist venv\Scripts\python.exe goto havevenv

rem --- Uygun Python bul (3.10 - 3.13). 3.14 ve uzeri bazi kutuphanelerde henuz desteklenmiyor.
set "PYEXE="
set "PYARG="
for %%V in (3.12 3.13 3.11 3.10) do (
    if not defined PYEXE (
        py -%%V -c "import sys" >nul 2>&1 && (set "PYEXE=py" & set "PYARG=-%%V")
    )
)
if not defined PYEXE (
    python -c "import sys; assert (3,10) <= sys.version_info[:2] <= (3,13)" >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
    echo Uygun Python bulunamadi. Python 3.12 kuruluyor - winget ile, yonetici izni gerekmez...
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements
    set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if not exist "!PYEXE!" goto nopython
)
echo Python: !PYEXE! !PYARG!
"!PYEXE!" !PYARG! -m venv venv
if not exist venv\Scripts\python.exe goto nopython

:havevenv
echo.
echo Kutuphaneler kuruluyor - ilk seferde birkac dakika surer...
venv\Scripts\python.exe -m pip install --upgrade pip --disable-pip-version-check -q
venv\Scripts\python.exe -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto pipfail

where nvidia-smi >nul 2>&1
if not errorlevel 1 (
    echo NVIDIA ekran karti bulundu: GPU ses tanima kutuphaneleri kuruluyor - yaklasik 1 GB...
    venv\Scripts\python.exe -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 --disable-pip-version-check -q
)

if not exist .env (
    if exist .env.example (copy /y .env.example .env >nul) else (echo JARVIS_MODEL=gemini-3.8-flash> .env)
)

if /i "%MOD%"=="/test" goto smoke

rem --- Masaustu kisayolu
set "JV_DIR=%CD%"
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Jarvis.lnk')); $s.TargetPath=(Join-Path $env:JV_DIR 'venv\Scripts\pythonw.exe'); $s.Arguments='\"'+(Join-Path $env:JV_DIR 'jarvis_gui.py')+'\"'; $s.WorkingDirectory=$env:JV_DIR; $s.Description='JARVIS'; $s.Save()" >nul 2>&1

echo.
echo KURULUM TAMAM. Masaustundeki "Jarvis" kisayolu ile acabilirsin.
echo Ilk acilista ucretsiz Gemini anahtarini soracak: aistudio.google.com/apikey
if /i "%MOD%"=="/oto" (
    start "" "%CD%\venv\Scripts\pythonw.exe" "%CD%\jarvis_gui.py"
    timeout /t 5 >nul
    exit /b 0
)
pause
exit /b 0

:smoke
echo.
echo Kurulum testi: Jarvis acilip bilesenler deneniyor...
if exist smoke_sonuc.txt del smoke_sonuc.txt
venv\Scripts\python.exe jarvis_gui.py --smoke
echo.
if exist smoke_sonuc.txt (type smoke_sonuc.txt) else (echo HATA: Jarvis acilamadi. jarvis_hata.txt dosyasina bak. & if exist jarvis_hata.txt type jarvis_hata.txt)
pause
exit /b 0

:nopython
echo HATA: Python kurulamadi. python.org adresinden Python 3.12 indirip kur - kurulumda "Add Python to PATH" kutusunu isaretle - sonra bunu tekrar calistir.
pause
exit /b 1
:pipfail
echo HATA: Kutuphaneler kurulamadi. Internet baglantini kontrol et ve tekrar calistir. Yukaridaki kirmizi mesaji kaydet.
pause
exit /b 1

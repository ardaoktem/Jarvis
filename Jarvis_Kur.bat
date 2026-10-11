@echo off
chcp 65001 >nul
setlocal
rem ==================================================================================
rem  JARVIS tek dosyalik kurulum / guncelleme.
rem  Bu dosyayi indir ve cift tikla: Jarvis'i GitHub'dan indirir, Python yoksa kurar,
rem  kutuphaneleri kurar, masaustune kisayol koyar ve acar. Tekrar calistirirsan gunceller
rem  (API anahtarlarin ve ayarlarin korunur).
rem ==================================================================================
set "REPO=ardaoktem/Jarvis"
set "BRANCH=main"
set "HEDEF=%USERPROFILE%\Jarvis"
set "MOD=/oto"
set "ZIP=%TEMP%\jarvis_indir.zip"
set "TMPX=%TEMP%\jarvis_acilan"

echo === JARVIS kurulum ===
if exist "%~dp0Jarvis-main.zip" goto testmode
echo GitHub'dan indiriliyor: %REPO%
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri ('https://github.com/'+$env:REPO+'/archive/refs/heads/'+$env:BRANCH+'.zip') -OutFile $env:ZIP"
if errorlevel 1 goto dlfail
goto extract

:testmode
echo TEST MODU: yandaki Jarvis-main.zip kullaniliyor.
set "ZIP=%~dp0Jarvis-main.zip"
set "HEDEF=%~dp0Jarvis_test_kurulum"
set "MOD=/test"

:extract
if exist "%TMPX%" rmdir /s /q "%TMPX%"
powershell -NoProfile -Command "Expand-Archive -Force -LiteralPath $env:ZIP -DestinationPath $env:TMPX"
if errorlevel 1 goto dlfail
set "SRC="
for /d %%D in ("%TMPX%\*") do set "SRC=%%D"
if not defined SRC goto dlfail
if not exist "%HEDEF%" mkdir "%HEDEF%"
echo Dosyalar kopyalaniyor: %HEDEF%
robocopy "%SRC%" "%HEDEF%" /E /XF .env jarvis_settings.json usage.json /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto copyfail
rmdir /s /q "%TMPX%" >nul 2>&1
call "%HEDEF%\kurulum.bat" %MOD%
exit /b 0

:dlfail
echo HATA: Jarvis indirilemedi veya acilamadi. Internet baglantini kontrol et.
pause
exit /b 1
:copyfail
echo HATA: Dosyalar %HEDEF% klasorune kopyalanamadi. Jarvis aciksa kapatip tekrar dene.
pause
exit /b 1

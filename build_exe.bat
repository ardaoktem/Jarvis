@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === JARVIS exe olusturuluyor (birkac dakika surer) ===
if not exist venv\Scripts\python.exe (
    echo HATA: venv bulunamadi. Once kurulum.bat dosyasini calistir.
    pause
    exit /b 1
)
rem PyInstaller dist\Jarvis klasorunu silip bastan olusturur: ayar ve anahtar dosyalarini koru
set "KEEP=%TEMP%\jarvis_keep"
if exist "%KEEP%" rmdir /s /q "%KEEP%"
mkdir "%KEEP%"
for %%F in (.env jarvis_settings.json usage.json .spotify_cache) do (
    if exist "dist\Jarvis\%%F" copy /y "dist\Jarvis\%%F" "%KEEP%\%%F" >nul
)
venv\Scripts\python.exe -m pip install pyinstaller
venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name Jarvis ^
  --collect-all customtkinter ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all av ^
  --collect-all onnxruntime ^
  --collect-all tokenizers ^
  --collect-all edge_tts ^
  --collect-all google.genai ^
  --collect-all sounddevice ^
  --collect-all _sounddevice_data ^
  --collect-all pystray ^
  --collect-all uiautomation ^
  --hidden-import pystray._win32 ^
  --hidden-import clap_detector ^
  --hidden-import orb ^
  --hidden-import audio_hub ^
  --hidden-import screen_control ^
  --hidden-import comtypes ^
  jarvis_gui.py
echo.
if exist dist\Jarvis\Jarvis.exe (
    for %%F in (.env jarvis_settings.json usage.json .spotify_cache) do (
        if exist "%KEEP%\%%F" copy /y "%KEEP%\%%F" "dist\Jarvis\%%F" >nul
    )
    if not exist dist\Jarvis\.env if exist .env copy /y .env dist\Jarvis\.env >nul
    echo TAMAM: dist\Jarvis\Jarvis.exe olustu. Ayarlarin ve API anahtarlarin korundu.
    echo Windows ile baslatmak icin Jarvis acikken Ayarlar bolumunden "Windows ile baslat" anahtarini ac.
) else (
    echo HATA: exe olusmadi. Yukaridaki kirmizi hata mesajini bana gonder.
)
pause

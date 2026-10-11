@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === JARVIS: NVIDIA ekran karti ile ses tanima (istege bagli, yaklasik 1-2 GB indirir) ===
if not exist venv\Scripts\python.exe (
    echo Once kurulum.bat dosyasini calistir.
    pause
    exit /b 1
)
venv\Scripts\python.exe -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
echo.
echo Bitti. Jarvis'i yeniden baslat; Ayarlar - Mikrofon testi sonucunda "Ses tanima: GPU" yazmali.
pause

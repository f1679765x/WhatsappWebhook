@echo off
call %USERPROFILE%\miniconda3\Scripts\activate.bat whatsappwebhook
if errorlevel 1 (
    echo Failed to activate whatsappwebhook environment
    pause
    exit /b 1
)
uvicorn listener_app.main:app --host 0.0.0.0 --port 8000
pause

@echo off
cd /d C:\CodeProj\WhatsappWebhook
call %USERPROFILE%\miniconda3\Scripts\activate.bat whatsappwebhook
uvicorn app.main:app --host 0.0.0.0 --port 8000 >> C:\CodeProj\WhatsappWebhook\server.log 2>&1

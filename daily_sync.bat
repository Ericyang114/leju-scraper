@echo off
:: 每日自動同步腳本 - 由 Windows 工作排程器執行
:: 抓取 leju.com.tw 資料並推送到 yanghousetalk.onrender.com

set PUSH_API_KEY=7VdDj8fnWP203BrnjnnhCA
set RENDER_URL=https://leju-scraper.onrender.com
set PYTHON=C:\Users\fr367\AppData\Local\Programs\Python\Python312\python.exe

cd /d "D:\claude code\leju_scraper"
%PYTHON% push_to_render.py

echo.
echo 同步完成！

@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo        智能日报 - 采集并推送
echo ========================================
echo.

.venv\Scripts\python.exe -m daily_report run --team t1 --force --print --db my.db

echo.
echo ========================================
echo 推送完成。请查看上方的 sent 字段：
echo   email: 1      表示邮件已发出
echo   feishu_bot: 1 表示飞书已推送
echo ========================================
pause

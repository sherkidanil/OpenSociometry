@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py -3 app.py & goto :end)
where python >nul 2>nul && (python app.py & goto :end)
echo Python не найден. Установите Python 3 с сайта https://www.python.org/downloads/
echo При установке отметьте галочку "Add Python to PATH".
:end
pause

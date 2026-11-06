@echo off
setlocal
echo 启动脚本：%~f0
chcp 65001 >nul
for %%I in ("%~dp0.") do set "APP_HOME=%%~fI"
cd /d "%APP_HOME%"
set "READNEWBOOK_HOME=%APP_HOME%"
set "TEMP=%APP_HOME%\runtime\temp"
set "TMP=%TEMP%"
set "TMPDIR=%TEMP%"
set "PIP_CACHE_DIR=%APP_HOME%\runtime\cache\pip"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONNOUSERSITE=1"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%APP_HOME%\runtime\logs" mkdir "%APP_HOME%\runtime\logs"
set "READNEWBOOK_PYTHON=%APP_HOME%\runtime\python\python.exe"
if exist "%READNEWBOOK_PYTHON%" goto run_app
where py >nul 2>nul
if errorlevel 1 goto check_python
set "READNEWBOOK_PYTHON="
py -3.12 --version >nul 2>nul
if not errorlevel 1 set "READNEWBOOK_PYTHON=py -3.12"
if not defined READNEWBOOK_PYTHON (py -3.11 --version >nul 2>nul)
if not defined READNEWBOOK_PYTHON if not errorlevel 1 set "READNEWBOOK_PYTHON=py -3.11"
if defined READNEWBOOK_PYTHON goto run_system_python
:check_python
where python >nul 2>nul
if errorlevel 1 goto missing_python
python -c "import sys; raise SystemExit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)" >nul 2>nul
if errorlevel 1 goto missing_python
set "READNEWBOOK_PYTHON=python"
goto run_system_python
:run_app
"%READNEWBOOK_PYTHON%" -I -B -S -X utf8 "%APP_HOME%\launch_reading_desk.py"
goto app_ended
:run_system_python
%READNEWBOOK_PYTHON% -I -B -S -X utf8 "%APP_HOME%\launch_reading_desk.py"
goto app_ended
:app_ended
echo.
echo 工作台进程已退出。日志保存在：%APP_HOME%\runtime\logs\reading-desk.log
pause
goto done
:missing_python
echo 未找到程序自带的 Python，也未检测到 Python 3.11 或 3.12。
echo 请恢复便携包中的 runtime\python 文件夹，或从 https://www.python.org/downloads/windows/ 安装 Python 3.11/3.12 后再启动。
pause
:done
endlocal

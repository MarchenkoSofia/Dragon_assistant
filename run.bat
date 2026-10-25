@echo off
chcp 65001 > nul
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" goto CHECK

:CREATE
echo Виртуальное окружение не найдено. Создание...
if exist ".venv" rmdir /s /q .venv

py -3.12 -m venv .venv
if not exist ".venv\Scripts\activate.bat" (
    echo Ошибка: Python 3.12 не найден. Установите Python 3.12 с python.org и запустите снова.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 (
    echo Ошибка: не удалось обновить pip. Проверьте интернет.
    pause
    exit /b 1
)

echo Установка зависимостей PyQt5, PyAudio, SpeechRecognition, pywin32...
pip install -r requirements.txt
if errorlevel 1 (
    echo Ошибка: не удалось установить зависимости. Проверьте интернет и запустите run.bat снова.
    pause
    exit /b 1
)
goto RUN

:CHECK
rem Если окружение создано на другой версии Python (или сломано) - пересоздаём на 3.12.
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>&1
if %errorlevel%==0 goto RUN
echo Найденное окружение не на Python 3.12 - пересоздаю .venv...
rmdir /s /q .venv
goto CREATE

:RUN
call .venv\Scripts\activate.bat
echo Запуск дракончика. Если запросит права администратора - согласитесь,
echo программа сама перезапустится повышенными привилегиями.
python main.py %*
set EXITCODE=%errorlevel%
if not "%EXITCODE%"=="0" echo Работа завершилась с кодом %EXITCODE%.
pause
exit /b %EXITCODE%

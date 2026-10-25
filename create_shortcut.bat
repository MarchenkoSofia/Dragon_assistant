@echo off
chcp 65001 > nul
set "PROJECT_DIR=%~dp0"
set "PYTHONW=C:\Users\Sofia\AppData\Local\Programs\Python\Python312\pythonw.exe"
set "MAIN_PY=%PROJECT_DIR%main.py"
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Дракон Игнис.lnk"

echo Устанавливаем зависимости из requirements.txt...
"C:\Users\Sofia\AppData\Local\Programs\Python\Python312\python.exe" -m pip install -r "%PROJECT_DIR%requirements.txt"

echo Создаем ярлык на Рабочем столе...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = '%PYTHONW%'; $s.Arguments = '\"%MAIN_PY%\"'; $s.WorkingDirectory = '%PROJECT_DIR%'; $s.IconLocation = 'shell32.dll,43'; $s.Save()"

echo Готово! Ярлык «Дракон Игнис» создан на Рабочем столе.
pause
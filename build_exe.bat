@echo off
REM כל הזכויות שמורות לנתאי שנדורפי (c) 2026
chcp 65001 >nul
cd /d "%~dp0"
python -c "import PyInstaller, PIL, numpy" >nul 2>nul
if errorlevel 1 (
  echo מתקין את הכלים הדרושים לבניית ה-EXE...
  python -m pip install --disable-pip-version-check pyinstaller pillow numpy
  if errorlevel 1 (
    echo ההתקנה נכשלה. בדוק חיבור לאינטרנט ושפייתון מותקן.
    pause
    exit /b
  )
) else (
  echo הכלים הדרושים כבר מותקנים, ממשיך בלי חיבור לאינטרנט.
)
echo.
echo בונה את PhotoTools.exe (זה לוקח כדקה)...
set ICONARG=
if exist "assets\logo.ico" set ICONARG=--icon "assets\logo.ico"
set DATAARG=
if exist "providers.json" set DATAARG=--add-data "providers.json;."
set LANGARG=
if exist "lang\en.json" (set LANGARG=--add-data "lang;lang") else if exist "en.json" set LANGARG=--add-data "en.json;lang"
if exist "THIRD_PARTY_NOTICES.txt" set DATAARG=%DATAARG% --add-data "THIRD_PARTY_NOTICES.txt;."
if exist "photo_tools_guide.html" set DATAARG=%DATAARG% --add-data "photo_tools_guide.html;."
python -m PyInstaller --noconfirm --clean --onefile --windowed %ICONARG% %DATAARG% %LANGARG% --name PhotoTools photo_tools_gui.py
if errorlevel 1 (
  echo הבנייה נכשלה. שלח את ההודעות שמעל.
  pause
  exit /b
)
echo.
echo הסתיים. הקובץ נמצא כאן:  %~dp0dist\PhotoTools.exe
echo אם Windows חוסם אותו, השתמש ב-start_gui.bat במקום.
pause
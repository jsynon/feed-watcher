@echo off
setlocal
set "REPORT=%~dp0rejected_articles.csv"

if not exist "%REPORT%" (
    echo No rejected articles have been recorded yet.
    echo The report will be created after the watcher finds a newly rejected article.
    pause
    exit /b 0
)

start "" "%REPORT%"
endlocal

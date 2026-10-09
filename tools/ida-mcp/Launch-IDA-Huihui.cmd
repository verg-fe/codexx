@echo off
setlocal
set "IDA_HOME=G:\IDA Pro v7.6.210427"
set "PATH=%IDA_HOME%\python38;%PATH%"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONSTARTUP="
set "PYTHONUSERBASE="
set "PYTHONNOUSERSITE=1"
set "IDAUSR=G:\LocalCodex\ida-user"
set "TEMP=G:\LocalCodex\ida-jobs\tmp"
set "TMP=%TEMP%"
set "QT_OPENGL=software"
set "QT_QUICK_BACKEND=software"
start "" /D "G:\LocalCodex\ida-jobs" "%IDA_HOME%\ida64.exe" %*
endlocal

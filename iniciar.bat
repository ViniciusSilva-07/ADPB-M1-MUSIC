@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo Instalando o ADPB M1 MUSIC pela primeira vez...
  python -m venv .venv
  if errorlevel 1 (
    echo Python nao encontrado. Instale o Python 3.10+ em python.org e marque "Add Python to PATH".
    pause
    exit /b 1
  )
  .venv\Scripts\python -m pip install -U pip -q
  .venv\Scripts\pip install -r requirements.txt -q
  where deno >nul 2>&1 || winget install -e --id DenoLand.Deno --accept-source-agreements --accept-package-agreements
)
rem Git e necessario para o aviso automatico de atualizacoes (opcional)
where git >nul 2>&1 || if not exist "%ProgramFiles%\Git\cmd\git.exe" winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop');Remove-Item ($d+'\SoundHarbor.lnk'),($d+'\Cais.lnk') -ErrorAction SilentlyContinue;$s=(New-Object -COM WScript.Shell).CreateShortcut($d+'\ADPB M1 MUSIC.lnk');$s.TargetPath='%~dp0.venv\Scripts\pythonw.exe';$s.Arguments='app.py';$s.WorkingDirectory='%~dp0';$s.IconLocation='%~dp0icone.ico';$s.Save()"
start "" .venv\Scripts\pythonw.exe app.py

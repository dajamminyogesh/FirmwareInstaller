@REM rem call "%USERPROFILE%\.virtualenvs\FirmwareInstaller\Scripts\activate.bat"

DEL /F /A /Q Package\build
RD /S /Q Package\build
DEL /F /A /Q Package\dist
RD /S /Q Package\dist

call "C:\Users\User\Desktop\FirmwareInstaller\FirmwareInstaller\venv\Scripts\activate.bat"
@pyinstaller --workpath Package/build --distpath Package/dist -y Installer.spec
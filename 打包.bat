call "%USERPROFILE%\.virtualenvs\FirmwareInstaller\Scripts\activate.bat"
@pyinstaller --workpath Package/build --distpath Package/dist -y Installer.spec
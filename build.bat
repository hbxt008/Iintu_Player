@echo off
nuitka --assume-yes-for-downloads --standalone --windows-console-mode=disable --windows-icon-from-ico=huamao.ico --include-data-files=huamao.ico=huamao.ico --include-package-data=pypinyin --include-package=pythonosc --enable-plugin=pyqt6 --include-qt-plugins=multimedia Intu_Player.py
echo 打包完成！
pause
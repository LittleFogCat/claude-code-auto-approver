@echo off
rem observer_gui.bat - fallback launcher. For the truly silent
rem experience (no console flash at all), double-click observer_gui.vbs
rem instead. This .bat is kept for users who prefer .bat files but
rem it will briefly flash a console window -- use the .vbs for zero
rem black-box experience.

wscript.exe //nologo "%~dp0observer_gui.vbs"
@echo off
call "vendor_sdk\Vitis\bin\xsdb.bat" "hardware_workspace\gpt_softpack_launch02\board_once01\run.tcl"
exit /b %ERRORLEVEL%

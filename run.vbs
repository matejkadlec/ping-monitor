' Truly hidden launcher for Ping Monitor
' This script launches the ping monitor with no visible windows at all

' Get the script directory
Set objFSO = CreateObject("Scripting.FileSystemObject")
strScriptPath = objFSO.GetParentFolderName(WScript.ScriptFullName)

' Set the working directory
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = strScriptPath

' Run the Python script with pythonw.exe (no window)
pythonwPath = strScriptPath & "\venv\Scripts\pythonw.exe"
scriptPath = strScriptPath & "\main.py"

' Execute with window hidden (0 = hidden)
objShell.Run """" & pythonwPath & """ """ & scriptPath & """", 0, False

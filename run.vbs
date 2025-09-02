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

' Run Ping Monitor invisibly (no command prompt window)
Set WshShell = CreateObject("WScript.Shell")
strPath = WScript.ScriptFullName
strDir = Left(strPath, InStrRev(strPath, "\"))

' Check if python is in path
On Error Resume Next
WshShell.Run "where python", 0, True
If Err.Number <> 0 Then
    MsgBox "Python is not found in PATH. Please install Python 3.7 or higher.", vbExclamation, "Ping Monitor"
    WScript.Quit
End If
On Error Goto 0

' Run the Ping Monitor script
WshShell.Run "pythonw " & strDir & "ping_monitor.py", 0, False

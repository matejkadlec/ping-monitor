' Truly hidden launcher for Ping Monitor
' This script launches the ping monitor with no visible windows at all

' Get the script directory
Set objFSO = CreateObject("Scripting.FileSystemObject")
strScriptPath = objFSO.GetParentFolderName(WScript.ScriptFullName)

' Set the working directory
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = strScriptPath

' Run the Python script with pythonw.exe (no window)
pythonPath = strScriptPath & "\venv\Scripts\python.exe"
pythonwPath = strScriptPath & "\venv\Scripts\pythonw.exe"
scriptPath = strScriptPath & "\main.py"
logsPath = strScriptPath & "\logs"
launcherLogPath = logsPath & "\launcher.log"

If Not objFSO.FolderExists(logsPath) Then
    objFSO.CreateFolder(logsPath)
End If

If Not objFSO.FileExists(pythonwPath) Then
    MsgBox "Ping Monitor virtual environment was not found." & vbCrLf & vbCrLf & _
        "Please run setup.bat first.", vbExclamation, "Ping Monitor"
    WScript.Quit 1
End If

' Check the packages that are imported before app logging is available.
checkCommand = "%ComSpec% /c " & Chr(34) & Chr(34) & pythonPath & Chr(34) & _
    " -c " & Chr(34) & "import psutil, pystray, PIL, winshell, win32com.client" & Chr(34) & _
    " > " & Chr(34) & launcherLogPath & Chr(34) & " 2>&1" & Chr(34)

checkResult = objShell.Run(checkCommand, 0, True)
If checkResult <> 0 Then
    MsgBox "Ping Monitor dependencies are not installed correctly." & vbCrLf & vbCrLf & _
        "Please run setup.bat again." & vbCrLf & _
        "Details were written to:" & vbCrLf & launcherLogPath, _
        vbExclamation, "Ping Monitor"
    WScript.Quit checkResult
End If

' Execute with window hidden (0 = hidden)
objShell.Run """" & pythonwPath & """ """ & scriptPath & """", 0, False

' Hidden launcher for Ping Monitor (no console window).
' Missing dependencies are reported by the app itself, so starting is instant.
Option Explicit

Dim fso, shell, root, pythonw, script, args, i
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
pythonw = root & "\venv\Scripts\pythonw.exe"
script = root & "\main.py"

If Not fso.FileExists(pythonw) Then
    MsgBox "Ping Monitor virtual environment was not found." & vbCrLf & vbCrLf & _
        "Please run setup.bat first.", vbExclamation, "Ping Monitor"
    WScript.Quit 1
End If

' Pass arguments through (e.g. --minimized when started with Windows).
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " """ & WScript.Arguments(i) & """"
Next

shell.Run """" & pythonw & """ """ & script & """" & args, 0, False

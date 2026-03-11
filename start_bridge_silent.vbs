Set WshShell = CreateObject("WScript.Shell")
' Get the directory of the VBScript
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Launch the Synapse Bridge on Port 5001 hidden
WshShell.Run """" & strPath & "\.venv\Scripts\python.exe"" """ & strPath & "\tools\synapse_bridge.py""", 0, False

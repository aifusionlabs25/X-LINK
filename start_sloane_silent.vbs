Set WshShell = CreateObject("WScript.Shell")
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Kill existing instances to ensure clean slate
WshShell.Run "taskkill /F /IM python.exe /T", 0, True
WScript.Sleep 1000

' Launch the Discord Bot
WshShell.Run """" & strPath & "\.venv\Scripts\python.exe"" """ & strPath & "\tools\discord_watcher.py""", 0, False

' Launch the Synapse Bridge (Hub API)
WshShell.Run """" & strPath & "\.venv\Scripts\python.exe"" """ & strPath & "\tools\synapse_bridge.py""", 0, False

' Launch the Email Commander (Gmail Listener)
WshShell.Run """" & strPath & "\.venv\Scripts\python.exe"" """ & strPath & "\tools\email_commander.py""", 0, False

' observer_gui.vbs - silent launcher for the PreToolUse hook observer.
'
' Double-clicking this .vbs file spawns the GUI without any console
' window appearing:
'   - wscript.exe (the VBScript host) is a GUI-subsystem binary, so
'     it does not allocate a console.
'   - We use WScript.Shell.Run with WindowStyle=0 (SW_HIDE) to hide
'     any window the child might try to create.
'   - We use pythonw.exe (also GUI subsystem) so the child itself
'     does not allocate a console.
'   - WaitOnReturn=False detaches the child and returns immediately,
'     so this script exits as soon as the GUI is launched.

Dim shell, repoRoot, pywExe, guiScript, cmd
Set shell = CreateObject("WScript.Shell")

' Resolve paths relative to this .vbs file
repoRoot  = shell.CurrentDirectory
' CurrentDirectory is the script's directory when run via wscript
guiScript = repoRoot & "\observer_gui.py"

' Walk up one level to find the project root (scripts/ is one below)
Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")
Dim scriptDir
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Dim projectRoot
projectRoot = fso.GetParentFolderName(scriptDir)

pywExe    = projectRoot & "\.venv\Scripts\pythonw.exe"
guiScript = scriptDir & "\observer_gui.py"

' Existence checks
If Not fso.FileExists(pywExe) Then
    MsgBox "Could not find pythonw.exe at:" & vbCrLf & vbCrLf & _
           pywExe & vbCrLf & vbCrLf & _
           "Your venv seems incomplete. Recreate it with:" & vbCrLf & _
           "    python -m venv .venv" & vbCrLf & _
           "    .venv\Scripts\python.exe -m pip install -e .", _
           vbCritical, "Observer"
    WScript.Quit 1
End If

If Not fso.FileExists(guiScript) Then
    MsgBox "Could not find GUI script at:" & vbCrLf & vbCrLf & _
           guiScript, vbCritical, "Observer"
    WScript.Quit 1
End If

' Build the command: "pythonw.exe" "observer_gui.py"
cmd = """" & pywExe & """ """ & guiScript & """"

' WindowStyle=0  -> SW_HIDE: hide any window the child might try to
'                    show (in case pythonw.exe ever regresses)
' WaitOnReturn=False -> fire-and-forget; the GUI process keeps running
'                        after this launcher exits
shell.Run cmd, 0, False

Set fso = Nothing
Set shell = Nothing
' run_hidden.vbs - run the command passed as WScript.Arguments with
' stdin/stdout/stderr forwarded back to the parent (and no console
' flash on screen).
'
' Why Exec() and not Run():
'   - WScript.Shell.Exec(cmd) returns a WshScriptExec object that
'     supports .StdIn, .StdOut, .StdErr streams, so the child process
'     inherits the parent's stdin/stdout. This is what Claude Code
'     needs to deliver the PreToolUse JSON payload to the hook and
'     read the Decision JSON back.
'   - WScript.Shell.Run() does NOT expose stdio streams. Run() can
'     hide windows (WindowStyle=0) and detach (WaitOnReturn=False),
'     but it cannot forward stdin/stdout. So Run() is unusable here.
'   - Exec() blocks until the child exits -- which is exactly what we
'     want for the hook: Claude Code waits for the hook to finish
'     before applying the decision, and we want the child's exit code
'     to propagate.
'
' Why no cmd /c start wrapper:
'   - An earlier version wrapped the child in cmd /c start "" /b /min
'     to try to hide the child window. But cmd.exe is itself a
'     console-subsystem binary, so launching it allocates a brand-new
'     console window that flashes briefly on screen. That flash was
'     the "approval-black-box" the user reported (see issue notes).
'   - Claude Code itself is a console-subsystem program (its .exe
'     PE header has Subsystem = 3), so the hook child (python.exe)
'     INHERITS Claude Code's console when launched directly via
'     Exec() -- no new console is allocated, no flash.
'   - We verified this: Exec("python.exe ...") forwards stdin/stdout
'     correctly (Python sys.stdin.read() receives the parent's pipe
'     data, sys.stdout.write() reaches the parent's stdout handle)
'     without any cmd.exe wrapper.
'
' Usage: wscript.exe //nologo run_hidden.vbs <token1> <token2> ...

Dim cmd, i, shell, execObj
cmd = ""
For i = 0 To WScript.Arguments.Count - 1
    Dim tok
    tok = WScript.Arguments(i)
    ' Auto-swap python.exe -> pythonw.exe (if it exists alongside it).
    '
    ' Why: when Claude Code forks the hook via wscript.exe, the inner
    ' python.exe is a console-subsystem binary. The Python interpreter
    ' launches with a console handle from wscript.exe (GUI subsystem),
    ' and on Windows that often produces a brief console window flash
    ' on screen -- the "approval black box" the user reported.
    '
    ' pythonw.exe is the GUI-subsystem variant of Python. It does NOT
    ' allocate a console at all. Critically, on Windows it still
    ' inherits the parent pipe handles (stdin/stdout/stderr), so the
    ' stdin/stdout forwarding below continues to work exactly the same
    ' way -- we verified this end-to-end with approve/deny/edit hooks.
    '
    ' If pythonw.exe does not exist next to python.exe (rare), we fall
    ' back to the original token unchanged so behavior is preserved.
    ' "python.exe" is exactly 10 characters (no leading slash), so
    ' Right(tok, 10) returns the last 10 chars and they will equal
    ' "python.exe" when this token IS the python.exe path. Note: the
    ' earlier version of this code matched "\\python.exe" (11 chars),
    ' which never matched Right(tok, 10) and so the swap silently
    ' never fired -- fixing that here.
    Dim tail
    tail = LCase(Right(tok, 10))
    If tail = "python.exe" Or tail = "/python.exe" Then
        Dim pywCandidate, fso
        ' Drop "python.exe" (10 chars) and append "pythonw.exe" (11 chars).
        pywCandidate = Left(tok, Len(tok) - 10) & "pythonw.exe"
        Set fso = CreateObject("Scripting.FileSystemObject")
        If fso.FileExists(pywCandidate) Then
            tok = pywCandidate
        End If
        Set fso = Nothing
    End If
    If i > 0 Then cmd = cmd & " "
    cmd = cmd & """" & tok & """"
Next

If cmd = "" Then
    WScript.Echo "Usage: run_hidden.vbs <token1> <token2> ..."
    WScript.Quit 1
End If

Set shell = CreateObject("WScript.Shell")
Set execObj = shell.Exec(cmd)

' Forward stdin from WScript.StdIn to the child's StdIn so the parent
' (Claude Code) can deliver the PreToolUse JSON payload.
Dim input
Do While Not WScript.StdIn.AtEndOfStream
    input = WScript.StdIn.Read(1)
    If Err.Number <> 0 Then Exit Do
    execObj.StdIn.Write input
Loop
execObj.StdIn.Close

' Wait for child to finish, then forward its stdout/stderr to
' WScript.StdOut / WScript.StdErr so the parent can read the
' Decision JSON.
Do While execObj.Status = 0
    WScript.Sleep 50
Loop

' Read whatever the child wrote to stdout and write it to our
' parent's stdout (wscript forwards StdOut.Write to the spawner).
Dim outChunk
Do While Not execObj.StdOut.AtEndOfStream
    outChunk = execObj.StdOut.Read(1)
    If Err.Number <> 0 Then Exit Do
    WScript.StdOut.Write outChunk
Loop

' Same for stderr
Dim errChunk
Do While Not execObj.StdErr.AtEndOfStream
    errChunk = execObj.StdErr.Read(1)
    If Err.Number <> 0 Then Exit Do
    WScript.StdErr.Write errChunk
Loop

WScript.Quit execObj.ExitCode
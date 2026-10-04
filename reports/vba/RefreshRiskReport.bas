Attribute VB_Name = "RefreshRiskReport"
' ---------------------------------------------------------------------------
' Counterparty Credit Risk & Exposure Analytics - report refresh macro
'
' Setup (once):
'   1. Open reports/Risk_Report.xlsx and save it as Risk_Report.xlsm in the
'      same "reports" folder.
'   2. Alt+F11 (Mac: Opt+F11) -> File -> Import File... -> this .bas file.
'   3. Run the macro "RefreshRiskReport" (Alt+F8).
'
' What it does:
'   Python (run_pipeline.py) writes one CSV per report sheet into
'   reports/latest/. This macro reloads each CSV into the matching sheet
'   (headers in row 4, data from row 5). Number formats, conditional
'   formatting and the dashboard charts are kept.
' ---------------------------------------------------------------------------
Option Explicit

Private Const HEADER_ROW As Long = 4
Private Const DATA_FOLDER As String = "latest"

Public Sub RefreshRiskReport()
    Dim sheetNames As Variant
    Dim i As Long, refreshed As Long
    Dim folder As String

    sheetNames = Array("Dashboard", "Counterparties", "Exposure", "PFE", "Initial Margin", _
                       "Collateral", "Credit Analysis", "Limit Breaches", "Daily Commentary")
    folder = ThisWorkbook.Path & Application.PathSeparator & DATA_FOLDER & Application.PathSeparator

    Application.ScreenUpdating = False
    Application.DisplayAlerts = False
    On Error GoTo Failed

    For i = LBound(sheetNames) To UBound(sheetNames)
        If LoadCsvIntoSheet(folder & sheetNames(i) & ".csv", CStr(sheetNames(i))) Then
            refreshed = refreshed + 1
        End If
    Next i

    Application.DisplayAlerts = True
    Application.ScreenUpdating = True
    MsgBox refreshed & " sheet(s) refreshed from " & folder, vbInformation, "Risk Report"
    Exit Sub

Failed:
    Application.DisplayAlerts = True
    Application.ScreenUpdating = True
    MsgBox "Refresh failed: " & Err.Description, vbCritical, "Risk Report"
End Sub

Private Function LoadCsvIntoSheet(ByVal csvPath As String, ByVal sheetName As String) As Boolean
    Dim source As Workbook
    Dim target As Worksheet
    Dim data As Range
    Dim lastRow As Long, lastCol As Long

    If Dir(csvPath) = "" Then
        MsgBox "Missing data file: " & csvPath & vbCrLf & _
               "Run `python run_pipeline.py` first.", vbExclamation, "Risk Report"
        Exit Function
    End If

    Set target = ThisWorkbook.Worksheets(sheetName)
    Set source = Workbooks.Open(Filename:=csvPath, ReadOnly:=True, Local:=False)
    Set data = source.Worksheets(1).UsedRange

    ' Clear the old values (not the formats) below the title block.
    lastRow = target.Cells(target.Rows.Count, 1).End(xlUp).Row
    lastCol = target.Cells(HEADER_ROW, target.Columns.Count).End(xlToLeft).Column
    If lastRow >= HEADER_ROW Then
        target.Range(target.Cells(HEADER_ROW, 1), target.Cells(lastRow, lastCol)).ClearContents
    End If

    target.Cells(HEADER_ROW, 1).Resize(data.Rows.Count, data.Columns.Count).Value = data.Value
    source.Close SaveChanges:=False
    LoadCsvIntoSheet = True
End Function

' Optional (Windows): re-run the Python pipeline, then refresh the workbook.
' Adjust PYTHON_EXE if Python is not on the PATH (e.g. "C:\path\to\.venv\Scripts\python.exe").
Public Sub RunPipelineAndRefresh()
    Const PYTHON_EXE As String = "python"
    Dim projectRoot As String
    Dim shellObject As Object

    projectRoot = Left(ThisWorkbook.Path, InStrRev(ThisWorkbook.Path, Application.PathSeparator) - 1)
    #If Mac Then
        MsgBox "On macOS run `python run_pipeline.py` in Terminal, then run RefreshRiskReport.", _
               vbInformation, "Risk Report"
    #Else
        Set shellObject = CreateObject("WScript.Shell")
        shellObject.CurrentDirectory = projectRoot
        shellObject.Run PYTHON_EXE & " run_pipeline.py", 1, True   ' wait for completion
        RefreshRiskReport
    #End If
End Sub

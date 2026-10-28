$ErrorActionPreference = "Stop"
$src = $args[0]
$dst = $args[1]
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($src, $false, $true)
    $doc.SaveAs([ref]$dst, [ref]16)   # 16 = wdFormatXMLDocument (.docx)
    $doc.Close()
    Write-Output "OK $dst"
} finally {
    $word.Quit()
}

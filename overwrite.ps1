$dir = 'C:\Users\nitay\Documents\files'
$backup = Join-Path $dir '_backup'
New-Item -ItemType Directory -Force -Path $backup | Out-Null
while ($true) {
  Get-ChildItem -LiteralPath $dir -File | ForEach-Object {
    $m = [regex]::Match($_.Name, '^(.+) \(\d+\)(\.[^.]*)?$')
    if ($m.Success) {
      $orig = Join-Path $dir ($m.Groups[1].Value + $m.Groups[2].Value)
      if (Test-Path -LiteralPath $orig) {
        try {
          $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
          $bk = Join-Path $backup ($stamp + '-' + (Split-Path $orig -Leaf))
          Copy-Item -LiteralPath $orig -Destination $bk -ErrorAction Stop
          Move-Item -LiteralPath $_.FullName -Destination $orig -Force -ErrorAction Stop
        } catch { }
      }
    }
  }
  Start-Sleep -Seconds 2
}
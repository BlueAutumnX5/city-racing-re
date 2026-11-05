# Measure the player car's bounding box in the A/B screenshots.
# Uses WIC via PresentationCore, which handles WebP on Win11 if the codec is present.
Add-Type -AssemblyName PresentationCore

$imgs = @{
  'ROUND1 patched 16:9' = $args[0]
  'ROUND2 stock   4:3'  = $args[1]
}

foreach ($k in 'ROUND1 patched 16:9','ROUND2 stock   4:3') {
  $path = $imgs[$k]
  if (-not (Test-Path -LiteralPath $path)) { "$k : MISSING $path"; continue }
  try {
    $uri = New-Object System.Uri($path)
    $dec = [System.Windows.Media.Imaging.BitmapDecoder]::Create(
             $uri, 'None', 'OnLoad')
    $fr  = $dec.Frames[0]
  } catch {
    "$k : DECODE FAILED -> $($_.Exception.Message)"; continue
  }

  $conv = New-Object System.Windows.Media.Imaging.FormatConvertedBitmap
  $conv.BeginInit(); $conv.Source = $fr
  $conv.DestinationFormat = [System.Windows.Media.PixelFormats]::Bgra32
  $conv.EndInit()

  $w = $conv.PixelWidth; $h = $conv.PixelHeight
  $stride = $w * 4
  $buf = New-Object byte[] ($stride * $h)
  $conv.CopyPixels($buf, $stride, 0)

  # search window: lower-centre only, to exclude the RivaTuner overlay text
  # and other vehicles near the horizon
  $x0 = [int]($w * 0.30); $x1 = [int]($w * 0.70)
  $y0 = [int]($h * 0.52); $y1 = [int]($h * 0.96)

  $minX = $w; $maxX = -1; $minY = $h; $maxY = -1; $count = 0
  for ($y = $y0; $y -lt $y1; $y++) {
    $row = $y * $stride
    for ($x = $x0; $x -lt $x1; $x++) {
      $i = $row + $x * 4
      $b = $buf[$i]; $g = $buf[$i+1]; $r = $buf[$i+2]
      # strong red/orange body paint: red dominant over both others
      if ($r -gt 140 -and $r - $g -gt 60 -and $r - $b -gt 60) {
        $count++
        if ($x -lt $minX) { $minX = $x }
        if ($x -gt $maxX) { $maxX = $x }
        if ($y -lt $minY) { $minY = $y }
        if ($y -gt $maxY) { $maxY = $y }
      }
    }
  }

  if ($maxX -lt 0) { "$k : no red pixels found in window"; continue }
  $bw = $maxX - $minX + 1
  $bh = $maxY - $minY + 1
  "{0} : image {1}x{2}  red px {3}" -f $k, $w, $h, $count
  "{0}   car bbox x[{1}..{2}] y[{3}..{4}]  W={5} H={6}  W/H={7:N4}" -f `
      (' ' * $k.Length), $minX, $maxX, $minY, $maxY, $bw, $bh, ($bw / $bh)
}

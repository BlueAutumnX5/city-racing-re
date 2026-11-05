# Measure the player car's red bounding box in any number of City Racing screenshots,
# and report width as a FRACTION of screen width so different resolutions compare directly.
Add-Type -AssemblyName PresentationCore

foreach ($path in $args) {
  if (-not (Test-Path -LiteralPath $path)) { "MISSING $path"; continue }
  try {
    $uri = New-Object System.Uri($path)
    $dec = [System.Windows.Media.Imaging.BitmapDecoder]::Create($uri, 'None', 'OnLoad')
    $fr  = $dec.Frames[0]
  } catch { "DECODE FAILED $path -> $($_.Exception.Message)"; continue }

  $conv = New-Object System.Windows.Media.Imaging.FormatConvertedBitmap
  $conv.BeginInit(); $conv.Source = $fr
  $conv.DestinationFormat = [System.Windows.Media.PixelFormats]::Bgra32
  $conv.EndInit()

  $w = $conv.PixelWidth; $h = $conv.PixelHeight
  $stride = $w * 4
  $buf = New-Object byte[] ($stride * $h)
  $conv.CopyPixels($buf, $stride, 0)

  # lower-centre window only: excludes any overlay text and distant vehicles
  $x0 = [int]($w * 0.30); $x1 = [int]($w * 0.70)
  $y0 = [int]($h * 0.52); $y1 = [int]($h * 0.96)

  $minX = $w; $maxX = -1; $minY = $h; $maxY = -1; $count = 0
  for ($y = $y0; $y -lt $y1; $y++) {
    $row = $y * $stride
    for ($x = $x0; $x -lt $x1; $x++) {
      $i = $row + $x * 4
      $b = $buf[$i]; $g = $buf[$i+1]; $r = $buf[$i+2]
      if ($r -gt 140 -and $r - $g -gt 60 -and $r - $b -gt 60) {
        $count++
        if ($x -lt $minX) { $minX = $x }
        if ($x -gt $maxX) { $maxX = $x }
        if ($y -lt $minY) { $minY = $y }
        if ($y -gt $maxY) { $maxY = $y }
      }
    }
  }

  $name = Split-Path $path -Leaf
  if ($maxX -lt 0) { "{0,-10} {1}x{2}  no red pixels found" -f $name,$w,$h; continue }
  $bw = $maxX - $minX + 1
  $bh = $maxY - $minY + 1
  "{0,-10} {1,5}x{2,-5} carW={3,4}  carH={4,4}  W/screenW={5:N4}  H/screenH={6:N4}  px={7}" -f `
      $name, $w, $h, $bw, $bh, ($bw / $w), ($bh / $h), $count
}

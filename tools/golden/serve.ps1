# Localhost-only static server used to run the JS prototype engine (the reference oracle) in a browser
# and capture its outputs as golden files.
#   GET  /<file>            serves files from reference/prototype_js and tools/golden
#   POST /save/<name>.json  writes the request body to tests/golden/<name>.json
param([int]$Port = 8765)
$project = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$roots = @((Join-Path $project 'tools\golden'), (Join-Path $project 'reference\prototype_js'))
$outDir = Join-Path $project 'tests\golden'
$types = @{ '.html' = 'text/html; charset=utf-8'; '.js' = 'text/javascript; charset=utf-8'; '.json' = 'application/json' }
$l = New-Object System.Net.HttpListener
$l.Prefixes.Add("http://localhost:$Port/")
$l.Start()
Write-Output "Serving on http://localhost:$Port/ ; golden output -> $outDir"
while ($l.IsListening) {
  $c = $l.GetContext()
  $name = [Uri]::UnescapeDataString($c.Request.Url.AbsolutePath.TrimStart('/'))
  if ($c.Request.HttpMethod -eq 'POST' -and $name -match '^save/([A-Za-z0-9_\-]+\.json)$') {
    $reader = New-Object IO.StreamReader($c.Request.InputStream, [Text.Encoding]::UTF8)
    $body = $reader.ReadToEnd(); $reader.Close()
    [IO.File]::WriteAllText((Join-Path $outDir $Matches[1]), $body, (New-Object Text.UTF8Encoding($false)))
    $c.Response.StatusCode = 200
  } else {
    if ($name -eq '') { $name = 'generate_validation_golden.html' }
    $found = $null
    foreach ($r in $roots) {
      $p = [IO.Path]::GetFullPath((Join-Path $r $name))
      if ($p.StartsWith($r) -and (Test-Path $p -PathType Leaf)) { $found = $p; break }
    }
    if ($found) {
      $bytes = [IO.File]::ReadAllBytes($found)
      $ext = [IO.Path]::GetExtension($found)
      $c.Response.ContentType = $(if ($types.ContainsKey($ext)) { $types[$ext] } else { 'application/octet-stream' })
      $c.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    } else { $c.Response.StatusCode = 404 }
  }
  Write-Output "$($c.Request.HttpMethod) /$name $($c.Response.StatusCode)"
  $c.Response.Close()
}

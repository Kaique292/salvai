$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

function Invoke-Step {
  param([string[]]$Arguments)
  & $python @Arguments
  if ($LASTEXITCODE -ne 0) { throw "Falhou: python $($Arguments -join ' ')" }
}

Invoke-Step @("scripts\brand.py")
Invoke-Step @("scripts\make_splash.py")
Invoke-Step @("-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", "dist", "--workpath", "build\pyinstaller", "packaging\Salvai.spec")
Invoke-Step @("-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console", "--name", "salvai-mcp",
  "--icon", "$root\assets\icon.ico", "--add-data", "$root\packaging\salvai-mcp.marker;.",
  "--exclude-module", "PIL", "--exclude-module", "numpy", "--exclude-module", "tkinter",
  "--exclude-module", "pytest", "--exclude-module", "_pytest", "--exclude-module", "pygments.formatters.img",
  "--distpath", "dist", "--workpath", "build\pyinstaller",
  "--specpath", "build\pyinstaller", "src\salvai_mcp.py")

Get-ChildItem dist\*.exe | ForEach-Object {
  "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)"
} | Set-Content dist\SHA256SUMS.txt -Encoding ascii

Write-Host "Salvai $((Get-Content version.txt -Raw).Trim()) pronto em dist\"

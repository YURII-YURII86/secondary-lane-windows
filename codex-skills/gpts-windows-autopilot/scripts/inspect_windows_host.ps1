param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"

function Get-CmdResult {
  param(
    [string]$FilePath,
    [string[]]$ArgumentList
  )

  try {
    $output = & $FilePath @ArgumentList 2>&1
    return @{
      ok = $true
      output = ($output | Out-String).Trim()
    }
  } catch {
    return @{
      ok = $false
      output = ($_ | Out-String).Trim()
    }
  }
}

function Get-FirstOpenApiUrl {
  param([string]$Path)
  if (-not (Test-Path $Path)) { return $null }
  foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
    $trimmed = $line.Trim()
    if ($trimmed -like "- url:*") {
      return ($trimmed -split ":\s*", 2)[1]
    }
  }
  return $null
}

function Get-EnvMap {
  param([string]$Path)
  $map = @{}
  if (-not (Test-Path $Path)) { return $map }
  foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    if ($line.TrimStart().StartsWith("#")) { continue }
    if ($line -notmatch "=") { continue }
    $pair = $line -split "=", 2
    $map[$pair[0].Trim()] = $pair[1].Trim()
  }
  return $map
}

function Test-BranchRoot {
  param([string]$Path)
  if (-not (Test-Path (Join-Path $Path ".env.example"))) { return $false }
  $sideMarkers = @("gpts_agent_control.py", "openapi.gpts.yaml")
  foreach ($marker in $sideMarkers) {
    if (Test-Path (Join-Path $Path $marker)) { return $true }
  }
  return $false
}

$knownBranchNames = @(
  "Версия для Виндовс",
  "Secondary-LANE-Windows",
  "secondary-lane-windows",
  "SecondaryLANE-Windows",
  "SecondLane",
  "Secondary LANE"
)

function Find-BranchRoot {
  param([string]$StartPath)
  $resolved = (Resolve-Path -Path $StartPath -ErrorAction SilentlyContinue)
  if (-not $resolved) { throw "Path not found: $StartPath" }
  $start = $resolved.Path

  # 1. start itself
  if (Test-BranchRoot -Path $start) { return $start }

  # 2. known-named subfolders
  foreach ($name in $knownBranchNames) {
    $candidate = Join-Path $start $name
    if (Test-BranchRoot -Path $candidate) { return $candidate }
  }

  # 3. walk up a few levels
  $current = $start
  for ($i = 0; $i -lt 4; $i++) {
    $parent = Split-Path -Parent $current
    if ([string]::IsNullOrEmpty($parent) -or $parent -eq $current) { break }
    if (Test-BranchRoot -Path $parent) { return $parent }
    $current = $parent
  }

  # 4. bounded walk down (depth <=4, skipping junk dirs)
  $queue = New-Object System.Collections.Generic.Queue[object]
  $queue.Enqueue(@{ Path = $start; Depth = 0 })
  $skip = @(".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode")
  while ($queue.Count -gt 0) {
    $item = $queue.Dequeue()
    $p = $item.Path
    $d = $item.Depth
    if (Test-BranchRoot -Path $p) { return $p }
    if ($d -ge 4) { continue }
    try {
      $children = Get-ChildItem -LiteralPath $p -Directory -Force -ErrorAction SilentlyContinue
    } catch { continue }
    foreach ($child in $children) {
      if ($skip -contains $child.Name) { continue }
      if ($child.Name.StartsWith(".")) { continue }
      $queue.Enqueue(@{ Path = $child.FullName; Depth = $d + 1 })
    }
  }

  throw @"
Could not find the Windows project branch root.
  Searched under: $start
  Looked for: .env.example + gpts_agent_control.py (or openapi.gpts.yaml)
  Checked known folder names: $($knownBranchNames -join ', ')

Fix: make sure you unpacked the Secondary LANE archive, and that the path
you passed either IS the Windows branch folder or a folder that directly
contains it.
"@
}

$branchRoot = Find-BranchRoot -StartPath $ProjectRoot

$important = @(
  ".env.example",
  ".env",
  "openapi.gpts.yaml",
  "gpts\system_instructions.txt",
  "Запустить GPTS Agent.bat",
  "gpts_agent_control.py"
)

$files = @{}
foreach ($relative in $important) {
  $full = Join-Path $branchRoot $relative
  $files[$relative] = @{
    exists = (Test-Path $full)
    path = $full
  }
}

$envPath = Join-Path $branchRoot ".env"
$openapiPath = Join-Path $branchRoot "openapi.gpts.yaml"
$knowledgeRoot = Join-Path $branchRoot "gpts\knowledge"
$envMap = Get-EnvMap -Path $envPath
$knowledgeFiles = @()
if (Test-Path $knowledgeRoot) {
  $knowledgeFiles = Get-ChildItem -Path $knowledgeRoot -Recurse -Filter *.md | ForEach-Object { $_.FullName }
}

$workspaceRoots = ""
if ($envMap.ContainsKey("WORKSPACE_ROOTS")) {
  $workspaceRoots = $envMap["WORKSPACE_ROOTS"]
}
$firstWorkspaceRoot = ""
if ($workspaceRoots) {
  $firstWorkspaceRoot = ($workspaceRoots -split ";")[0]
}

$result = [ordered]@{
  host_platform = "windows"
  branch_root = $branchRoot
  important_files = $files
  env = @{
    exists = (Test-Path $envPath)
    agent_token_present = [bool]$envMap["AGENT_TOKEN"]
    ngrok_domain = $envMap["NGROK_DOMAIN"]
    workspace_roots = $workspaceRoots
    first_workspace_root = $firstWorkspaceRoot
    first_workspace_root_matches_branch = ($firstWorkspaceRoot -eq $branchRoot)
  }
  openapi = @{
    path = $openapiPath
    server_url = (Get-FirstOpenApiUrl -Path $openapiPath)
  }
  knowledge = @{
    root = $knowledgeRoot
    count = $knowledgeFiles.Count
    files = $knowledgeFiles
  }
  commands = @{
    py_3_13 = (Get-CmdResult -FilePath "py" -ArgumentList @("-3.13", "--version"))
    python = (Get-CmdResult -FilePath "python" -ArgumentList @("--version"))
    ngrok = (Get-CmdResult -FilePath "ngrok" -ArgumentList @("version"))
  }
}

$result | ConvertTo-Json -Depth 6

function Resolve-MinaJavaHome {
    # Prefer explicit toolchain selection. All build steps use this same JDK.
    $selected = $env:MINA_JAVA_HOME
    if ([string]::IsNullOrWhiteSpace($selected)) { $selected = $env:JAVA_HOME }
    if ([string]::IsNullOrWhiteSpace($selected)) {
        $compiler = Get-Command javac -ErrorAction SilentlyContinue
        if (!$compiler) { throw 'Install a complete OpenJDK 17+ and set MINA_JAVA_HOME to its installation directory.' }
        $selected = Split-Path (Split-Path $compiler.Source -Parent) -Parent
        if (!(Test-Path -LiteralPath (Join-Path $selected 'release'))) {
            # PATH may contain a vendor javac launcher/shim, not the JDK bin directory.
            $previousPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                $settings = & $compiler.Source '-J-XshowSettings:properties' '-version' 2>&1
                $compilerExit = $LASTEXITCODE
            } finally { $ErrorActionPreference = $previousPreference }
            $homeLine = $settings | ForEach-Object { [string]$_ } | Where-Object { $_ -match '^\s*java\.home\s*=\s*(.+?)\s*$' } | Select-Object -First 1
            if ($compilerExit -ne 0 -or !$homeLine) { throw 'Cannot resolve the JDK behind javac. Set MINA_JAVA_HOME explicitly.' }
            $selected = ([regex]::Match($homeLine, '^\s*java\.home\s*=\s*(.+?)\s*$')).Groups[1].Value
        }
    }
    $selected = [System.IO.Path]::GetFullPath($selected.Trim().Trim('"'))
    # Windows PowerShell 5.1's native argv quoting turns a final backslash
    # before the closing quote into a literal quote for paths containing spaces.
    # Keep a volume root intact, but never return a trailing JDK separator.
    $volumeRoot = [System.IO.Path]::GetPathRoot($selected)
    if ($selected.Length -gt $volumeRoot.Length) { $selected = $selected.TrimEnd([char[]]'\/') }
    foreach ($relative in @('release', 'bin\java.exe', 'bin\javac.exe', 'bin\jlink.exe', 'lib\src.zip')) {
        if (!(Test-Path -LiteralPath (Join-Path $selected $relative) -PathType Leaf)) {
            throw "Incomplete JDK at '$selected' (missing $relative). Set MINA_JAVA_HOME to a complete OpenJDK 17+."
        }
    }
    if (!(Test-Path -LiteralPath (Join-Path $selected 'legal') -PathType Container)) {
        throw "Incomplete JDK at '$selected' (missing legal directory). Set MINA_JAVA_HOME to a complete OpenJDK 17+."
    }
    $release = Get-Content -LiteralPath (Join-Path $selected 'release') -Raw
    $major = [regex]::Match($release, '(?m)^JAVA_VERSION="(\d+)')
    if (!$major.Success -or [int]$major.Groups[1].Value -lt 17) { throw "JDK 17+ is required; check MINA_JAVA_HOME '$selected'." }
    return $selected
}

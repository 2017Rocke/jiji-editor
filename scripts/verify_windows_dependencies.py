"""Reject reliance on a machine-installed Visual C++ runtime in the portable ZIP.

Windows system libraries (including the Windows 10 UCRT) are OS prerequisites.
The redistributable MSVC libraries must instead resolve within each bundled
application's loader directories; an existing copy in System32 is not evidence.
"""
import json
from pathlib import Path
import re
import sys

import pefile  # Installed by the Windows PyInstaller build dependency.

root = Path(sys.argv[1]).resolve()
redistributable = re.compile(r'^(?:vcruntime\d+|msvcp\d+|msvcr\d+|concrt\d+|mfc\d+|vcomp\d+|vccorlib\d+|atl\d+).*\.dll$', re.I)
checked = 0
dependencies = set()
missing = []
for binary in root.rglob('*'):
    if binary.suffix.lower() not in ('.exe', '.dll', '.pyd') or not binary.is_file():
        continue
    relative = binary.relative_to(root)
    # PyInstaller sets its _internal directory as the native DLL search root.
    if relative.parts[0] == 'backend':
        search = [binary.parent, root / 'backend/_internal', root / 'backend']
    elif relative.parts[0] == 'webview2':
        search = [binary.parent, root / 'webview2']
    else:
        search = [binary.parent, root]
    available = {p.name.casefold() for folder in search if folder.is_dir() for p in folder.iterdir() if p.is_file()}
    with pefile.PE(str(binary), fast_load=True) as executable:
        executable.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
            pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT'],
        ])
        checked += 1
        for entry in (getattr(executable, 'DIRECTORY_ENTRY_IMPORT', []) +
                      getattr(executable, 'DIRECTORY_ENTRY_DELAY_IMPORT', [])):
            name = entry.dll.decode('ascii').casefold()
            if redistributable.match(name):
                dependencies.add(name)
                if name not in available:
                    missing.append(f'{relative}: {name}')
if missing:
    raise RuntimeError('Unbundled Visual C++ runtime dependencies: ' + '; '.join(missing))
if checked < 20:
    raise RuntimeError('The portable package is incomplete')
report = {'passed': True, 'checkedBinaries': checked, 'bundledVisualCppDependencies': sorted(dependencies)}
Path('output/native-dependencies-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))

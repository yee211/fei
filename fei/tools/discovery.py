from fei.tools.base import Tool
from fei.discovery import list_directory, find_files

base={"path":{"type":"string","description":"Directory relative to workdir, default ."},"depth":{"type":"integer","minimum":1,"maximum":50},"limit":{"type":"integer","minimum":1,"maximum":2000},"include_hidden":{"type":"boolean"},"include_ignored":{"type":"boolean","description":"Include dependency/build/cache directories; default false"}}
list_tool=Tool("list_directory","List relative file/directory paths, bounded by depth and limit. Defaults depth=2/limit=200. Skips hidden/dependency/cache entries and symlinks. Scans at most 10000 entries or 5 seconds.",{"type":"object","properties":base,"additionalProperties":False},list_directory)
find_tool=Tool("find_files","Find files by basename glob or relative path pattern, e.g. *config* or tests/**/*.py. Defaults depth=20/limit=100; same ignore and scan limits as list_directory.",{"type":"object","properties":{**base,"pattern":{"type":"string"}},"required":["pattern"],"additionalProperties":False},find_files)

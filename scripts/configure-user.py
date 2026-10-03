#!/usr/bin/env python3
"""Install/remove only marked proxy startup blocks in the target user's files."""

from pathlib import Path
import re
import sys


BEGIN = "# BEGIN MIHOMO DEFAULT PROXY"
END = "# END MIHOMO DEFAULT PROXY"
BLOCK = '''# BEGIN MIHOMO DEFAULT PROXY
if [ -r "${XDG_CONFIG_HOME:-$HOME/.config}/mihomo-toolkit/proxy-defaults.sh" ]; then
    . "${XDG_CONFIG_HOME:-$HOME/.config}/mihomo-toolkit/proxy-defaults.sh"
fi
# END MIHOMO DEFAULT PROXY
'''
STARTUP_FILES = (".zshenv", ".profile", ".bashrc", ".xsessionrc", ".gnomerc")


def configure(home, install):
    files = STARTUP_FILES + tuple(name for name in (".bash_profile", ".bash_login")
                                 if (home / name).exists())
    for name in files:
        path = home / name
        if path.is_symlink():
            print(f"保留符号链接，请手动维护代理启动区块：{path}", file=sys.stderr)
            continue
        if not path.exists() and not install:
            continue
        original = path.read_text() if path.exists() else ""
        if (BEGIN in original) != (END in original):
            raise ValueError(f"代理启动区块不完整，请先修复：{path}")
        cleaned = re.sub(r"(?m)^" + re.escape(BEGIN) + r"\n.*?^" + re.escape(END) + r"\n?",
                         "", original, flags=re.DOTALL)
        text = cleaned.rstrip() + "\n\n" + BLOCK if install else cleaned
        if text != original:
            path.write_text(text)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("install", "remove"):
        print("用法：configure-user.py install|remove", file=sys.stderr)
        return 2
    configure(Path.home(), sys.argv[1] == "install")
    return 0


if __name__ == "__main__":
    sys.exit(main())

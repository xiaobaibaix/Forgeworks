#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bridge 的 PTY 子进程入口：取得控制终端后 exec 登录 shell。"""

import fcntl
import os
import sys
import termios


def main():
    shell = sys.argv[1] if len(sys.argv) > 1 else (os.environ.get('SHELL') or '/bin/sh')
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError:
        pass
    os.execvpe(shell, [shell, '-l'], os.environ.copy())


if __name__ == '__main__':
    main()

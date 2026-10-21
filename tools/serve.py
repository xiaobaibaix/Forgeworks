#!/usr/bin/env python3
"""
Forgeworks 启动器
================================================================

默认以 Bridge 启动：同一个端口既发界面，也提供 /api（同步、Blender、管线）。
Bridge 已经在 tools/bridge.py 里继承了 no-store，所以不再需要单独的静态服务。

用法：
    python3 tools/serve.py          # 8787 端口，等于启动 Bridge
    python3 tools/serve.py 9000     # 指定端口
    python3 tools/serve.py --static # 只发静态文件，不启 Bridge
"""

import http.server
import os
import socketserver
import sys


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """--static 模式：所有响应禁缓存。"""

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def run_static(port, root):
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('127.0.0.1', port), NoCacheHandler) as httpd:
        print(f'Forgeworks 静态服务  http://127.0.0.1:{port}/')
        print(f'根目录: {root}')
        print('Ctrl+C 停止。')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\n已停止。')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    port = int(args[0]) if args else 8787
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)

    if '--static' in sys.argv[1:]:
        run_static(port, root)
        return

    bridge = os.path.join(root, 'tools', 'bridge.py')
    if not os.path.exists(bridge):
        print(f'找不到 {bridge}，退回静态服务。', file=sys.stderr)
        run_static(port, root)
        return
    os.execv(sys.executable, [sys.executable, bridge, str(port)])


if __name__ == '__main__':
    main()

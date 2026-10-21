#!/usr/bin/env python3
"""
Forgeworks 开发服务器
================================================================

为什么不用 `python -m http.server`：
    它不发送 Cache-Control，浏览器会对 .js 应用启发式缓存。
    结果是改了代码、刷新页面，跑的却还是旧版本 —— 很难排查。

本脚本给所有响应加 no-store，保证每次刷新都拿最新文件。

用法：
    python3 tools/serve.py          # 默认 8787 端口
    python3 tools/serve.py 9000     # 指定端口
"""

import http.server
import socketserver
import os
import sys


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """在所有响应上禁缓存。"""

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, fmt, *args):
        # 安静模式，只打印错误
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('127.0.0.1', port), NoCacheHandler) as httpd:
        print(f'Forgeworks 已启动  http://127.0.0.1:{port}/')
        print(f'根目录: {root}')
        print('已禁用缓存，改完文件刷新即可生效。Ctrl+C 停止。')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\n已停止。')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""extract_agnocast.py - LTTng トレースから agnocast_info.json を生成する

使用方法:
  python extract_agnocast.py <trace_dir> [output.json]

  ※ babeltrace の出力テキストファイルを直接渡すことも可能:
  python extract_agnocast.py raw.log [output.json]
"""

import json
import subprocess
import sys
import re
import os


def extract_agnocast_nodes_from_text(text: str) -> list[str]:
    """babeltrace 出力テキストから agnocast_node_init イベントを抽出する"""
    agnocast_nodes = set()

    # TRACEPOINT_PROVIDER はソースコードでは "agnocast" だが、
    # caret_trace 経由で記録すると "ros2_caret" に統合される。
    # "agnocast_node_init:" だけでマッチさせることで両方に対応。
    pattern = re.compile(
        r'agnocast_node_init:.*?'
        r'node_name\s*=\s*"([^"]*)".*?'
        r'namespace\s*=\s*"([^"]*)"'
    )

    for line in text.splitlines():
        match = pattern.search(line)
        if match:
            name = match.group(1)
            namespace = match.group(2).rstrip('/')
            full_name = namespace + '/' + name if namespace else '/' + name
            agnocast_nodes.add(full_name)

    return sorted(agnocast_nodes)


def extract_agnocast_nodes(trace_dir: str) -> list[str]:
    """babeltrace で agnocast_node_init イベントを抽出する"""
    # テキストファイルが直接渡された場合はそのまま読む
    if os.path.isfile(trace_dir) and not os.path.isdir(trace_dir):
        with open(trace_dir, 'r') as f:
            text = f.read()
        return extract_agnocast_nodes_from_text(text)

    # ディレクトリの場合は babeltrace を実行
    cmd = ['babeltrace', trace_dir]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        print(f"Error: babeltrace failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    return extract_agnocast_nodes_from_text(result.stdout)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <trace_dir_or_log_file> [output.json]", file=sys.stderr)
        sys.exit(1)

    trace_dir = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'agnocast_info.json'

    nodes = extract_agnocast_nodes(trace_dir)

    info = {
        "version": 1,
        "source": "babeltrace",
        "agnocast_nodes": nodes
    }

    with open(output_file, 'w') as f:
        json.dump(info, f, indent=2)

    print(f"Extracted {len(nodes)} agnocast nodes -> {output_file}")
    for node in nodes:
        print(f"  {node}")


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""python -m backend 启动本地报销网页。

仓库由环境变量 AF_REPO 决定，启动脚本会先设好。
也可以直接写：python -m backend repo.sample
"""
import os
import sys


def _take_repo(argv):
    repo = None
    rest = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in {"--repo", "-r"} and index + 1 < len(argv):
            repo = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--repo="):
            repo = arg.split("=", 1)[1]
            index += 1
            continue
        rest.append(arg)
        index += 1
    if repo is None and len(rest) == 1 and not rest[0].startswith("-"):
        repo = rest[0]
        rest = []
    return repo, rest


if __name__ == "__main__":
    chosen, remaining = _take_repo(sys.argv[1:])
    if chosen:
        os.environ["AF_REPO"] = chosen
    sys.argv = [sys.argv[0], *remaining]
    from .server import main

    main()

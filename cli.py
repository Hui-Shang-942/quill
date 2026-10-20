"""命令行入口：用于联调与录制验证。

  python cli.py health
  python cli.py run --product "MateBook Pro S" --audience "大学新生" --scenario 开学季 --platform 小红书
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from agent.exporter import export, plain_text, render_markdown
from agent.pipeline import Agent, Task


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    r = sub.add_parser("run")
    r.add_argument("--raw", default="")
    r.add_argument("--product", default="")
    r.add_argument("--audience", default="")
    r.add_argument("--scenario", default="")
    r.add_argument("--platform", default="")
    r.add_argument("--extra", default="")
    r.add_argument("--export", action="store_true")
    r.add_argument("--name", default="")
    a = ap.parse_args()

    agent = Agent()
    if a.cmd == "health":
        print(agent.health())
        return
    task = Task(raw=a.raw or f"{a.audience} {a.product} {a.platform} {a.extra}", model_text=a.product,
                audience=a.audience, scenario=a.scenario, platform=a.platform, extra=a.extra)
    res = agent.start(task, progress=lambda s: print(f"… {s}", file=sys.stderr))
    if res["status"] == "need_info":
        print("需要补充信息：")
        for q in res["questions"]:
            print(f" - {q['question']} {q.get('options') or ''}")
        return
    if res["status"] == "ok":
        paths = export(res, a.name or None)      # 先落盘，再打印
        print(f"已导出：{paths['md']}")
    print(render_markdown(res))


if __name__ == "__main__":
    main()

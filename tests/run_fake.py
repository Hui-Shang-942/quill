"""用测试替身端到端跑一遍流水线，检查逻辑。用法: python tests/run_fake.py <产品> <人群> <场景> <平台> [extra]"""
import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fake_ima import FakeIma
from agent.pipeline import Agent, Task
from agent.exporter import render_markdown

prod, aud, sc, plat = sys.argv[1:5]
extra = sys.argv[5] if len(sys.argv) > 5 else ""
t0 = time.time()
agent = Agent(ima=FakeIma())
res = agent.start(Task(raw=f"{aud} {prod} {plat} {extra}", model_text=prod, audience=aud, scenario=sc, platform=plat, extra=extra),
                  progress=lambda s: print("…", s, file=sys.stderr))
print(f"[{res['status']}] {time.time()-t0:.0f}s usage={res.get('usage')}", file=sys.stderr)
print(render_markdown(res) if res["status"] == "ok" else res)

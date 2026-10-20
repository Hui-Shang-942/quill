# Gradio 创空间部署设计

## 目标

将 `quill-of-Huawei` 从 Flask 自有网页迁移到 Gradio 界面，使项目可作为魔搭社区 Gradio 创空间部署。文案生成、知识检索、事实核验、合规检查及图片读取继续复用现有 `agent/` 逻辑。

## 方案

- 新增 `app.py`，用 Gradio Blocks 实现产品型号、受众、场景、发布平台和补充要求输入，并呈现生成状态、文案、事实核验、合规结果和配图。
- 将原 Flask `/api/check`、`/api/generate`、`/api/revise` 与 `/api/image` 的用户操作映射到 Gradio 回调；后端直接调用现有 Agent，避免同一进程内再启动 Flask 服务。
- 继续使用 `agent/ima_client.py` 调用随仓库提供的 Node.js ima 客户端。通过创空间环境变量注入 Anthropic 与 ima 凭证，不将密钥写入代码或仓库。
- 新增 `requirements.txt`（含 Gradio、Python 后端依赖与 Node.js wheel）、带 Gradio 元数据的 `README.md`，以及中文部署说明（创空间 Secrets 名称、启动方式和凭证配置）。
- 项目只保留 Gradio 入口 `app.py`；移除旧 Flask 服务及其静态前端，避免维护两套界面。

## 运行与错误处理

- 启动时检查 `ANTHROPIC_API_KEY`、`IMA_CLIENT_ID`、`IMA_API_KEY` 是否已配置；缺失时在界面显示具体缺项，不显示密钥值。
- 将生成过程放入 Gradio 队列，避免并发调用耗尽共享服务额度；给用户显示阶段进度和可读错误。
- 对创空间写入的缓存使用可重建目录；生成结果作为 Gradio 输出返回，不依赖容器重启后仍保留本地文件。
- 默认只开放必要的 Gradio 交互。公开使用者共享部署者的上游额度；部署说明应提醒设置 Space Secrets，并注明额度与访问控制由上游服务及创空间设置决定。

## 部署文件

| 文件 | 用途 |
| --- | --- |
| `app.py` | Gradio 应用入口和界面回调 |
| `requirements.txt` | Python 运行依赖 |
| `requirements.txt` | 安装 Gradio、后端依赖与 Node.js 运行时，避免依赖未确认的系统包安装机制 |
| `README.md` | 创空间 YAML 元数据和项目部署说明 |
| `docs/deployment-modelscope.md` | 创建 Gradio 创空间、配置 Secrets、部署与常见故障说明 |

## 验收

- Gradio 应用可在本地启动并渲染主要输入与输出区域。
- 配置缺少凭证时，界面能提示所缺环境变量且不会泄露任何凭证。
- 配置凭证后，生成、修改、核验结果与图片输出沿用现有 Agent 语义。
- README 中的 Space 元数据指向 `app.py`，依赖清单覆盖 Python 与 Node 运行时。

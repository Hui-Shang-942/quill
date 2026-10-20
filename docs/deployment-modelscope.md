# 魔搭 Gradio 创空间部署说明

## 1. 创建创空间

在魔搭社区创建一个 **Gradio** 类型的创空间。应用入口为仓库根目录下的 `app.py`，SDK 版本为 `6.2.0`。

将 `quill-of-Huawei` 目录中的项目文件放到创空间仓库根目录，使目录结构如下：

```text
app.py
requirements.txt
README.md
agent/
vendor/ima-skill/ima_api.cjs
```

不要把外层 `华为PC全板块深度知识库_v7` 文件夹或密钥文件上传。应用通过 ima 服务检索知识库，不需要将知识库原始文件放入创空间仓库。

## 2. 配置创空间 Secrets

在创空间设置中添加以下 Secrets：

| 名称 | 用途 |
| --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic 模型 API 密钥 |
| `IMA_CLIENT_ID` | ima OpenAPI 客户端 ID |
| `IMA_API_KEY` | ima OpenAPI API 密钥 |

请只在创空间的 Secrets 设置中填写这些值，不要写入 `app.py`、`README.md`、`.env` 或提交记录。应用加载时只检查密钥是否存在，不会在界面显示密钥值。

可选的普通环境变量：

- `IMA_KB_NAME`：ima 知识库名称；未设置时使用代码中的默认值。
- `COPYWRITER_MODEL`：Anthropic 模型名；未设置时使用代码中的默认值。
- `COPYWRITER_EFFORT`：模型推理档位；未设置时使用 `medium`。

## 3. 启动与访问

配置 Secrets 后上传代码并启动创空间。`requirements.txt` 会安装 Gradio、项目 Python 依赖以及随 ima 客户端调用的 Node.js 运行时。启动后先点“检查连接”，确认知识库可访问，再试用文案生成与修改。

要让所有人访问，请将创空间可见性设为公开。公开访客共用创空间配置的 Anthropic 与 ima 凭证，因此所有生成请求会消耗部署者对应的 API 额度。需要限制访问时，请保持创空间为私有。

## 常见问题

- **页面提示缺少 Secrets**：检查 Secret 名称与上表完全一致，并确认重新启动了创空间。
- **提示 Node 可执行文件不存在**：确认 `requirements.txt` 中的 `nodejs-wheel==24.16.0` 安装完成后重新部署。
- **知识库连接失败**：核对 `IMA_CLIENT_ID`、`IMA_API_KEY`、`IMA_KB_NAME` 和网络访问权限。
- **模型调用失败**：确认 `ANTHROPIC_API_KEY` 有效，并检查该创空间运行环境能访问 Anthropic API。
- **知识库没有资料或出现冲突**：查看应用返回的具体提示；系统会在证据不足时停止生成，避免根据不完整资料编造产品信息。

运行缓存和导出文件位于创空间容器本地。容器重启后本地文件可能清理，需保留的报告请在生成后下载。

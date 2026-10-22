# 魔搭社区 Gradio 创空间部署

本文针对本项目当前的启动入口与依赖编写。部署前请确认你有可用的魔搭社区账号、ima 知识库访问凭证，以及 Anthropic Messages API 兼容服务的 API Key。

## 1. 创建创空间

1. 登录[魔搭社区](https://modelscope.cn/)，打开[创建创空间](https://modelscope.cn/studios/create)。
2. 选择 **Gradio** SDK。空间名称、可见性、硬件等按项目发布需要选择；本应用不在创空间本地加载大模型，默认先用 CPU 即可。
3. Gradio 版本选择 **6.2.0**，与项目 `requirements.txt` 和仓库根目录 `README.md` 中的 `sdk_version` 一致。
4. 将本项目内容放在空间仓库的根目录。不要多套一层项目文件夹。至少需要以下文件与目录：

   ```text
   README.md                 # 含 Gradio Space 元数据
   app.py                    # Gradio 启动入口
   requirements.txt          # Python 依赖
   UI-frontend-design/
     theme.css               # Gradio 前端主题样式
     hero.html               # 页面顶部内容路径说明
   agent/                    # 应用逻辑
     ima_api.cjs             # ima 知识库客户端
     ...
   ```

   `README.md` 文件开头的元数据应保留：

   ```yaml
   ---
   title: 华为 PC 营销文案助手
   sdk: gradio
   sdk_version: 6.2.0
   app_file: app.py
   ---
   ```

5. 使用 Git 推送到创空间仓库，或在创空间文件页面上传项目文件。`UI-frontend-design/` 下的 HTML 和 CSS 是 `app.py` 启动时读取的必需文件，需一并上传。不要上传 `.env`、`.cache/`、本地虚拟环境或 `outputs/` 运行产物。

## 2. 配置 Secrets

在创空间的 **设置** 中打开 **Secrets/密钥**，添加以下三个密钥。名称必须完全一致，应用启动后会检查它们是否存在：

| 名称 | 用途 |
| --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic Messages API 兼容服务的密钥；当前默认模型名为 `deepseek-flash` |
| `IMA_CLIENT_ID` | ima 知识库 API 的 Client ID |
| `IMA_API_KEY` | ima 知识库 API Key |

值应从对应服务的控制台获取。只在创空间设置中录入，不要写入 `README.md`、源码或提交到 Git。若创空间设置将普通变量与 Secrets 分开，请把这三个都添加为 Secrets。

如果你使用 DeepSeek 的 Anthropic 兼容接口，需要额外设置其 Base URL。Base URL 不是密钥，可在创空间 **Variables/环境变量** 中添加：

| 名称 | 值 |
| --- | --- |
| `ANTHROPIC_BASE_URL` | `https://api.deepseek.com/anthropic` |

该 URL 与项目 `.env.example` 中的本地开发配置一致。若使用其他兼容服务，按该服务提供方的文档填写 Base URL，并确认其支持 Anthropic Messages API。

应用还支持以下可选普通环境变量；未设置时使用右侧默认值：

| 名称 | 默认值 | 说明 |
| --- | --- | --- |
| `IMA_KB_NAME` | `任德耀新建华为PC知识库` | ima 知识库名称 |
| `COPYWRITER_MODEL` | `deepseek-flash` | 文案模型名称，应与配置的 API 服务匹配 |
| `COPYWRITER_EFFORT` | `medium` | 模型推理档位，可设为 `low`、`medium` 或 `high` |
| `COPYWRITER_MAX_OUTPUT_TOKENS` | `393216` | 应用允许的单次最大输出 token 数；服务端仍可能有更低限制 |

## 3. 构建与启动

提交或上传文件后，创空间会根据 `README.md` 的 Gradio 元数据启动 `app.py`，并安装 `requirements.txt` 中的依赖。依赖包含 `nodejs-wheel`，用于应用调用 `agent/ima_api.cjs`；不要删除该依赖或只上传 Python 文件。

入口脚本由本项目负责监听 `0.0.0.0:7860`。部署时无需再配置另一个启动命令或 Gradio 分享链接。构建期间可在创空间页面查看构建日志；启动失败时查看运行日志。

## 4. 部署后检查

1. 等待创空间状态变为运行中，打开应用页面。
2. 在界面点击 **检查连接**，确认应用可以访问配置的 ima 知识库。
3. 选择一个平台和场景，生成一份短任务文案，确认流程能够完成、页面显示结果，并能复制或导出最终内容。
4. 如修改代码或依赖，提交到创空间仓库后等待新一轮构建，再检查运行状态和日志。

## 5. 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 页面提示缺少 Secrets | 检查三个必需名称是否拼写正确、是否设置在当前创空间，以及值是否为空；修改后重启或重新部署空间 |
| 依赖安装失败 | 查看构建日志；确认 `requirements.txt` 位于仓库根目录，且未改动项目要求的依赖版本范围 |
| 找不到入口或模块 | 确认 `app.py` 在仓库根目录、README 的 `app_file` 为 `app.py`，并且整个 `agent/` 目录已上传 |
| ima 连接失败 | 确认 `IMA_CLIENT_ID`、`IMA_API_KEY` 有效，空间可访问外网，并且 `IMA_KB_NAME` 指向有权限访问的知识库 |
| 模型请求失败 | 确认 `ANTHROPIC_API_KEY` 有效、Base URL 与模型服务匹配，并检查模型服务额度、限流及创空间运行日志 |
| 更新后仍显示旧版本 | 确认文件已推送到当前空间所用分支，等待构建完成；再查看最新构建与运行日志 |

## 安全说明

- `.env` 仅用于本地运行，已由 `.gitignore` 排除；不要上传到创空间仓库。
- 凭证应通过创空间 Secrets 管理。不要将密钥写入代码、提交记录或日志。
- `.cache/` 可能包含知识库缓存，`outputs/` 是运行产物；按项目忽略规则，不应作为部署源码提交。

## 参考

- [魔搭社区创空间](https://modelscope.cn/studios/create)
- [魔搭创空间支持 Gradio 5 的公告](https://community.modelscope.cn/6731aa6182931a478c1c4171.html)
- [魔搭创空间部署技能说明](https://modelscope.cn/skills/modelscope/modelscope-studio)

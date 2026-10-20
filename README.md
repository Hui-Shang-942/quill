---
title: 华为 PC 营销文案助手
sdk: gradio
sdk_version: 6.2.0
app_file: app.py
---

# 华为 PC 营销文案助手

基于 ima 知识库生成和核验华为 PC 多平台营销文案。应用会检查产品事实、图片型号和合规要求，并支持按指令修改文案。

## 部署

请按[魔搭创空间部署说明](docs/deployment-modelscope.md)创建 Gradio 创空间并配置 Secrets。请将本项目目录作为仓库根目录上传，保证 `app.py`、`agent/` 与 `vendor/` 位于仓库根目录。

## 本地运行

安装 `requirements.txt` 中的依赖并配置所需环境变量后执行：

```bash
python app.py
```

本地 Flask 页面仍可通过 `python server.py` 启动。

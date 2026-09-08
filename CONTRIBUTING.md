# 参与开发

感谢你改进做菜助手。提交代码前，请先确认变更与项目用途相关，并避免提交个人配置、Cookie、数据库、日志或下载文件。

## 开发环境

- Python 3.12 或 3.13
- Windows 本地运行，或 Docker
- 安装依赖：`python -m pip install -r requirements.txt`

## 分支与提交

- 从 `main` 创建功能分支，例如 `feat/recipe-import`、`fix/api-error-response`。
- 使用 Conventional Commits：`feat`、`fix`、`docs`、`test`、`ci`、`refactor`、`chore`。
- 提交标题使用现在时态、简短描述，不在一个提交中混入无关格式化。
- 破坏兼容性的变更在标题后加 `!`，并在正文说明迁移方式，例如 `feat!: change recipe export schema`。

## 提交前检查

```powershell
python -m compileall app.py core.py knowledge.py
python -m unittest discover -s tests -v
python smoke_test.py
git diff --check
```

涉及 Docker 或部署文件时，还应本地构建镜像并确认 `/health` 返回 `{"ok":true}`。真实平台检索和语音转写需要外部服务，不应在测试中写入真实 Key。

## Pull Request

PR 描述应包括：变更目的、用户可见行为、测试命令及已知限制。新增接口或配置时同步更新 README、`config.example.json` 和 CHANGELOG。维护者会检查测试、错误处理、敏感信息和许可证要求。

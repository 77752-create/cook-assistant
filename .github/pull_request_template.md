## 变更说明

<!-- 说明为什么改、改了什么，以及用户能观察到的行为。 -->

## 验证

- [ ] `python -m compileall app.py core.py knowledge.py`
- [ ] `python -m unittest discover -s tests -v`
- [ ] `python smoke_test.py`
- [ ] `git diff --check`

## 检查清单

- [ ] 未提交 API Key、Cookie、数据库、日志或下载文件
- [ ] 新增接口、配置或行为已更新 README 和 CHANGELOG
- [ ] 错误响应没有泄露内部路径、凭据或上游原始响应
- [ ] 破坏性变更已写明迁移方式

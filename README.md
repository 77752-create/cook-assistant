# 做菜助手

把抖音或 B 站的做菜视频整理成可保存、可复制的菜谱：食材、步骤、关键技巧，以及每个关键操作背后的烹饪原理。

这是一个 **Python + Flask 后端应用**。GitHub 用来托管源代码；要让网站在公网持续运行，需要按本文部署到 Render 或自己的服务器。它不是 GitHub Pages 静态网站，不能直接部署到 GitHub Pages。

> 本项目适合个人或家庭分别部署一份实例。它没有多用户账户与菜谱隔离机制；不要把一个未设置 `APP_PASSWORD` 的实例公开分享给陌生人。

## 能做什么

- 按菜名搜索：优先返回抖音结果，并补充 B 站视频。
- 粘贴链接：支持抖音长链接、抖音分享短链接/文案、B 站链接和 BV 号。
- 提取文字：优先使用 B 站字幕、视频简介或抖音公开文稿；B 站缺少文字时可临时下载音频转写，临时文件完成后自动删除。
- 整理菜谱：生成食材分类、步骤、关键技巧和“为什么这样做”。配置文本 AI 后，整理效果更好；未配置时仍会使用本地规则整理。
- 保存与迁移：将菜谱保存到 SQLite 数据库，可查看、删除、复制 Markdown，以及备份/恢复 JSON。
- 多设备使用：在同一 Wi‑Fi 下让手机访问电脑；也可部署到云端，使用同一份云端菜谱数据。
- 手机桌面应用：浏览器可按 PWA 方式添加到手机主屏幕。

## 使用流程

1. 启动网站，浏览器打开 `http://127.0.0.1:8765`。
2. 在“搜索”输入菜名，或展开“直接粘贴抖音 / B 站视频链接”。
3. 在结果中点击“生成模板”。系统会提取可用的字幕、简介或公开文稿。
4. 提取完成后查看食材、步骤、关键技巧和“为什么”。点击“打开视频观看”可回到原视频核对细节。
5. 点击“保存到菜谱”；之后可在“菜谱”页随时打开、复制或删除。
6. 在“设置 → 菜谱数据”下载备份。换电脑或换云端时，将 JSON 粘贴到恢复框即可导入。

### 文字提取的边界

- 抖音只使用公开文字（AI 文稿或描述）。某条视频没有公开文字时，系统会提示你打开原视频；不会绕过平台限制下载抖音视频。
- B 站优先取字幕和可识别为菜谱的简介。若都没有，需要开启“允许临时下载转写”。
- 结果来自视频文字和规则/AI 整理，食材用量、火候与食品安全信息应以原视频和实际食材状态为准。

## 本地安装（Windows）

### 前提条件

- Python 3.12 或 3.13，并在安装时勾选“Add Python to PATH”。
- 网络连接。首次安装依赖、首次下载本地语音模型或检索视频可能耗时较长。

### 第一次运行

```powershell
git clone https://github.com/<你的用户名>/cook-assistant.git
cd cook-assistant
Copy-Item config.example.json config.json
py -m pip install -r requirements.txt
py app.py
```

随后打开 <http://127.0.0.1:8765>。也可以双击 `启动做菜助手.bat`；首次使用前仍需先执行一次上面的依赖安装命令，或双击 `安装依赖.bat`。

停止服务时，关闭启动窗口，或双击 `停止做菜助手.bat`。

### 手机访问同一台电脑

1. 让手机和电脑连接同一 Wi‑Fi。
2. 打开网站“设置”，复制“手机（同一 WiFi）”显示的地址。
3. 在手机浏览器打开该地址。
4. 若打不开，请将 Windows 网络设为“专用网络”，并在防火墙提示时允许 Python 通过专用网络。

电脑关机或关闭服务后，手机将无法访问本地实例。

## 配置 AI 与视频转写

代码库不会携带你的密钥、Cookie 或个人菜谱。请只在本机的 `config.json` 或部署平台的环境变量中配置，**绝不要提交 `config.json`**。

### 最简单的本地配置

从 `config.example.json` 复制为 `config.json` 后，按需填写：

| 配置项 | 用途 | 是否必需 |
| --- | --- | --- |
| `openai_api_key` | 文本 AI 整理的密钥 | 否 |
| `openai_base_url` | 文本 AI 的 OpenAI 兼容地址 | 使用第三方兼容服务时需要 |
| `llm_model` | 文本整理模型名 | 否 |
| `stt_api_key` | 云端音频转写服务的密钥 | 云端 B 站转写需要 |
| `stt_base_url` | 云端音频转写服务地址 | 非官方地址时需要 |
| `stt_model` | 转写模型名，默认 `gpt-4o-transcribe` | 否 |
| `douyin_cookie` | 仅供你自己的抖音访问状态使用 | 否 |

文本整理和音频转写是两项独立服务。比如可以用 DeepSeek 做文本整理，同时用支持 `gpt-4o-transcribe` 的服务做音频转写；不要把只支持文本聊天的 API 地址填作转写地址。

本地 B 站转写使用 `faster-whisper` 和本机模型，不需要 `stt_*` 配置，但首次准备模型会占用磁盘空间和时间。

“设置”页只提供不敏感的开关、访问密码和备份恢复；API Key 与 Cookie 不会显示在网页中，避免在浏览器里暴露凭据。

## Docker 与云端部署

Docker 镜像已经配置为云端模式：数据保存在 `/data/recipes.db`，B 站无字幕时通过远程转写 API 处理音频。

### 自己的服务器（推荐保留数据）

在项目根目录运行：

```bash
docker build -t cook-assistant .
docker volume create cook_data
docker run -d --name cook-assistant --restart unless-stopped -p 8765:8765 \
  -v cook_data:/data \
  -e APP_PASSWORD='请换成强密码' \
  -e OPENAI_API_KEY='文本整理密钥（可选）' \
  -e OPENAI_BASE_URL='文本 AI 兼容地址（可选）' \
  -e LLM_MODEL='gpt-4o-mini' \
  -e STT_API_KEY='音频转写密钥（需要云端转写时填写）' \
  -e STT_BASE_URL='https://api.openai.com/v1' \
  -e STT_MODEL='gpt-4o-transcribe' \
  cook-assistant
```

`APP_PASSWORD` 会对整个网站启用浏览器访问验证，用户名固定为 `cook`。公网部署务必设置它，并在服务器防火墙/安全组只开放需要的端口。不要把 API Key 放进 GitHub 仓库、Dockerfile 或截图。

### Render

1. 将本项目推送到你自己的 GitHub 仓库。
2. 在 Render 中选择 **New → Blueprint**，连接该仓库。仓库中的 `render.yaml` 会创建 Web Service。
3. 创建完成后，在该服务的 **Environment** 页面添加：
   - `APP_PASSWORD`（公网访问密码，强烈建议）
   - `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_MODEL`（可选，文本整理）
   - `STT_API_KEY`、`STT_BASE_URL`、`STT_MODEL`（云端 B 站转写需要）
4. 如果平台支持持久磁盘，将它挂载到 `/data`；否则重建实例后 SQLite 菜谱会丢失，请定期在“设置”导出备份。
5. 等部署完成，使用 Render 提供的网址访问。

免费实例可能休眠，首次唤醒会更慢。云端网络、平台规则以及抖音/B站页面结构发生变化时，搜索或提取功能也可能受影响。

## 发布到 GitHub

在本项目目录中执行以下命令。先在 GitHub 网站创建一个**空仓库**（不要勾选 README、`.gitignore` 或 License），再将其中的仓库地址替换进去：

```powershell
git init
git add .
git commit -m "feat: publish cook assistant"
git branch -M main
git remote add origin https://github.com/<你的用户名>/cook-assistant.git
git push -u origin main
```

发布前检查：

```powershell
git status --short
git check-ignore -v config.json recipes.db
git diff --cached --name-only
```

前两个命令应显示 `config.json` 和 `recipes.db` 被 `.gitignore` 忽略；最后一个命令的文件列表中不应包含它们，也不应包含日志或你的个人导出文件。提交前仍请人工检查暂存差异中没有真实密钥或 Cookie。若密钥曾经提交或发到任何公开位置，请立刻到对应服务商后台撤销并重新生成。

## 项目结构

```text
app.py                 Flask 路由、任务与 SQLite 菜谱接口
core.py                视频检索、文字提取、转写、菜谱整理
knowledge.py           烹饪原理知识库
static/                网页界面与 PWA 资源
config.example.json    安全配置模板
Dockerfile             容器构建文件
render.yaml            Render Blueprint
requirements.txt       Python 依赖
```

## 许可证

本项目采用 [MIT License](LICENSE)，允许使用、修改和分发；使用视频平台内容时仍应遵守对应平台的规则与版权要求。

## 验证与排错

```powershell
py -m compileall app.py core.py knowledge.py
py smoke_test.py
```

该冒烟测试不访问外部平台、不写入菜谱数据库。网络相关功能受平台、网络和密钥状态影响，不能保证每次都得到相同结果。

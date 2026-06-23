# LitKG Assistant 部署指南

将 LitKG Assistant 部署到 **Streamlit Community Cloud**，免费、所有人都能访问。

---

## 前置条件

1. **GitHub 账号** — 用于存放代码并连接 Streamlit Cloud
2. **OpenAI 兼容 API Key** — 用于 LLM 和 Embedding 调用
3. **Git** — 用于推送代码到 GitHub

---

## 步骤一：创建 GitHub 仓库

1. 打开 https://github.com/new
2. Repository name 填 `litkg-assistant`（或其他名字）
3. 选 **Public**（免费部署必须公开）
4. **不要**勾选 "Add a README file"、"Add .gitignore"、"Choose a license"
5. 点击 "Create repository"

---

## 步骤二：推送代码到 GitHub

在本地项目目录打开终端，执行：

```bash
cd litkg-assistant

# 初始化 Git（如果还没有）
git init
git checkout -b main

# 添加远程仓库（替换为你的 GitHub 仓库地址）
git remote add origin https://github.com/你的用户名/litkg-assistant.git

# 添加所有文件并提交
git add .
git commit -m "Initial commit: LitKG Assistant"

# 推送到 GitHub
git push -u origin main
```

> `.gitignore` 已配置，`.env`、`secrets.toml`、PDF 文件、数据库等**不会被提交**。

---

## 步骤三：连接 Streamlit Cloud

1. 打开 https://share.streamlit.io/
2. 用 GitHub 账号登录（点击 "Continue with GitHub"）
3. 点击右上角 **"New app"**
4. 选择刚推送的仓库、分支 `main`、入口文件 `app/main.py`
5. App URL 可自定义（如 `litkg-assistant.streamlit.app`）
6. 点击 **"Deploy!"**

---

## 步骤四：配置 Secrets（API Key）

部署后 App 会报错 "API Key 未配置"，因为还没设置密钥：

1. 在 Streamlit Cloud Dashboard 找到你的 App
2. 点击右侧 **⋮ → Settings → Secrets**
3. 填入以下内容：

```toml
LLM_API_KEY = "sk-你的真实API密钥"
LLM_BASE_URL = "https://api.openai.com/v1"
LLM_MODEL_NAME = "gpt-4o-mini"
```

4. 点击 **Save**，App 会自动重启并读取密钥。

---

## 步骤五：验证

打开你的 App 网址（如 `https://litkg-assistant.streamlit.app`）：

1. 侧边栏正常显示，统计数字为 0
2. 上传一篇 PDF 测试处理
3. 在智能问答和知识图谱页面验证功能正常

---

## 关于免费版限制

| 项目 | 免费额度 |
|------|---------|
| App 数量 | 1 个私有 + 无限公开 |
| 内存 | 1 GB RAM |
| CPU | 共享 |
| 存储 | **临时存储（重启清空）** |
| 休眠 | 长时间无访问后休眠 |

### 存储临时性的影响

- 用户上传的 PDF、ChromaDB 向量库、知识图谱数据在 App 重启后会清空
- 每次重启后相当于全新状态
- 适合场景：用户当场上传论文、当场查询分析

### 休眠唤醒

- App 长时间无人访问会自动休眠
- 下次有人访问时自动唤醒（首次加载稍慢，约 10-30 秒）

---

## 本地开发 vs 云端

| | 本地 | 云端 (Streamlit Cloud) |
|------|------|------|
| API Key | `.env` 文件 | `Secrets` 面板 |
| 数据持久化 | ✅ 本地硬盘 | ❌ 临时（重启清空） |
| 启动命令 | `streamlit run app/main.py` | 自动 |
| 访问方式 | `localhost:8501` | 公网 URL |

代码已适配双模式：
- `config/settings.py` 优先读 `st.secrets`，本地开发回退到 `.env`
- 启动时自动创建所需目录，不依赖预置数据

# 🌿 分支对话 AI 画布 (Branch Chat Canvas)

> 把一次 AI 对话变成一棵**可以持续分叉的树**：在无限画布上提问，AI 流式回答；
> **划选回答中的任意一句话**，一键长出一个独立子分支继续深挖，无限嵌套。

线性聊天窗口里，问题越聊越偏、思路汇不拢；这里每个想法都是画布上的一个节点，
哪条线索值得深入就分叉哪条，哪条不需要就整枝剪掉。

## 📥 直接下载（Windows，双击即用）

不需要安装任何环境，下载后双击运行，等 5~10 秒解包即可：

- **[GitHub Releases 下载 BranchChatCanvas.exe](https://github.com/z689004/branch-chat-canvas/releases/latest)**（约 28 MB）
- **[Gitee 发行版下载 BranchChatCanvas.exe](https://gitee.com/Zhi-JunLiu/branch-chat-canvas/releases/latest)**（国内访问更快）

不填 API Key 也能进演示模式先玩起来；数据全部存本地 `data/` 目录。
未签名程序可能被 Defender 误报，选「仍要运行」即可。

**三种用法，按需选择：**

| 运行方式 | 适合场景 | 依赖 |
|---|---|---|
| 🖥️ **桌面软件（.exe）** | 双击即用，无需安装 Python/Node，可拷给别人 | 无（[直接下载](https://github.com/z689004/branch-chat-canvas/releases/latest)，或 `build_exe.bat` 自行打包） |
| ⚡ **纯前端单文件**（`dist-web/index.html`） | 双击即用、发给别人、离线演示，数据存浏览器 | 无 |
| 🌐 **FastAPI 完整版** | 数据落盘、多画布管理、局域网/服务器共享 | Python 3.9+ / Node 18+（或 Docker） |

---

## ✨ 特性

- ✂️ **划词分叉** — 在 AI 回答里选中一段文字，弹出面板，点「精简 / 完整」立即创建子分支，自动连线
- 🌳 **无限嵌套** — 子分支的回答同样可以划词继续分叉，思路树随对话生长
- 🎛️ **两种上下文模式**（可随时切换）
  - **精简**：子分支只围绕选中的片段展开，干净聚焦
  - **完整**：继承父节点全部对话历史 + 选中片段，上下文连贯
- 🫧 **流式输出** — SSE 打字机效果，回答实时渲染 Markdown
- 🖱️ **画布操作** — 节点拖拽（连线跟随）、折叠/展开子树、删除（含子树）、重命名、一键整理布局
- 🫧 **桌面悬浮球** — 42px 应用图标球，始终置顶；左键直达快速对话，右键开菜单，自动贴边吸附
- 📌 **系统托盘驻留** — 主窗口最小化收进右下角托盘；左键托盘图标唤回主界面，右键菜单可开关悬浮球、退出软件
- 🪟 **快速对话小窗** — 独立置顶小窗，标题栏拖动移动、八方向自由缩放，位置与大小自动记忆
- 🗂️ **多画布** — 多个话题并行，互不干扰；画布可重命名、删除
- 📝 **笔记 / 收藏夹** — 划选对话、悬停消息、右键收藏节点（⭐）都能存进笔记（自动记录来源画布与节点），也支持手动记；面板带分类筛选与搜索，存本机刷新不丢
- 📤 **导出** — Markdown / Mermaid / 网页快照 HTML / JSON（可再导入还原）
- 🤖 **多模型** — 任何 OpenAI 兼容 API（DeepSeek / 豆包 / 通义 / 智谱 / OpenAI…）、本地 Ollama、无 Key 演示模式；页面右上角填 Key 即生效
- 💾 **数据自主** — 完整版存本地 JSON 文件；单文件版存浏览器 localStorage，不经过任何第三方

## 🚀 快速开始

### 方式一：桌面版 exe（Windows，双击即用，无需任何环境）

```bash
build_exe.bat          # 打包一次，产出 dist-exe\BranchChatCanvas.exe（约 19MB）
```

双击 `BranchChatCanvas.exe` → 等待 5~10 秒 → **打开独立应用窗口**（基于系统 WebView2 内核渲染，
不依赖也不打开浏览器，无控制台黑窗）。任务栏与窗口使用内置应用图标。

- 数据保存在 **exe 同级的 `data/` 目录**，整个文件夹拷走即可带着对话记录迁移
- 关闭应用窗口即退出程序
- 端口自动挑选空闲值（8765 起，被占用自动顺延），多开互不冲突
- 应用图标由 `tools/make_icon.py` 生成（可自行替换后重新打包）
- 调试：设置环境变量 `BCC_DEBUG=1` 可打开 DevTools

### 方式二：Docker

```bash
git clone https://github.com/<you>/branch-chat-canvas.git
cd branch-chat-canvas
docker compose up -d          # 打开 http://localhost:8000
```

### 方式三：一键脚本

```bash
# Windows
start.bat

# macOS / Linux
chmod +x start.sh && ./start.sh
```

脚本会自动安装依赖、构建前端（首次）并启动服务。

### 方式四：手动

```bash
# 1) 后端
pip install -r requirements.txt
python backend/main.py                # 默认 http://localhost:8000

# 2) 前端（首次构建一次即可；不构建则只有后端 API）
cd frontend
npm install
npm run build                         # 产物由后端自动托管
```

### 方式五：纯前端单文件（无需任何环境）

```bash
cd frontend
npm install
npm run build:web        # 产出 dist-web/index.html（单文件，约 1.7MB）
```

双击 `dist-web/index.html` 即可使用；也可以把这个文件发给任何人，
或扔到任意静态托管（GitHub Pages / OSS / Nginx）上。
> 注意：单文件版数据存浏览器 localStorage，清浏览器数据前请先导出备份。

## 🤖 接入大模型

默认**演示模式**（mock）：不需要任何 Key，返回模拟回答，完整交互流程与真实模型一致。

**方式 A：页面配置（推荐）** — 打开网页 → 右上角「🧪 演示模式」→
选「云端 API」→ 填 API 地址 / Key / 模型名 → 测试连接 → 保存，立即生效。

**方式 B：环境变量 / `.env`** — 复制 `.env.example` 为 `.env` 后填写：

```env
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=sk-xxxx
LLM_MODEL=deepseek-chat
```

| 服务 | BASE_URL | 模型示例 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 豆包（火山方舟） | `https://ark.cn-beijing.volces.com/api/v3` | 你的推理接入点 ID |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| 本地 Ollama | `http://localhost:11434`（`LLM_PROVIDER=ollama`） | `qwen2.5:7b` |

## 📖 怎么用

1. 打开网页，输入第一个问题 → 生成根节点卡片，AI 流式回答
2. 在 AI 回答中**划选一段文字**（≥4 字）→ 选区上方弹出面板
3. 点 **⚡ 精简** 或 **📚 完整** → 立即创建子分支并自动连线
4. 在子分支里继续追问；它的回答同样可以划词继续分叉
5. 节点操作：标题栏拖动卡片 · 悬停标题点 ✏️（或双击）重命名 ·
   `−` 折叠子树 · `⋮` 菜单（重命名 / 折叠 / 删除含子树）
6. 工具栏：切换/新建/重命名画布 · 整理布局 · 适应视图 · 小地图开关 · 清空画布 · 导出

`Esc` 取消选中并关闭划词面板。

## 🧩 上下文模式说明

| | 精简模式 | 完整模式 |
|---|---|---|
| 发给模型的上下文 | 系统提示 + 本节点选中片段 | 系统提示 + 祖先链全部对话 + 各级选中片段 |
| 适合 | 局部深挖、换角度重问 | 连续推演、需要前文连贯 |
| Token 消耗 | 低 | 随深度增长 |

## 📁 项目结构

```
branch-chat-canvas/
├── backend/              # FastAPI 后端
│   ├── main.py           #   路由 + SSE 流式 + 静态托管
│   ├── models.py         #   Pydantic 请求模型
│   ├── llm_client.py     #   大模型调用（openai 兼容 / ollama / mock）
│   ├── storage.py        #   JSON 文件存储（backend/data/）
│   ├── app_desktop.py    #   桌面版启动器（pywebview 独立窗口，自动选端口）
│   └── data/             #   运行时数据（不入库 git）
├── frontend/             # Vue3 + VueFlow + Element Plus + Pinia
│   └── src/
│       ├── App.vue       #   画布、工具栏、划选交互
│       ├── store/tree.js #   对话树状态（Pinia）
│       ├── components/ChatNode.vue
│       └── api/          #   backend.js（走后端）/ standalone.js（纯前端）
├── docs/                 # 设计文档
├── start.bat / start.sh  # 一键启动脚本
├── build_exe.bat         # 打包桌面版 exe（PyInstaller + pywebview）
├── tools/make_icon.py    # 生成应用图标 assets/icon.ico
├── Dockerfile / docker-compose.yml
└── .env.example          # 环境变量模板
```

## 🔌 API 一览（完整版）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/tree/create` | 创建画布（含根节点） |
| GET | `/api/tree/list` | 画布列表 |
| GET | `/api/tree/get` | 读取画布（含全部节点） |
| PUT | `/api/tree/update` | 画布重命名 |
| DELETE | `/api/tree/delete` | 删除画布 |
| POST | `/api/node/create-child` | 基于选中片段创建子节点 |
| PUT | `/api/node/update` | 更新节点（标题/坐标/折叠/上下文模式） |
| DELETE | `/api/node/delete` | 删除节点（含子树） |
| POST | `/api/node/send` | 提问（SSE 流式返回） |
| GET/POST | `/api/llm/config` | 读取/更新模型配置（Key 打码返回） |
| POST | `/api/llm/test` | 模型连通性测试 |
| GET | `/api/tree/export` | 导出 markdown / mermaid / json |

启动后可访问 `http://localhost:8000/docs` 查看交互式 API 文档。

## ❓ 常见问题

- **数据存在哪？会丢吗？**
  完整版：`backend/data/*.json`，每棵对话树一个文件；单文件版：浏览器 localStorage。
  两者都在本机，不经过第三方。
- **API Key 安全吗？**
  Key 只保存在你自己的机器上（`backend/data/llm_config.json` 或浏览器本地），
  界面上始终打码显示；请勿把 `data/` 目录或 `.env` 提交到仓库（.gitignore 已拦截）。
- **划选文字没反应？**
  划选需在 **AI 回答区域**进行，少于 4 个字不触发；移动卡片请改从卡片头部拖动。
- **npm 安装很慢 / 报 403？**
  换镜像：`npm install --registry=https://registry.npmmirror.com`
- **网页直连模型失败（Failed to fetch）？**
  部分 API 服务不允许浏览器跨域（CORS）直连。DeepSeek 官方端点已验证支持；
  其他服务请改用完整版（后端代理调用）。
- **exe 首次启动慢 / 被安全软件拦截？**
  单文件 exe 启动需解包 3~8 秒属正常；PyInstaller 未签名程序可能被 Defender 误报，
  选择“仍要运行”或加入白名单即可，也可改用源码方式启动。

## 🗺️ Roadmap

- [ ] 用户登录与多端同步
- [ ] 对话树只读分享链接
- [ ] 分支对比（同一问题多分支结果对照）
- [ ] 节点级模型覆盖（不同分支用不同模型）
- [ ] PNG 画布截图导出、JSON 导入恢复
- [ ] SQLite 存储后端

欢迎提 Issue / PR。

## 📋 更新日志

### v1.2.0 — 快速对话真正可用（2026-11-05）

**快速对话（悬浮球）**
- 删画布 / 删会话后不再卡在「对话树不存在」：打开面板或发消息时自动补回根会话，
  原画布保留不动，消息照常发出
- 支持划词建分支：选中 ≥4 字浮出「精简 / 完整」，生成后小窗直接切到该分支，
  顶部面包屑可「回到主会话」，下次展开仍停在分支上
- 修掉「文字选不中」：悬浮窗整体禁选 + 浏览器残留光标毒化拖选锚点，两处同时修
- 主画布里与快速对话共用的卡片带「⚡ 快速对话」徽标

**画布**
- 对话全部删完后出现「＋ 新建一个对话」入口，不再是一块空白
- 修复拖左 / 上边缩放时位置滞后半拍，八个方向拖动都逐帧跟手

**桌面**
- 悬浮球系统阴影收窄约 2/3，球边缘更干净

**工程**
- 新增 6 个自动化回归脚本（快速对话自愈、划选建分支、空画布、徽标、缩放与阴影探针）

### v1.1.2 — 设置不再丢失（2026-11-05）

- 修复主题、画布背景、自定义配色与笔记关掉软件就丢：桌面窗口此前跑在 WebView2
  隐私模式，关闭时会删掉整个浏览器数据目录；现固定到 `data/webview/` 保存
- 笔记与外观设置随 `data/` 文件夹一起迁移

### v1.1.1 — 笔记 / 收藏夹（2026-11-04）

- 新增独立笔记本子：对话摘录 + 手动备忘，攒提示词、知识点、结论
- 三种收藏入口：划选文字点「📝 收藏」（自动记录来源画布 / 节点 / 谁说的）、
  悬停消息点 📝 收藏整条、面板里直接手写
- 收藏节点（⭐）与笔记打通：右键「收藏节点」会把该节点对话快照存进笔记，
  重复收藏自动去重；取消星标自动移除对应笔记（手动编辑过的会保留）
- 右侧笔记面板：分类筛选（全部 / ⭐节点 / 📌摘录 / ✍️手动）、搜索、复制、
  编辑、删除、长文展开收起、清空全部；`Ctrl + J` 快捷开关
- 本地 localStorage 存储，刷新页面不丢；深浅色主题均适配
- 新增系统托盘驻留：主窗口最小化自动收进右下角托盘；左键托盘图标唤回主界面，
  右键菜单（打开主界面 / 显示悬浮球 / 退出软件）
- 修复：关闭主窗口后悬浮球与后台进程残留（现在会一起退出；球里「收起」不受影响）
- 修复：重复启动 / 点任务栏图标不再拉起第二个进程，改为唤起已运行实例的主界面；
  托盘改设置后主界面设置面板实时同步

### v1.1.0 — 悬浮速记与画布操作打磨（2026-11-04）

**桌面悬浮体验**
- 悬浮球改用应用图标外观，尺寸收敛到 42px，去掉黑色方块底
- 交互重排：左键直达快速对话，右键开菜单，点击窗口外自动收起
- 快速对话小窗支持标题栏拖动与**八方向自由缩放**（四边 + 四角），带最小尺寸保护
- 小窗位置与大小持久记忆，下次展开回到原处
- 拖动/缩放由后端跟随全局光标，光标移出小窗也不会中断

**画布操作**
- 左下角缩放百分比移至画布最底部，移除与其重叠的旧缩放控件
- 「清空」改为清空当前会话全部对话，只保留一个空白根会话（可撤销）
- 新增「删除画布」，二次确认即可，无需输入文字

**修复**
- 画布列表不再出现点不开的「未命名画布 (0)」（只认 `tree-*.json`）
- 悬浮速记改为后端记住绑定画布，不再每次启动多出一个空白画布

### v1.0.0 — 首个公开版本（2026-11-04）

划词分叉、无限嵌套、两种上下文模式、流式输出、多画布、多模型接入、
桌面 exe 打包、网页快照与 Markdown 导出。

## 📄 License

[MIT](LICENSE)

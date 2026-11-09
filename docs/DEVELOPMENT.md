# 开发、构建与发布

Python 3.12 为推荐开发版本。PDF 运行时依赖固定在 requirements.txt；打包额外依赖 requirements-build.txt。Mac 和 Windows 包必须分别在对应系统构建，不能用 Mac 的 PyInstaller 生成 Windows EXE。

## 核心测试

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

测试使用合成文档，覆盖页面顺序、裁剪坐标、局部文字替换、加密文件、撤销回滚和本机 API。可用的本机端口是集成测试必要条件。

## 构建 Mac

需要 Xcode Command Line Tools（Swift、codesign）和 Git。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
bash scripts/build_mac.sh
.venv/bin/python scripts/verify_packaged.py 'output/吉吉编辑软件.app/Contents/Resources/backend/jiji-engine'
```

脚本按 Python 运行架构生成 Apple Silicon 或 Intel 包，不生成 universal 包。可以通过 `JIJI_PYTHON` 指定 Python。构建物位于 `output/`，随包包含源码 ZIP 和依赖许可。源码按 `git ls-files` 清单打包，因此新文件应先加入 Git。

## 构建 Windows

需要 Windows x64、Python 3.12、.NET 10 SDK 和 Git。仅开发者需要这些构建工具，使用下载包无需另装运行时：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-build.txt
.venv\Scripts\python scripts\build_windows.py
.venv\Scripts\python scripts\verify_packaged.py output\JijiEditor-Windows-x64\JijiEditor.exe
.venv\Scripts\python scripts\verify_windows_native.py output\JijiEditor-Windows-x64\JijiEditor.exe
```

Windows 包由 `JijiEditor.exe`（WinForms + WebView2）和 `backend/jiji-engine.exe`（PDF 服务）组成。`--verify-native 输出目录` 在真实内嵌窗口验证裁剪、撤销、保存、取消保存与关闭保护，并生成截图；另验证显示异常时不依赖网页的应急导出通道。保存路径和取消选择由测试注入，未自动操作系统保存对话框。服务单独支持 `--no-browser`；原生窗口不调用外部浏览器。

Windows 使用 `dotnet publish --self-contained true -r win-x64` 携带完整 .NET/WindowsDesktop 运行环境。构建脚本从微软官网下载锁定版本的 WebView2 Fixed Runtime，核对 SHA-256 和微软 Authenticode 签名后完整打包到 `webview2/`，保留原始许可证。程序显式选择该目录，验证实际 CLR 和 WebView2 进程路径均位于应用目录，禁止退回机器上预装的运行时。

Windows 10 使用 Fixed Runtime 120 及以后版本需要 AppContainer 的读取/执行权限。ZIP 不保留 ACL，因此应用在用户解压后的本机目录设置相应权限，不启动安装程序，也不请求管理员提升。Fixed Runtime 不支持 UNC/网络共享目录。

发布测试从实际 ZIP 的中文及空格路径运行。`scripts/verify_windows_portable.ps1` 仅在一次性 Windows CI 环境使用：临时阻止包内程序访问非本机网络，设置无效的机器运行时搜索路径，再运行原生验证，结束时恢复防火墙状态。报告同时要求包内 CLR/WebView2 检查和编辑、保存、恢复检查通过。测试使用已安装开发工具的 Windows runner，依靠实际加载模块路径证明运行组件来自下载包；它不能替代所有 Windows 版本的实机兼容测试。

Fixed Runtime 不自动更新。发布维护时应从微软官方稳定版来源刷新锁定文件、下载校验值和许可，重新运行完整 Windows 验证后发布新版。

启动诊断按运行组件核验、权限、用户目录、后台启动/握手、WebView2 环境/窗口创建和首屏加载分别记录阶段。系统 build 使用 `RtlGetVersion`，补丁修订号读取 UBR；异常只记录类型、HRESULT 与内层 Win32 错误码，不序列化异常消息、堆栈、会话地址或文档路径。原生验证会注入不可用目录和包含私密字段的异常，核对目录检查、临时目录回退、内层错误保留及报告过滤。

v0.3.2 另生成只适用于 v0.3.1 的小型启动更新。`scripts/build_windows_startup_update.py` 接收旧版与新版完整解压目录，在 .NET 框架版本、依赖图、实际运行依赖文件和 Fixed Runtime 文件全部匹配后才生成更新 ZIP。发布流程下载并校验公开 v0.3.1 包，将更新实际覆盖到旧包，再运行完整原生验证。更新保留旧 backend、VERSION 与 Source.zip，新启动器源码命名为 Startup-update-Source.zip，因此编辑页版本仍为 0.3.1。该专用步骤仅在 VERSION 为 0.3.2 时运行。

现有自动化验证平台是 Windows Server 2022，不覆盖 Windows 10 1809 实机。没有目标机器的具体错误码前，不将通用初始化失败归因为某个 WebView2 版本，也不宣称诊断更新已修复所有旧系统启动问题。

## 浏览器与 Office 验证

浏览器测试需要 Node.js 和 Playwright。安装在项目内即可，不依赖任何特定人的电脑路径：

```sh
npm install --no-save playwright
npx playwright install chromium
node scripts/verify_ui.cjs
```

可用 `JIJI_CHROME` 指定现有 Chromium/Chrome，`JIJI_PYTHON` 指定 Python。

发布流程会把 Windows ZIP 解压到含中文和空格的目录，再验证其中的 EXE。打包浏览器验证可单独运行：

```sh
node scripts/verify_packaged_browser.cjs "解压目录/JijiEditor-Windows-x64/backend/jiji-engine.exe"
```

此项验证真实浏览器中的脚本与样式、示例文档、批量裁剪、整批撤销及 PDF 下载，并生成不含会话地址的结果和截图。它不代表覆盖所有用户电脑的浏览器关联或系统限制；独立窗口另有必须通过的真实 WebView2 验证。

Office 验证需要免费 LibreOffice，并安装测试依赖：

```sh
python -m pip install -r requirements-test.txt
python scripts/make_office_fixtures.py
python scripts/verify_office.py
```

结果保存于 `output/`，不提交到源代码仓库。Office 测试既应检查提取结果，也应检查生成的 PNG，避免字体导致中文不可见。

## 发布新版本

1. 更新 VERSION、网页关于信息和 docs/releases/latest.md。
2. 本地运行核心测试，提交并推送到 main。
3. 创建对应标签，例如 `git tag v0.1.1`，再 `git push origin v0.1.1`。
4. `.github/workflows/release.yml` 分别构建 Windows x64、macOS arm64、macOS x86_64，验证冻结程序并计算校验值。
5. 所有平台通过后才自动创建 Release 并上传包。构建失败时先修复，不将未通过的包宣称为可用。

手动运行该 workflow 只上传 Actions artifacts，不创建公开 Release。开源仓库使用标准 GitHub 托管 runner，无需自建 Windows 主机；不要将工作流改到付费 large/xlarge runner 而不检查费用。

## 项目结构

- `jiji/engine.py`：格式转换、页面坐标、文字编辑、快照回滚。
- `server.py`：只监听本机的 HTTP API 与静态界面。
- `web/`：中文页面编辑界面。
- `scripts/windows-native/`：Windows 原生编辑窗口、系统保存对话框和后台服务生命周期。
- `scripts/MacApp.swift`：Mac 原生 WebKit 窗口和保存对话框。
- `scripts/package_common.py`：按公开 Git 文件清单生成源码包并收集许可。
- `tests/`：合成文件与本机接口测试。

初版源码不包含自动保存、OCR 或完整 Office 编辑器；这些属于后续功能。请不要把页面裁剪作为安全脱敏。

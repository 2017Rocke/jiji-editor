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

需要 Windows x64、Python 3.12（带 tkinter）和 Git：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-build.txt
.venv\Scripts\python scripts\build_windows.py
.venv\Scripts\python scripts\verify_packaged.py output\JijiEditor-Windows-x64\JijiEditor.exe
.venv\Scripts\python scripts\verify_windows_launcher.py output\JijiEditor-Windows-x64\JijiEditor.exe
```

打包后的 EXE 有两种测试模式：`--no-browser` 用于验证 PDF 服务；`--verify-launcher` 用于验证随包 tkinter 启动窗口。常规双击自动打开默认浏览器。

## 浏览器与 Office 验证

浏览器测试需要 Node.js 和 Playwright。安装在项目内即可，不依赖任何特定人的电脑路径：

```sh
npm install --no-save playwright
npx playwright install chromium
node scripts/verify_ui.cjs
```

可用 `JIJI_CHROME` 指定现有 Chromium/Chrome，`JIJI_PYTHON` 指定 Python。

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
- `windows_launcher.py`：Windows 启动窗口和后台服务生命周期。
- `scripts/MacApp.swift`：Mac 原生 WebKit 窗口和保存对话框。
- `scripts/package_common.py`：按公开 Git 文件清单生成源码包并收集许可。
- `tests/`：合成文件与本机接口测试。

初版源码不包含自动保存、OCR 或完整 Office 编辑器；这些属于后续功能。请不要把页面裁剪作为安全脱敏。

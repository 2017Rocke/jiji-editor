# 第三方软件与参考资料

吉吉编辑软件的自有代码采用 GNU AGPL v3。完整条款见 LICENSE。

## 运行时依赖

- **PyMuPDF 1.26.7 / MuPDF**：Copyright Artifex Software, Inc.，GNU AGPL v3。项目：https://github.com/pymupdf/PyMuPDF 。使用包内自带的完整版权、许可和字体资料；未购买或依赖商业 Office 扩展。发布修改版本或提供网络服务时须遵守 AGPL 的对应源码要求。
- **Pillow 11.3.0**：HPND/PIL 许可。项目：https://github.com/python-pillow/Pillow 。许可保留在打包依赖元数据中。
- **Python 3.12**：Python Software Foundation License；分发包保留解释器所需文件。
- **Microsoft.Web.WebView2 1.0.2903.40**（Windows 独立窗口）：Microsoft 提供的 WinForms SDK 与原生加载组件。使用官方 NuGet 包：https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.2903.40 。Windows 分发包在 `licenses/Microsoft.Web.WebView2/` 原样保留该包的 `LICENSE.txt`（BSD 风格再分发条款）及 `NOTICE.txt`；SDK 与本项目自有代码各自遵循原许可。
- **Microsoft WebView2 Fixed Version Runtime**（Windows 随包显示组件）：从微软官方来源获取完整固定版本运行环境，构建时核对下载摘要和微软 Authenticode 签名。完整二进制随应用放置于 `webview2/`，无需安装 Edge 或系统 WebView2。遵循微软 WebView2 Runtime 许可，原始条款随包提供于 `licenses/`；来源、版本及下载摘要见 `DEPENDENCIES.json`。Fixed Runtime 随吉吉新版本更新，不使用 Evergreen 自动更新服务。官方下载、许可及隐私信息：https://developer.microsoft.com/microsoft-edge/webview2/ 、https://privacy.microsoft.com/privacystatement 。
- **.NET 10 / WindowsDesktop Runtime**（Windows 随包运行组件）：以 self-contained 形式分发微软官方运行时，使用者无需安装 .NET Framework 或系统 .NET。运行时许可及第三方声明随包保留于 `licenses/`，具体版本记录于 `DEPENDENCIES.json`。官方信息：https://dotnet.microsoft.com/download/dotnet/10.0 。
- **LibreOffice**（独立安装，可选）：MPL 2.0 等项目许可，https://github.com/LibreOffice/core 。通过独立进程调用，不包含于当前应用。用于 DOC/DOCX、XLS/XLSX、PPT/PPTX 与开放文档格式转换。软件内不提供付费转档服务。
- **PyInstaller**（仅打包）：GPL v2 带运行时/引导程序例外，https://github.com/pyinstaller/pyinstaller 。不改变应用的 AGPL 许可。

## 学习参考，未复制到运行时代码

- **PDF Arranger**：GPL v3 或更新版本。学习 `pdfarranger/core.py` 的页面编排、旋转与裁剪坐标模型；实现采用自己的 PyMuPDF 坐标变换。https://github.com/pdfarranger/pdfarranger
- **pdf-lib**：MIT。学习 `src/api/PDFPage.ts` 的 CropBox 与页面绘制 API；未作为运行时依赖。https://github.com/Hopding/pdf-lib
- **Stirling-PDF**：根目录以 MIT 为主，但当前 LICENSE 对 engine、proprietary、saas、desktop、cloud 等目录指向独立许可，不能将全仓库视为统一 MIT。仅参考产品功能组织，没有复制代码。https://github.com/Stirling-Tools/Stirling-PDF

调研日期：2026-10-10。上游原始摘录保留在开发者本机，不纳入公开仓库或应用包；公开调研文档保留出处链接。发布应用时请同时提供本项目完整对应源码、requirements.txt、构建脚本和许可文件；应用本身没有登录、订阅、遥测或水印逻辑。

## 依赖的对应源码

- PyMuPDF 1.26.7：https://github.com/pymupdf/PyMuPDF/tree/1.26.7
- MuPDF 1.26.12（PyMuPDF 1.26.7 所用内核）：https://github.com/ArtifexSoftware/mupdf/tree/1.26.12 。使用 `git clone --recursive --branch 1.26.12 https://github.com/ArtifexSoftware/mupdf.git` 获取源码与构建所需子模块；PyMuPDF 源码包含内核构建说明。
- Pillow 11.3.0：https://github.com/python-pillow/Pillow/tree/11.3.0
- Python 3.12：https://github.com/python/cpython/tree/3.12
- PyInstaller 6.16.0：https://github.com/pyinstaller/pyinstaller/tree/v6.16.0

发行包中 `Source.zip` 包含本项目对应源文件与构建脚本，`licenses/` 保留所分发依赖的许可，`DEPENDENCIES.json` 记录实际分发的解释器及依赖版本和对应上游源码地址。没有将 AGPL 依赖改成闭源许可。

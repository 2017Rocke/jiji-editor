# 第三方软件与参考资料

吉吉编辑软件 v0.1 的自有代码采用 GNU AGPL v3。完整条款见 LICENSE。

## 运行时依赖

- **PyMuPDF 1.26.7 / MuPDF**：Copyright Artifex Software, Inc.，GNU AGPL v3。项目：https://github.com/pymupdf/PyMuPDF 。使用包内自带的完整版权、许可和字体资料；未购买或依赖商业 Office 扩展。发布修改版本或提供网络服务时须遵守 AGPL 的对应源码要求。
- **Pillow 11.3.0**：HPND/PIL 许可。项目：https://github.com/python-pillow/Pillow 。许可保留在打包依赖元数据中。
- **Python 3.12**：Python Software Foundation License；分发包保留解释器所需文件。
- **LibreOffice**（独立安装，可选）：MPL 2.0 等项目许可，https://github.com/LibreOffice/core 。通过独立进程调用，不包含于当前应用。用于 DOC/DOCX、XLS/XLSX、PPT/PPTX 与开放文档格式转换。软件内不提供付费转档服务。
- **PyInstaller**（仅打包）：GPL v2 带运行时/引导程序例外，https://github.com/pyinstaller/pyinstaller 。不改变应用的 AGPL 许可。

## 学习参考，未复制到运行时代码

- **PDF Arranger**：GPL v3 或更新版本。学习 `pdfarranger/core.py` 的页面编排、旋转与裁剪坐标模型；实现采用自己的 PyMuPDF 坐标变换。https://github.com/pdfarranger/pdfarranger
- **pdf-lib**：MIT。学习 `src/api/PDFPage.ts` 的 CropBox 与页面绘制 API；未作为运行时依赖。https://github.com/Hopding/pdf-lib
- **Stirling-PDF**：根目录以 MIT 为主，但当前 LICENSE 对 engine、proprietary、saas、desktop、cloud 等目录指向独立许可，不能将全仓库视为统一 MIT。仅参考产品功能组织，没有复制代码。https://github.com/Stirling-Tools/Stirling-PDF

调研日期：2026-10-10。上游原始摘录保留在开发者本机，不纳入公开仓库或应用包；公开调研文档保留出处链接。发布应用时请同时提供本项目完整对应源码、requirements.txt、构建脚本和许可文件；应用本身没有登录、订阅、遥测或水印逻辑。

## 依赖的对应源码

- PyMuPDF 1.26.7：https://github.com/pymupdf/PyMuPDF/tree/1.26.7
- MuPDF：随 PyMuPDF 使用的具体版本可通过 `python -c "import pymupdf; print(pymupdf.version)"` 查询；官方源码 https://github.com/ArtifexSoftware/mupdf 。PyMuPDF 源码的构建说明会指定内核版本。
- Pillow 11.3.0：https://github.com/python-pillow/Pillow/tree/11.3.0
- Python 3.12：https://github.com/python/cpython/tree/3.12
- PyInstaller 6.16.0：https://github.com/pyinstaller/pyinstaller/tree/v6.16.0

发行包中 `Source.zip` 包含本项目对应源文件与构建脚本，`licenses/` 保留所分发依赖的许可。没有将 AGPL 依赖改成闭源许可。

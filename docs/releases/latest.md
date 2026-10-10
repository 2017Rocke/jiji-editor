吉吉编辑软件 v0.1.1：免费、本地运行的 PDF 工作台。

### 选择下载包

- Windows 10 / 11（64 位 Intel/AMD）：`Windows-x64.zip`，解压后运行 `JijiEditor.exe`。
- Mac Apple Silicon（M 系列）：`macOS-arm64.zip`。
- Mac Intel：`macOS-x86_64.zip`。

三种包都包含 Python 与 PDF 引擎，无需手动安装 Python。每个包附带项目源码、第三方许可；对应的 SHA-256 校验文件单独提供下载。

### 功能

PDF 裁剪、旋转、删页、排序、合并、提取；中文添加与横排文字局部替换；高亮、画笔、图片；撤销重做；无水印导出。图片/TXT 可直接转 PDF，Word/Excel/PPT 转换需要独立安装免费的 LibreOffice。

### 验证与限制

发布流程在每个对应系统运行核心测试，并启动打包后的程序验证预览、中文文字添加与 PDF 导出。Windows 另验证打包后的启动窗口。

未购买商业代码签名，Mac 未经 Apple 公证；Mac 目标 macOS 13+，旧系统尚需实机验证。不提供 OCR、任意段落重排或云同步；退出前请导出。Windows 版本使用默认浏览器显示编辑器。更详细的使用与安装说明见仓库 README。

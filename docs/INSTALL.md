# 在另一台电脑上使用

打开 [Releases 下载页](https://github.com/2017Rocke/jiji-editor/releases/latest)，展开 Assets，下载与你的系统和芯片对应的 ZIP。`Source code` 是开发源码，不是可直接使用的应用包。

## Windows

1. 下载名字包含 `Windows-x64.zip` 的文件，适用于常见的 64 位 Windows 10 / 11 电脑。
2. 右键解压全部文件。将完整文件夹放到你喜欢的位置。
3. 双击 `JijiEditor.exe`。启动窗口会自动打开默认浏览器中的吉吉编辑器。
4. 浏览器地址是 `127.0.0.1`，表示你自己的电脑；文档不会传到远程网站。
5. 导出 PDF 后，从吉吉启动窗口退出。不要单独移动 EXE 或删除 `_internal`。

这是免安装版，无需管理员权限或安装 Python。启动器依赖系统正常的浏览器关联。未购买商业代码签名，Windows 可能提示未知发布者；请核对仓库来源与 SHA-256 校验值。

## Mac

1. 苹果菜单 → 关于本机，查看芯片。M 系列选择 `macOS-arm64.zip`，Intel 选择 `macOS-x86_64.zip`。
2. 解压 ZIP，将“吉吉编辑软件.app”拖入“应用程序”。
3. 打开应用。Mac 版使用独立窗口，导出时出现系统保存对话框。

当前包未经 Apple 公证，macOS 可能阻止首次启动。只对你核实过来源的软件，按照系统“隐私与安全性”页面提供的安装选项处理；不要全局关闭 Gatekeeper 或系统安全功能。

## Word / Excel / PPT 转 PDF

两种系统都需要另外安装免费的 [LibreOffice](https://www.libreoffice.org/)。装好后重启吉吉。默认检测位置：

- Windows：`C:\Program Files\LibreOffice\program\soffice.exe`，也检测 32 位目录和 PATH。
- Mac：`/Applications/LibreOffice.app/Contents/MacOS/soffice`。
- 自定义位置：设置环境变量 `JIJI_SOFFICE`，然后重新打开吉吉。

没有 LibreOffice 时，PDF 编辑、合并、图片和 TXT 转 PDF 仍可使用。转换文档中用到的字体应在目标电脑上安装，否则排版和字体可能变化。

## 换电脑与更新

把原始文档或已导出的 PDF 复制到另一台电脑，再用当地的吉吉打开。未导出的编辑仅保存在当前进程内，不会自动同步到 GitHub。

更新时先导出并退出旧版，再下载新 ZIP。Windows 替换整个应用文件夹，Mac 替换应用；不要混用不同版本的依赖文件。

## 校验下载

每个发行包都有对应 `SHA256SUMS-*.txt`。Windows 可执行 `Get-FileHash 文件.zip -Algorithm SHA256`，Mac 可执行 `shasum -a 256 文件.zip`，将结果与公开校验值对比。

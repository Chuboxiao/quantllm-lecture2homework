# Mac 终端环境：安装前需要核对什么

状态：已在项目独立虚拟环境安装 Python 3.12.14、vnpy 4.4.0，并编译安装 vnpy_ctp 6.7.7.2。未启动交易图形界面；联网验收见项目状态。

## 源码声明

- `vnpy` 声明 Python >= 3.10、NumPy >= 2.2.3、TA-Lib >= 0.6.4，并依赖 PySide6、pyqtgraph 等。
- `vnpy_ctp` 声明 Python >= 3.10、vnpy >= 3.0.0，构建使用 meson-python、Meson、pybind11。
- `vnpy_ctastrategy` 当前声明 vnpy >= 4.4.0。

依据：[pyproject.toml](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/pyproject.toml#L1)、[pyproject.toml](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/pyproject.toml#L1)、[pyproject.toml](https://github.com/vnpy/vnpy_ctastrategy/blob/6ef76981624bf55b2ea978f8587f74d633aafc72/pyproject.toml#L1)。包声明不是本机已经安装成功的证据。

用户选择不配置完整界面，但正常安装 vnpy 可能会带上 Qt 依赖；这不代表程序会打开窗口。不要为了“无界面”盲目用 `--no-deps` 跳过必要依赖。

## Mac 构建差异

CTP 的 README 指出 Mac 需要源码编译及 Xcode C++ 工具。源码包含 `.framework` 动态库。当前文件位于 `vnpy_ctp/api/` 下，不能照搬旧教程里的 `api/libs/` 路径。

实际构建发现：原先学习用 6.7.11 绑定调用的函数参数及结构字段与附带的 Mac 6.7.7 SDK 不兼容。因此另行取得官方 6.7.7.2 标签（commit `fa199f70dac9e242c20e925c17e2241b877e694f`）的相关源码，校验 Git blob 后在 `build/vnpy_ctp_mac_6_7_7/` 编译；原始学习仓库保持不变。

构建使用 setuptools 和系统 Xcode C++ 编译器，以 `.framework` 链接；对 `exit()` 绑定添加释放 Python GIL 的保护，避免退出等待回调线程时互锁。旧 C++ 文件使用 GB18030 编码。来源与补丁见 [版本清单](../../reports/ctp-compat-source.json)、[补丁](../../reports/ctp-mac-compat.patch)、[构建脚本](../../scripts/build_ctp_mac.py)。

本地扩展的运行库路径指向上述 build 目录，不能单独移动或删除该目录；该 wheel 是本机开发产物，不是可直接分发的安装包。

依据：[README.md](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/README.md#L1)、[meson.build](https://github.com/vnpy/vnpy_ctp/blob/ad76250cf87cf5b03604336fde8c7489bdc0d0d7/meson.build#L1)。

## 路径与持久化

`vnpy.trader.utility` 在导入时确定 `TRADER_DIR`：当前目录已有 `.vntrader` 时用当前目录，否则可能用用户主目录。`MainEngine.__init__` 又会切换进该目录。

因此后续程序使用明确的项目配置路径，并在导入相关模块前确定运行目录；不能默认读写都发生在终端最初位置。底层 CTP 的会话文件也应固定在项目本地目录。

依据：[_get_trader_dir](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/utility.py#L38)、[MainEngine.__init__](https://github.com/vnpy/vnpy/blob/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09/vnpy/trader/engine.py#L86)。

关联：[Demo 准备](ctp-demo-plan.md)。

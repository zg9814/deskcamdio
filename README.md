# DeskCamdio v1.0.0rc2.post1

面向 Raspberry Pi Zero 2 W 的桌面 AI 与 GBA 掌机。架构级重写版本，
设计文档见 [`DEVELOPMENT_GUIDE.md`](./DEVELOPMENT_GUIDE.md)。

## 开发（Windows 承担模拟器与测试）

Windows下可直接双击仓库根目录的 `run-local.cmd` 启动480×480交互模拟器。
首次启动会由`uv`自动准备Python 3.13和项目依赖。

```powershell
uv sync            # 创建 .venv 并按 uv.lock 安装（自动获取 CPython 3.13）
uv run deskcamdio-device --version
uv run pytest --cov=deskcamdio --cov-branch --cov-fail-under=85

# 命令行启动方式（与双击 run-local.cmd 相同）
.\scripts\run_local.ps1

# 无窗口快速验证
.\scripts\run_local.ps1 -Headless -Frames 60
```

质量门槛：`ruff format` 零差异、`ruff check` 零错误、mypy 通过 core/services/platform、
分支覆盖率 ≥85%（core/services ≥90%）。

## rc2 状态

- 水族像素首页、双页桌面、四主题与全部应用统一视觉已完成；默认主题为水族蓝灰。
- Runtime 共享主题、惰性应用生命周期、TaskScope、BackendClient 关闭链路已完成。
- IMX708 Picamera2 三档完整配置、异步滤镜、真实最新缩略图与 worker 回收已完成。
- 触控去重、EC11、USB ALSA、Zipformer ONNX、GBA 热插拔手柄接口已完成。
- rc2 wheel、ARM64 sherpa-onnx、mGBA 与资源均由最终路径原子安装；失败不切换 release。
- 本地门禁与截图见 `work/screenshots/`；Pi 结果持续记录在 `work/v1.0-pi-report.md`。

正式 `v1.0.0` 标签仍需蓝牙音箱和 USB 手柄两项实机验收，本轮只发布 rc2。

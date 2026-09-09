# 无头服务运维

运行时可以安装为 systemd 服务，在 Jetson 上无人值守运行。服务与命令行程序使用相同的
TensorRT、GStreamer、ByteTrack、事件和遥测代码路径。

主服务有意不启用 systemd `PrivateTmp`。NVIDIA Argus 摄像头采集通过 `/tmp` 下由
宿主管理的端点通信；隔离临时目录会导致 `nvarguscamerasrc` 无法连接摄像头守护进程。
清理 spool 的服务不使用摄像头，因此仍保留临时目录隔离。

## 生命周期

```text
systemd 启动
  -> 启动器创建持久化会话目录
  -> 运行时打开输入源并报告 READY=1
  -> 每次收到真实帧都刷新 watchdog 进度
  -> 帧进度停止导致 watchdog 超时并重启
  -> SIGTERM 请求有序停止
  -> 采集、证据、视频、遥测和指标完成收尾
  -> 运行时报告 STOPPING=1 并正常退出
```

信号处理器只记录信号编号。主线程从定时队列等待中醒来，观察停止请求，并在正常 C++ 控制
流中清理资源，从而避免在异步信号上下文中调用锁、内存分配器、GStreamer 或文件 I/O。

## 安装

先构建 Jetson 运行时，再安装可执行文件和在目标设备构建的 TensorRT engine：

```bash
sudo apt-get update
sudo apt-get install -y logrotate

cmake -S . -B build-service \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGE_VISION_ENABLE_GSTREAMER=ON \
  -DEDGE_VISION_ENABLE_TENSORRT=ON
cmake --build build-service -j"$(nproc)"

sudo bash scripts/install_systemd_service.sh \
  --binary build-service/edge_vision_realtime_detect \
  --engine models/yolox_tiny_fp16.plan
```

安装器会创建非特权 `edge-vision` 账号，把文件安装到 `/opt/edge-vision`，将 engine
按原文件名复制到持久化状态目录，并把 `EDGE_VISION_ENGINE` 更新为本次显式传入的
engine。其他环境配置保持不变；重新传入 Nano engine 即可回退。在审查配置前，安装器
不会启动视频流水线。

编辑 `/etc/edge-vision/edge-vision.env`，然后启动服务：

```bash
sudo systemctl start edge-vision.service
sudo systemctl status edge-vision.service --no-pager
sudo systemctl enable --now edge-vision-prune.timer
```

默认配置选择 IMX219 传感器模式 4，以 1280x720/60 FPS 采集，并向应用交付 30 FPS。
RTSP 与文件输入使用同一启动器，分别设置 `EDGE_VISION_SOURCE=rtsp` 或
`EDGE_VISION_SOURCE=file` 及其必需路径变量。

### 可选事件证据配置

[事件配置片段](../../deploy/systemd/event-evidence.env.example)提供显式的穿线持续确认、
ROI 离区确认、x264 与重叠片段共享设置。先部署同版本程序及启动器，再将片段中的键合并到
既有环境文件；不要直接用片段覆盖完整环境文件，也不要追加重复键。未设置新变量时保持
旧行为，基础示例仍不启用警戒线。几何坐标需按实际场景核对。

这套配置只保留事件 JSONL、截图和片段，不开启全程标注录像；每条事件仍有独立记录和截图，
多个事件可以指向同一片段。程序保持 `--continuous`，不加入测试预览或固定帧数退出。
模型、检测/跟踪阈值、输入、功率、时钟与 systemd 安全隔离均不由该片段改变。
规则取舍和字段定义见[事件 Schema](../events/event_schema.md)，开发短测及质量限制见
[Tiny416 25W 事件链路记录](../benchmarks/tiny416_event_runtime_25w.md)。

更新运行程序前，保存原程序、启动器、环境文件及权限/属主，核对候选源码身份和二进制哈希。
仅在约定停服窗口内原子替换；应安排独立于交互终端的失败/超时恢复流程。
启动后核对实际进程参数、engine 哈希、`active/running`、`NRestarts=0` 和同一进程的两段
新增真实帧进度。发生异常则恢复原文件并重复健康核验，不因 `active` 或安装命令退出0就认定成功。
这项部署检查不等于重新完成事件质量、CSI 性能或60分钟持续运行验收。

## 持久化状态

```text
/var/lib/edge-vision/
  models/yolox_tiny_fp16.plan
  metrics/latest.json
  current -> spool/<session-id>
  spool/<session-id>/
    events.jsonl
    snapshots/
    clips/
```

每个进程代次写入独立会话。发布日志或证据不依赖网络；重启服务会创建新会话，不覆盖早期
证据。

`edge-vision-prune.timer` 会在会话早于 `EDGE_VISION_SPOOL_MAX_AGE_DAYS`，或总保留
数据超过 `EDGE_VISION_SPOOL_MAX_BYTES` 时删除最旧的非保护会话。当前会话始终受保护；
此外保护按目录时间排序最新的 `keep-latest` 个会话（默认1，可能与当前会话重合，
不保证额外保留一个已完成会话）。服务单代最长运行24小时，定期关闭活跃日志，让历史会话空间
逐步回收。该策略不是活跃会话的硬磁盘配额：当前会话和受保护会话仍可能超过配置字节数；
高频误报会持续产生截图和片段，应另行监测剩余空间，不能把5 GiB示例值当作磁盘占用硬上限。

## Watchdog 与停止

unit 使用 `Type=notify` 和 `WatchdogSec=30`。只有在 watchdog 间隔一半以内收到过
真实帧，才发送心跳。因此，一个已连接但不产生可解码帧的 RTSP socket 无法无限期维持
健康状态。

验证有序停止：

```bash
sudo systemctl stop edge-vision.service
sudo systemctl show edge-vision.service \
  -p Result -p ExecMainStatus -p ActiveState
cat /var/lib/edge-vision/metrics/latest.json
```

预期结果是 `Result=success`、`ExecMainStatus=0`，并且指标状态包含
`shutdown_requested: true` 与 `shutdown_signal: 15`。

让帧进度停止到超过 watchdog 间隔，然后检查以下字段以验证重启：

```bash
systemctl show edge-vision.service \
  -p NRestarts -p Result -p WatchdogTimestampMonotonic
```

## 日志

运行输出写入 `/var/log/edge-vision/runtime.log`。安装的 logrotate 策略每天或文件达到
20 MiB 时轮转，保留 7 个压缩代次。由于进程整个生命周期内都保持 stdout 打开，策略
使用 `copytruncate`。systemd 在启动非特权服务前以 root 身份打开追加目标，因此
logrotate 对该文件保持 root 权限。启动器对 stdout 和 stderr 使用行缓冲，使运维记录
无需等待用户态输出缓冲区填满即可见。

```bash
sudo logrotate -d /etc/logrotate.d/edge-vision
tail -n 100 /var/log/edge-vision/runtime.log
```

systemd 的启动、停止、watchdog 和退出状态消息仍可通过 journal 查看：

```bash
journalctl -u edge-vision.service --since today --no-pager
```

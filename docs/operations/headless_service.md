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
  --engine models/yolox_nano_fp16.plan
```

安装器会创建非特权 `edge-vision` 账号，把文件安装到 `/opt/edge-vision`，将 engine
复制到持久化状态目录，并启用服务与保留策略定时器。在审查配置前，它不会启动视频流水线。

编辑 `/etc/edge-vision/edge-vision.env`，然后启动服务：

```bash
sudo systemctl start edge-vision.service
sudo systemctl status edge-vision.service --no-pager
sudo systemctl enable --now edge-vision-prune.timer
```

默认配置选择 IMX219 传感器模式 4，以 1280x720/60 FPS 采集，并向应用交付 30 FPS。
RTSP 与文件输入使用同一启动器，分别设置 `EDGE_VISION_SOURCE=rtsp` 或
`EDGE_VISION_SOURCE=file` 及其必需路径变量。

## 持久化状态

```text
/var/lib/edge-vision/
  models/yolox_nano_fp16.plan
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
数据超过 `EDGE_VISION_SPOOL_MAX_BYTES` 时删除最旧的已完成会话。当前会话和最新一个
已完成会话受保护。服务单代最长运行 24 小时，定期关闭活跃日志，让完整会话的保留空间
始终有界。

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

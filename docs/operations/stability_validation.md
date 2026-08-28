# 稳定性与恢复验证

运行时按受监管服务进行验证，而不是只验证单条命令成功。基线持续运行建立稳态行为证据，
独立的进程与输入源故障注入则验证自动恢复。

## 健康模型

进程仍然存在，不足以证明视频服务健康。验证检查三个独立层次：

1. systemd 报告服务处于 active、running 和 ready。
2. 只有真实帧到达时，`WatchdogTimestampMonotonic` 才会推进。
3. 运行日志持续出现行缓冲帧记录。

采集器还会采样服务 PID、重启计数、进程内存、任务数、spool 大小、可用磁盘、功率、
GPU 利用率和温度。它不修改推理线程或其计时边界。

## 基线持续运行

采集前立即重启标准 720p/25W 服务，使运行代次窗口与持续运行采样窗口对齐，然后执行：

```bash
sudo systemctl restart edge-vision.service
sudo python3 scripts/collect_service_soak.py \
  --duration-seconds 3600 \
  --sample-interval-seconds 30 \
  --output-root reports/stability/raw
```

如果 SSH 会话可能断开，先完成 sudo 认证，只把采集器放到后台。日志第一行会记录运行目录：

```bash
sudo -v
sudo nohup python3 scripts/collect_service_soak.py \
  --duration-seconds 3600 \
  --sample-interval-seconds 30 \
  --output-root reports/stability/raw \
  > /tmp/edge-vision-soak-collector.log 2>&1 &
head -n 1 /tmp/edge-vision-soak-collector.log
```

命令会输出 `run_directory`。采集完成后，应尽快有序停止该代次，复制其原子发布的最终
指标，汇总运行结果，再恢复服务：

```bash
run_dir=reports/stability/raw/service_soak_TIMESTAMP_PID
sudo bash scripts/finalize_service_soak.sh --run-dir "$run_dir"
cat "$run_dir/report.md"
```

基线通过条件：覆盖请求时长；同一服务代次持续活跃；watchdog 与帧进度持续推进；温度和
磁盘保持在门限内；内存没有持续上升趋势；最终运行指标至少保持 25 FPS，稳态采集丢帧率
不超过 1%。最终指标还必须显示一次干净的 SIGTERM 停止。

如果延迟执行收尾，实时样本仍描述精确的请求窗口，而最终运行计数会覆盖更长的进程代次。
报告会估算并披露两个窗口，不会悄悄把它们当成同一段时间。

原始 `samples.jsonl` 和 `tegrastats.log` 保存在 Git 忽略的 `reports/` 目录。
审查后可以单独发布精简报告。

## 进程崩溃注入

进程测试只向主进程发送 SIGKILL。只有 systemd 创建新 PID 和新会话、`NRestarts`
递增、服务报告 ready，并且收到由新真实帧支撑的 watchdog 心跳后，测试才通过：

```bash
sudo python3 scripts/inject_service_crash.py \
  --output reports/stability/process_crash.json
```

该测试有意与基线持续运行分开，因为计划内故障会使“零重启”的基线条件失效。

## RTSP 输入中断

使用 H.264 MP4 回放，让中断可重复且不依赖外部摄像头服务器：

```bash
python3 scripts/inject_rtsp_outage.py \
  --video videos/session_h264.mp4 \
  --engine models/yolox_nano_fp16.plan \
  --binary build-stability/edge_vision_realtime_detect
```

测试脚本启动本地 RTSP 服务，在推理期间中断并重新启动，然后检查运行时汇总。只重新打开
socket 不算恢复；必须在真实解码帧到达后，`restart_successes`、`stream_generation`
和 `tracker_resets` 都发生推进，并且仍达到请求帧数。

## 证据边界

- 周期日志延迟是定期健康轨迹，不是所有帧的延迟分位数；最终运行时 JSON 提供完整的有界
  延迟窗口。
- 只比较内存起点和终点可能漏掉暂时峰值；报告同时给出最大内存和最小二乘稳态斜率。
- 一次持续运行只能为一种硬件、功率、输入源和配置组合提供证据，不能证明所有部署环境。

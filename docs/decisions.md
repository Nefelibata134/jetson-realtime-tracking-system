# 长期工程决策

本页汇总当前仍然有效的系统级取舍。实现细节、完整数据和复现命令留在链接的专题文档中。

## D001：使用原生 GStreamer 与 TensorRT C++ 主线

**Decision**

v1 及当前默认运行时直接使用 GStreamer、TensorRT C++ API 与 ByteTrack，不把 DeepStream
作为运行依赖。

**Reason**

目标设备的软件组合是 JetPack 6.2.1，而当时可用 DeepStream 版本的官方验证组合不同。
原生路径已经通过文件、CSI、RTSP、性能和恢复验证，组件边界也更可控。

**Rejected Alternative**

在兼容性证据不足时切换 DeepStream。它仍可作为未来单独 A/B，但不能阻塞稳定主线。

## D002：三种输入共享 `IFrameSource`

**Decision**

文件、IMX219 CSI 和 H.264 RTSP 通过统一帧接口进入同一检测、跟踪与事件链路。

**Reason**

确定性文件回放、板端实时采集和网络恢复测试需要复用相同下游行为，避免三套流水线漂移。

**Rejected Alternative**

不为每种输入复制检测或事件逻辑。USB UVC 只作为未来适配器，不改变核心接口。

## D003：有界输入队列采用 drop-oldest

**Decision**

采集快于处理时丢弃最旧待处理帧，并记录丢弃数、队列高水位和帧序缺口。

**Reason**

实时分析更关心当前画面；保留旧帧会形成不断增长的延迟。时间戳和序号允许跟踪器与指标
识别跳帧，而不是假设帧连续。

**Rejected Alternative**

不使用无界队列，也不让采集线程长期阻塞以换取处理每一帧。

## D004：重连使用流代次隔离状态

**Decision**

成功恢复真实帧后递增 `stream_generation`，重置 ByteTrack 与事件状态。

**Reason**

输入中断前后的目标身份和时间连续性不可保证；继续旧状态会产生跨流假轨迹、错误停留或
重复事件。

**Rejected Alternative**

不只依靠 PID、frame index 或 socket 连接状态判断同一视频代次。

## D005：有序证据与后台编码分离

**Decision**

JSONL 和截图在处理线程按事件顺序发布并独立计时；事件片段和标注视频由有界工作线程编码。

**Reason**

事件记录需要确定顺序和已验证路径，而视频编码工作量可能超过单帧预算。两类工作分离后，
主链路延迟与后台吞吐可以分别解释。

**Rejected Alternative**

不在主线程同步编码完整视频，也不使用无界后台任务掩盖持续过载。

## D006：systemd watchdog 由真实帧进度驱动

**Decision**

只有近期收到真实解码帧时才发送 watchdog 心跳；恢复验收还要求新 PID/会话和后续帧进度。

**Reason**

进程可以仍在运行，RTSP socket 也可以保持连接，但检测链路没有任何帧。监管必须覆盖真正
影响功能的卡死状态。

**Rejected Alternative**

不使用单纯进程存活、固定定时器或“连接成功”作为健康信号。

## D007：队列容量按场景定义，不设单一全局数字

**Decision**

持续服务默认输入容量为 2，以限制延迟；CAVIAR 文件转 RTSP 评估使用容量 8，仅用于吸收
每段进程启动时的 TensorRT 冷启动抖动。输出和片段队列独立配置。

**Reason**

服务关注长期新鲜度，有限评估还要求逐帧对齐标注。首轮 CAVIAR 容量 2 出现冷启动丢帧并
被判为无效轮次；容量 8 后正式帧为零丢失、零缺口，模型和阈值未改变。

**Rejected Alternative**

不把评估修复后的容量 8 直接推广到服务，也不把服务容量 2 强加给逐帧计分工具。

## D008：当前默认模型为 YOLOX-Tiny

**Decision**

systemd 服务默认使用 Tiny；Nano 保留为历史基线，S 保留为已验证候选。

**Reason**

Tiny 相对 Nano 改善了 MOT17 HOTA/IDF1/MOTA，并在同一 CAVIAR 开发规则下取得三者最高
F1 `53.33%`。S 虽能以 720p/30 FPS 运行并消除入口误报，但总 F1 为 `50.00%`，且未检出
停留事件。

**Rejected Alternative**

不因模型参数更多或局部事件更好就直接切换到 S，也不把 Nano 的历史性能矩阵改写成 Tiny
结果。

## D009：25W 是默认功率模式

**Decision**

25W 用于默认服务与主要基准；MAXN_SUPER 作为需要额外延迟余量时的显式选项。
`jetson_clocks` 只在需要固定频率的受控基准或明确诊断中使用；systemd 服务不自行切换
`nvpmodel` 或锁频。

**Reason**

Nano 和 S 在 25W 已达到目标帧率。S 的 MAXN_SUPER 只降低约 10.48% E2E P95，同时增加
约 4.50% 平均输入功率，且 FPS 仍受 30 FPS 输入上限约束。支持 MAXN_SUPER 说明该模式
可用，不等于持续服务必须牺牲 DVFS 的功耗和温度调节能力。

**Rejected Alternative**

不默认依赖 MAXN_SUPER 或全时锁频来满足当前单路 720p 目标。

## D010：外部事件评估先冻结后解锁

**Decision**

开发片段用于人工定义语义和比较候选；留出片段在规则、真值、阈值和匹配标准冻结且审核后
才允许运行。查看过预测的留出片段永久标记为已消费。

**Reason**

事件规则包含场景几何和时间语义。先看结果再改区域或阈值会把留出集变成开发集，失去独立
证据意义。

**Rejected Alternative**

不覆盖 Nano 的 CAVIAR FAIL，也不使用同四段视频为 Tiny/S 生成新的独立测试结论。

详细协议见 [`benchmarks/caviar_external_validation_protocol.md`](benchmarks/caviar_external_validation_protocol.md)，
当前结果与限制见
[`benchmarks/caviar_external_validation_results.md`](benchmarks/caviar_external_validation_results.md)。

## D011：冻结当前 Jetson 板级系统基线

**Decision**

当前已验证的 JetPack 6.2.1 / L4T 36.4.3 组合保持为板端基线。`apt update` 只用于刷新索引；
普通依赖安装必须先检查完整变更集。通用 `apt upgrade`、发行版升级、Jetson 平台包变更、
系统更新界面确认、OTA、刷机和启动链修改，只有在准确 Seeed 产品与载板身份已确认、存在
该产品支持的 BSP/OTA 路径、镜像已校验、备份与恢复方案齐备且用户明确批准时才可执行。
相同 JetPack/L4T 版本号不构成刷机包兼容证据；产品目标、BSP 构建和 artifact 哈希也必须
匹配，实验或环境预装镜像默认不属于恢复基线。
分区级备份、恢复与刷机默认使用版本匹配的实体 Ubuntu 主机；目标板配置和存储设备必须从
匹配 BSP 与实际设备确认，不能复制示例中的占位值。

**Reason**

Jetson BSP 使用与具体 SoM、载板和 L4T 版本匹配的设备树、overlay、bootloader 与功率配置；
当前系统还带有 Seeed 构建标识。本项目的 CSI、NVMe、CUDA/TensorRT、MAXN_SUPER 和 systemd
实测结论依赖这一组合。宽泛的 Ubuntu 或 NVIDIA 包升级可能改变多个层级，使已有设备结论
失效，甚至造成摄像头、启动或外设不可用。Seeed 官方流程同样要求先选择准确产品和 L4T
版本，并在刷机故障时核对 BSP、保存主机刷机日志与 UART 启动日志。

**Rejected Alternative**

不使用 `apt upgrade`、`apt full-upgrade`、`do-release-upgrade` 或更换软件源作为一般依赖安装
和排错手段，也不根据刷机指南标题、设备树显示名或镜像文件名猜测载板后直接刷写。

参考：Seeed [`指定产品 BSP 刷写流程`](https://wiki.seeedstudio.com/cn/flash/jetpack_to_selected_product/)、
[`Jetson 串口调试指南`](https://wiki.seeedstudio.com/cn/jetson_debug_guide/) 与
[`Seeed Jetson Develop Tool`](https://github.com/Seeed-Projects/Seeed-Jetson-DevelopTool)。

## D012：YOLO26s 通过独立张量契约进入检测器 A/B

**Decision**

候选固定使用 `640x640`、batch 1、one-to-many `[1,84,8400]` 导出。通过
`IProfiledDetector` 和统一工厂接入，独立实现 RGB/255 居中 letterbox、`cxcywh` 解码与
按类别 NMS。运行入口须显式选择候选并提供检测/跟踪阈值；默认 YOLOX-Tiny 保持不变。

**Reason**

YOLO26 的输入归一化、补边和输出布局与 YOLOX 不同。模型无关的上层链路需要一致结果与
计时接口，但不能共用不兼容的解码公式。显式阈值避免不同 confidence 分布被当作同一标尺。

**验证证据**

固定官方权重和主机重复 ONNX 导出见[资产契约](models/yolo26s.md)；
[`edge_vision_yolo26_check`](../apps/yolo26_check.cpp) 覆盖几何、颜色、NMS 与静态 shape。
目标 Jetson 已完成 TensorRT 编译、链接、FP16 engine 构建、零张量与合成灰图推理，
并验证原 Tiny 服务恢复及配置哈希不变，见[板端最小验证](benchmarks/yolo26s_jetson_smoke.md)。
这些证据不包含真实视频质量或完整流水线性能。候选评估入口要求显式阈值，并限于
development/calibration；新留出执行入口须在参数和新协议冻结后另行审核。

**Rejected Alternative**

不复用 YOLOX grid decode，不把 one-to-many 输出当作 NMS-free 结果，不根据文件名自动
选择解码器，也不在固定 A/B 证明质量与实时性同时改善前变更正式默认值。

## D013：YOLO26n 与 YOLO26s 共用参数化候选资产链

**Decision**

YOLO26n 和 YOLO26s 作为独立候选保留各自的官方权重哈希与机器可读元数据，并通过同一
获取脚本、导出实现和 `Yolo26Detector` 接口提供 one-to-many `[1,84,8400]` 评估路径。两者
均不改变默认 YOLOX-Tiny、systemd 或既有评估协议。

**Reason**

两个尺度使用相同的 YOLO26 输出契约和后处理语义。参数化共享链可避免复制实现，同时把
权重、导出工具版本、ONNX 哈希和目标 Jetson engine 哈希分别记录，便于复现实验和审计。

**验证证据**

YOLO26n 官方权重 SHA-256、主机导出工具链和输出契约见[YOLO26n 资产与导出契约](models/yolo26n.md)；
YOLO26s 的既有固定哈希和板端最小验证保持不变。主机确定性测试覆盖两种元数据与入口；
YOLO26n 的目标 Jetson engine、MOT17/CAVIAR development 和完整实时链路尚未验证。

**Rejected Alternative**

不为 YOLO26n 复制独立解码器或下载器，不把主机 ONNX 导出写成 Jetson 性能结论，也不在
固定 A/B 与完整实时证据完成前切换正式默认模型。

## D014：Tiny 输入尺寸候选先验证权重与基线等价

**Decision**

Tiny640 复用官方 Tiny 权重、原网络与既有 YOLOX Detector，先复现 416 并核验固定图像
原始输出/检测结果，再从权重真实导出 640。默认 Tiny416 保持不变。

**Reason**

输入分辨率可能影响远景人物召回，也会增加推理和后处理工作量。同文件名不能证明同权重，
静态 shape 修改不能替代完整网络导出。需要同条件 calibration 和对应尺寸完整流水线证据。

**验证证据**

83 层卷积参数和四帧原始输出/检测等价核验、两次 640 导出哈希一致性见
[资产契约](models/yolox_tiny_640.md)。质量门槛与固定 GT 高度诊断见
[输入尺寸对照协议](benchmarks/tiny_resolution_protocol.md)。主机证据不替代目标 FP16 或实时性验证。
目标 FP16 和首轮25W同阈值 calibration 已执行，见[对照结果](benchmarks/tiny_resolution_results.md)。
召回与整体 HOTA/IDF1/MOTA 改善，但 h<100 跟踪中断由75增至194，未通过扩大验证门槛；
保留该结果与旧超时轮次，停止扩大验证，不改变默认 Tiny416。

**Rejected Alternative**

不修改现有 ONNX shape 标签，不用其他尺寸的质量结果为部署尺寸背书，不用已消费 holdout
调参，不根据一次吞吐结果改变服务默认值。

## D015：输入尺寸开发验证独立区分质量与带事件实时性

**Decision**

保留D014对应25W同阈值质量FAIL；新的版本化开发协议允许在MAXN_SUPER锁频条件下独立
检查CSI720p/30可行性。性能比较须包含真实人物和三类事件证据，数值FPS达标不足以通过。
当前默认Tiny416、25W服务配置不变。未通过完整事件负载前，不扩大到CAVIAR或60分钟验证。

**Reason**

分辨率收益、轨迹稳定性和事件I/O负载衡量不同风险。输入构图可能使框底边中心无法到达
既定规则区域；零事件短测不能证明同步截图或后台片段编码负载下仍然实时。
连续性诊断须固定GT并保留共同覆盖、新增覆盖、丢失覆盖和全未覆盖，不筛选有利指标。

**验证证据**

[v2结果](benchmarks/tiny_resolution_development_v2_results.md)保留3600帧/模型的CSI数据及
帧完整性、事件缺失FAIL、状态恢复和同GT连续性复算。共同覆盖小目标中断74→92，
旧75→194门槛FAIL未改写。三类事件质量与最终60分钟稳定性仍未验证。

[带事件CSI复测](benchmarks/tiny_resolution_csi_event_retest.md)进一步记录4/5条事件和完整输出，
两组数值实时性达标；Tiny416仍无穿线、六轮规范动作未验证，OC3计数增加1。
保留Tiny640原始数值PASS，但不将其等同完整同负载A/B或事件F1验证，不据此扩大验证或改默认。

**Rejected Alternative**

不把MAXN_SUPER与25W结果混合，不用事后归一化覆盖旧FAIL，不以无事件的30FPS短测切换
默认engine，不为通过单轮测试修改事件锚点、几何或默认参数。

## D016：有界参数搜索与默认部署验收分离

**Decision**

Tiny640以独立v3协议进行有限calibration/development参数筛选。固定检测缓存只有在原
Tiny416/Tiny640八份MOT输出字节一致重放后才用于跟踪搜索；检测score和NMS保持缓存契约。
筛选无合格项时记录全部回退，不事后扩展网格或改变筛选标准。旧质量FAIL、实时性限制和
当前默认Tiny416保留；默认迁移需要最终配置的质量、对应尺寸性能与持续运行证据。

**Reason**

最高HOTA、最低误报和最少中断可能对应不同参数。降低覆盖也能减少绝对中断，因此必须
同时保留召回、匹配观测、FP、IDSW及同GT连续性诊断。主机重放只能支持跟踪质量分析，
不能证明Jetson GPU延迟、完整流水线事件I/O或功耗。

**验证证据**

[v3调参结果](benchmarks/tiny_resolution_tuning_v3_results.md)记录27组配置、135行整体与
逐序列结果、来源SHA及八份基线字节一致性；26组改动均有MOTA回退，未选出无回退候选。
新参数尚未完成板端重放、CAVIAR事件对照、新性能矩阵或60分钟稳定性验证。

上述为 v3 完成时的验证范围；后续[v4 四组开发对照](benchmarks/tiny_resolution_caviar_v4_results.md)
确认 16 份新板端 MOT 字节一致和 12 次完整 CAVIAR 回放，但三组 Tiny640 的穿线漏报增加、
停留漏报未减少、入口误报更多，并存在入口片段缺项。优先候选的聚合 F1 为 38.10%，
本轮 Tiny416 为 58.82%；开发结果不支持替换默认项。新 CSI 矩阵、独立外部验证和持续运行仍未完成。
同 GT 连续性证据中的覆盖损失与中断时长回退均保留，执行有效不能代替质量验收。

**Rejected Alternative**

不以开发集最高单项分数宣布全局最优，不用旧Nano性能表替换标题生成Tiny640结论，
不从主机重放推算TRT/E2E P95，不改写既有FAIL或重新消费holdout作为独立测试。

## D017：源分辨率归因使用同帧配对，不替代事件与部署验收

**Decision**

源清晰度假设以同一原片的原生720p/无损同源低清，分别配Tiny416/Tiny640形成固定四组。
预测前冻结事件参考、几何、匹配和参数，完整帧后计分；同时报告迟报、重复报警与身份/锚点
问题。顺序回放的质量、阶段耗时、整机任务遥测和CSI完整流水线性能分别陈述。

**Reason**

不同视频间的分数差同时包含场景、目标大小、遮挡和规则影响，不能单独归因于分辨率。
检测数增加不等于持续轨迹或及时事件；事件匹配不约束GT身份时，事件TP也不能证明身份连续。

**验证证据**

[v5同源开发结果](benchmarks/tiny_source_resolution_v5_results.md)完成12项25W原DVFS回放，
原生输入下两组F1均66.67%，低清下为66.67%/70.59%。640增加的同一次停留TP在两种输入
均出现，远景仍全部漏报，并有入区迟报、锚点抖动和缺口后停留重计时误报。未支持原生输入
有更大640收益，默认Tiny416、旧MOT/CAVIAR FAIL与独立部署验收边界保留。

**Rejected Alternative**

不把低清上采样当原生720p，不通过改容差挽救迟报，不由PNG回放FPS判断CSI通过或失败，
不以有观测但无稳定事件的结果证明升级完成。

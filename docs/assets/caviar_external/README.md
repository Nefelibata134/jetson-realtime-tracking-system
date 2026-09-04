# CAVIAR 外部验证截图

本目录中的四张截图由项目运行时从 CAVIAR Test Case Scenarios 视频生成，包含检测框、
事件 ROI、轨迹 ID 和事件类型叠加层。

| 文件 | 含义 |
| --- | --- |
| `entry-true-positive-startup.jpg` | 启动占用事件，匹配冻结真值 |
| `entry-false-positive.jpg` | 第 124 帧入口事件，未匹配冻结真值 |
| `entry-true-positive-crossing.jpg` | 后续进入事件，匹配冻结真值 |
| `browse2-unscored-roi-entry.jpg` | 停留序列中的 ROI 进入事件，不属于停留计分类型 |

源数据由 EC Funded CAVIAR project/IST 2001 37540 提供，数据页面标示为 CC BY-SA。
这些独立文档截图沿用相同署名与共享方式要求，文件本身未被仓库根许可证重新许可。

- 数据来源：<https://homepages.inf.ed.ac.uk/rbf/CAVIARDATA1/>
- 评估结果：[`caviar_external_validation_results.md`](../../benchmarks/caviar_external_validation_results.md)

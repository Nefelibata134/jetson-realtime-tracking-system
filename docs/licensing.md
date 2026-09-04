# 许可证与发布边界

## 当前项目与整体分发

Copyright (c) 2026 Nefelibata134

从许可证迁移提交开始，项目自有源码以及包含兼容第三方组件的整体项目分发按
`AGPL-3.0-only` 提供，完整条款见根目录 `LICENSE`。版权归相应贡献者所有。分发受覆盖的
源码或二进制时，必须满足 GNU AGPL v3 的相应源码提供、许可证与版权声明等义务；修改版
通过网络与用户交互时，还须按第 13 条向这些用户提供取得相应源码的机会。

第三方文件本身未被重新许可，其原始条款和版权声明继续保留。这种文件级许可保留不表示
整体组合程序不受 AGPL 发布条件约束。没有向项目许可证加入针对专有 SDK 的额外链接例外。

## 历史 MIT 授权

截至并包括提交 `d790926b0187d27b1f5f5607f1ef709c909eaf7f` 的项目版本在发布时采用
MIT License。已经依据该许可证取得的副本继续享有原授权；本次迁移不追溯撤销或缩减既有
权利。迁移提交及其后版本的整体项目分发采用 `AGPL-3.0-only`，同时保留第三方文件原许可。

需要重现历史许可状态时，应检出相应提交并以该提交中的 `LICENSE` 为准。

## 第三方边界

项目根许可证不替换第三方文件的原始许可；在整体分发的 AGPL 义务之外，还须保留并遵守
适用的第三方条款：

- `third_party/bytetrack/` 保留 ByteTrack 的 MIT 许可证与版权声明。
- YOLOX 模型和上游实现仍受 Apache-2.0 约束。
- Ultralytics YOLO26n 与 YOLO26s 权重及其上游工具按 AGPL-3.0 或 Enterprise License
  提供；本项目选择 AGPL-3.0 路线，权重只在仓库外获取，第三方文件本身未被重新许可。
- GStreamer、OpenCV、Eigen、nlohmann/json 和 TrackEval 保留各自许可证。
- CAVIAR 派生截图作为独立文档资产保留原始 CC BY-SA 署名与共享方式要求，见
  [截图许可说明](assets/caviar_external/README.md)。
- CUDA 与 TensorRT 是目标系统独立提供的 NVIDIA SDK/运行库，不纳入项目源码，也不随
  本仓库分发。

逐项来源、固定版本和保留的许可证位置见 `THIRD_PARTY_NOTICES.md`。

## 模型、数据与生成物

仓库只保存来源元数据、校验和、构建脚本和评估协议，不保存以下内容：

- `.pt`、`.pth`、`.weights` 等模型权重；
- ONNX、TensorRT plan/engine 或其他生成的推理二进制；
- MOT17、CAVIAR 等数据集、原视频和人工标注原件；
- 凭据、私有地址、token 或运行输出。

模型权重必须从记录的官方来源获取并验证 SHA-256。ONNX 导出必须记录工具版本、导出参数
和生成文件哈希；TensorRT engine 必须在目标 Jetson 上构建并记录 GPU、JetPack、CUDA、
TensorRT、profile、精度和 engine SHA-256。

## 发布检查

当前公开发布范围是源码、配置、测试、文档和不含受限资产的脚本。发布包含项目二进制、
容器镜像或第三方运行库前，必须重新审计实际组合的许可兼容性、分发权限和相应源码提供
方式。CUDA/TensorRT 等外部专有 SDK 和运行库不随本仓库分发；不得将其视为已由项目 AGPL
重新许可，也不得将当前源码发布解释为二进制或捆绑分发授权。

许可证合规结论以实际发布内容为边界；新增第三方源码、模型、数据或打包方式时必须重新
执行审计并更新第三方声明。

条款依据见 [GNU AGPL v3](https://www.gnu.org/licenses/agpl.en.html) 与
[GNU 许可证兼容性说明](https://www.gnu.org/licenses/license-compatibility.en.html)。

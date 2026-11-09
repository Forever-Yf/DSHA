# DSHA Fork：真实 DSH 0.2.2-rc.1 预发布

[下载 APK](https://github.com/Forever-Yf/DSHA/releases/download/v0.2.2-rc.1-fork.1/dsha-0.2.2-rc.1-fork.1-arm64.apk) · [Release 与校验文件](https://github.com/Forever-Yf/DSHA/releases/tag/v0.2.2-rc.1-fork.1)

这是实际编译与独立签名的 Fork APK，不是旧版镜像。主运行时为 **DSH 0.2.2-rc.1**，应用版本为 `0.2.2-rc.1-fork.1-dsh0.2.2-rc.1`，versionCode 191。

## 安装边界
- Android 11 / API 30 及以上，ARM64，标准版。本次没有发布 Low 版。
- 独立包名 `io.github.foreveryf.dsha`，可与原版共存；不是原版覆盖更新，不自动读取旧 App 数据。
- 保留原版和备份，先配置新环境。未声明已验证旧完整备份跨版本恢复。
- 主运行时已升级；独立救援胶囊保留固定 0.2.1 版本和它自己的配方。

## 已执行验证
- 49 条新版本补丁，包含拆分后的工具执行管线安全检查。
- 真实 Web 认证与 8 个内置插件启动；拒绝未授权和错误令牌。
- 20 项 native/PTC 管线和 JSON 存储回归；工具是内存夹具，不执行真实设备命令。
- 选定 Java 单元测试 **63 项**，失败、错误、跳过均为零；覆盖真实补丁链幂等/恢复、设备命令策略、凭据、备份与运行时描述。
- Chromium 手机尺寸界面初始化：集成 ready，移动界面存在，无页面错误。
- APK 中真实 ARM64 Node **v24.19.0** 与 DSH CLI 在 QEMU 中执行，返回 0.2.2-rc.1。
- 最终 APK 摘要、独立包名、ABI、不可调试标志、v1/v2/v3 签名与 ZIP 16 KiB 对齐。

**未执行：** 真机 Android/proot/OEM 长时运行、无障碍/ADB/Root 操作、付费模型对话、旧完整备份的跨版本恢复。本次是有软件验收证据的预发布，不宣称所有历史回归或完整设备矩阵通过。

## 精确交付
- APK：423065520 字节
- APK SHA-256：`ee2443c2373c17ff7c7fcd6b8842ba55ba8d87fe2dfd26deb8323dce53f264d0`
- 主运行时 SHA-256：`b4a0b1fab0f21082626f0d8d4e9556d882946988a03aca4d0f6c0f98930ff11f`
- 编译源码：`8e82330a6c9531ce3f914cfd8aa87c6f81ca56b4`
- [实际构建与测试](https://github.com/Forever-Yf/DSHA/actions/runs/42569235432)
- [实际签名与发布](https://github.com/Forever-Yf/DSHA/actions/runs/42571027556)
- Release 附带匹配源码和机器可读验收报告；源码包不含大型离线输入，重建由工作流恢复固定 SHA-256 的上游原始输入，再依 npm 锁生成真实运行时。

## 签名维护
Fork 的公开证书身份在 [ci/fork-release-identity.json](ci/fork-release-identity.json)。原上游 E7E3 密钥没有使用，也不能冒充原版签名。

私钥备份用随机 AES 密钥与 HMAC 认证加密，再以仅属于用户的 RSA 公钥封装。加密备份位于发布运行的 `fork-signing-key-ENCRYPTED-owner-backup` artifact；解密私钥通过对话私有附件交付，**不在仓库中**。请保存两者；artifact 不应作为永久备份。

本地恢复工具：[tools/restore-fork-signing-backup.py](tools/restore-fork-signing-backup.py)。恢复后为后续发布配置 Actions Secrets：`DSHA_FORK_KEYSTORE_BASE64`、`DSHA_FORK_KEYSTORE_PASSWORD`。脚本会核对现有证书，缺失原 Fork 密钥时拒绝重新生成，避免后续 APK 无法覆盖更新。

下方上游 README 和历史文档保留原始记录，不代表这个 Fork 仍内置 0.2.1，也不代表本 Fork 获得了原版签名或历史真机验收。

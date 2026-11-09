# 当前状态：0.2.2 Fork APK 已实际发布

[下载、验收与签名说明](../../FORK.md) · [Release](https://github.com/Forever-Yf/DSHA/releases/tag/v0.2.2-rc.1-fork.1)

原 17 项迁移阻塞已完成移植或上游等效适配，当前为 49 条启用补丁，并通过真实构建与选定回归。下面保留第一轮审查记录，**不是当前未完成状态**。

---

# 将 DSHA 的内置 DSH 升级到 0.2.2-rc.1：兼容性验收记录

> 状态：**迁移中，未完成**（2026-11-09）。这不是可安装的新版 APK，也不改变生产 `0.2.1-rc.2` 依赖、Android 版本常量、签名或用户数据。

## 来源与目标

- DSHA 基线：Fork 自 `DSH-APP/DSHA`，`main` 初始 SHA `635f2fe54f1342fc6ecc78dcf2ff94b52e1ce424`。
- 上游源码：https://github.com/deepseek-ai/deepseek-harness/tree/dsh-v0.2.2-rc.1
- 上游发布说明：https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.1 （2026-11-04）。
- npm 核心包：`@deepseek-ai/dsh@0.2.2-rc.1`。
- 新上游最低 Node.js **24.9**；其 monorepo 使用 pnpm **11.28.5**。DSHA 的受管 pnpm 工具与 Node/Ubuntu 输入是独立合同，不能不经校验就同步替换。
- 测试分支：`upgrade/dsh-0.2.2-rc.1`。Fork 的 `main` 保持原有 DSH 版本与所有发布资产定义。

## 第一轮实际执行的检查

通过 GitHub Actions 在 Ubuntu 24.04 上使用 Node 24，按照 Linux / arm64 / glibc 平台条件，以 `--ignore-scripts` 生成候选 `package-lock.json` 并执行 `npm ci`。实际运行 DSH CLI 的 `--version` 返回 `0.2.2-rc.1`。随后将 `app/src/main/assets/runtime-patches.json` 中 48 条启用的精确源码补丁逐项与 npm 安装后的发布 JS 比对。

第一次审查输出：

| 分类 | 数量 |
| --- | ---: |
| 可按旧锚点应用 | 31 |
| 锚点失配 | 12 |
| 旧源码 SHA 不再匹配 | 4 |
| 对应模块缺失 | 1 |
| 合计明确阻塞 | 17 |

此外，注册表里的 **5 个 specialized 入口**仍需人工审查；不能把 31 个补丁匹配成功等同于 Android 功能测试成功。


### 17 项已定位的阻塞

下面是首轮 npm 安装树检查到的准确路径；“SHA 变化”只代表必须重新核实安全语义，不能反推功能一定失效。

| 范围 | 具体补丁 | 原因 |
| --- | --- | --- |
| 工具/安全 | `tool-dispatch-validation-patch.json` | 源码 SHA 变化 |
| 工具/安全 | `tool-messages-history-patch.json` | 源码 SHA 变化 |
| 工具/安全 | `tool-stream-identity-patch.json` | 源码 SHA 变化 |
| 工具/安全 | `guard-tools-patch.json` | 锚点失配 |
| 插件/策略 | `plugin-bundle-proof-workers-patch.json` | 锚点失配 |
| 插件/配置 | `config-editor-lock-order-patch.json` | 锚点失配 |
| 插件/配置 | `plugin-manager-pending-patch.json`、`plugin-inventory-entries-patch.json` | 锚点失配 |
| 插件/配置 | `retired-market-optional-patch.json`、`file-upload-resolver-lifecycle-patch.json` | 锚点失配 |
| 会话/界面 | `composer-enter-patch.json`、`sidebar-layout-recovery-patch.json`、`session-interaction-patch.json` | 锚点失配 |
| 会话/界面 | `tool-history-display-patch.json` | 源码 SHA 变化 |
| 网页/缓存 | `frontend-static-cache-patch.json`、`tooltip-entry-patch.json` | 锚点失配 |
| 网页/缓存 | `tooltip-interaction-patch.json` | 旧编译资源文件不存在 |

实际新发布 JS 已出现静态资源 ETag/304 实现，且旧实验性市场包名已不在同一宿主模块中；相应补丁可以评估上游替代方案，但不得仅凭关键词存在就删除旧配方。工具执行默认拒绝、插件签名/证明校验必须保留等效保护。


- 执行记录：https://github.com/Forever-Yf/DSHA/actions/runs/42560586087
- CI 产物包含隔离的 npm lock 和机器可读的 JSON 报告。
- 脚本：`tools/audit-dsh-upgrade.py`；工作流：`.github/workflows/dsh-022-audit.yml`。
- **限制**：仅对比编译发布 JS 的文本锚点。没有执行 48 个补丁后的端到端 DSH 对话；没有验证 SDK、协议、Android 设备桥、数据迁移、发布 APK、签名或真实手机。

## 在本地复现审查

需要 Node >= 24.9 和 npm 11；下列命令只在忽略的构建目录安装候选包：

    mkdir -p app/build/dsh-upgrade-candidate
    cp tools/dsh-upgrade-candidate/package.json app/build/dsh-upgrade-candidate/package.json
    npm install --package-lock-only --ignore-scripts --no-audit --no-fund \
      --os=linux --cpu=arm64 --libc=glibc --prefix app/build/dsh-upgrade-candidate
    npm ci --ignore-scripts --no-audit --no-fund \
      --os=linux --cpu=arm64 --libc=glibc --prefix app/build/dsh-upgrade-candidate
    python3 tools/audit-dsh-upgrade.py \
      --install app/build/dsh-upgrade-candidate \
      --output app/build/dsh-upgrade-candidate/compatibility-audit.json

脚本出现阻塞时以退出码 2 终止，`compatibility-audit.json` 仍会写出。审查出现阻塞时，GitHub Actions 工作流会失败；artifact 上传步骤仍用 `if: always()` 保存报告，**不能把报告上传成功理解为兼容性通过**。

## 在更新生产代码之前必须完成

1. 对明确不兼容的补丁，核对上游功能是否已经实现同等行为；如没有，则移植补丁并重新锁定源码锚点及相应单测。不能仅把每个 recipe 的 `dshVersion` 替换成 `0.2.2-rc.1`，更不能禁用安全拦截补丁以绕过错误。
2. 检查 5 个 specialized 适配入口、构建器特判模块与新上游导出；修复弃用的导入和会话/投影 API，确保 DSHA 原生插件能加载。
3. 对新的最小 Node 版本、受管 pnpm、glibc arm64 原生依赖、插件更新的生命周期脚本进行运行时校验，不能把 npm 安装成功等同于容器启动成功。
4. 在精确适配后重新生成生产 `tools/dsh-runtime/package-lock.json`、`dsh-runtime.bin` 和 `*.inputs.json`，同步 `runtime-patches.json`、Android `Constants.DSH_VERSION`、Gradle 版本、runtime descriptor、notice/锁定来源。严格执行 `verifyBundledDshVersion`。
5. 独立验证旧 `0.2.1-rc.2` 会话、设置和插件在新 reader 中的兼容读写；只有通过真实格式测试，才能把新版本纳入 `READ_COMPATIBILITY`。首先做好真实备份，避免旧格式被未知迁移破坏。
6. 准备构建所需的原始离线输入（仓库说明中的大型 ZIP / rootfs / recovery 资产），运行 Standard/Low 单测、Release lint、正式签名 APK 和覆盖安装验证。没有 E7E3 历史证书不能签同签名覆盖安装包；**不要声称已验证手机或发布更新**。

## 不可跳过的保护

- 保留 Ubuntu base 身份，升级 DSH 不自动清除用户目录、不改签名、不覆盖用户私有工作区。
- 继续对不认识的设备 shell 命令默认拒绝；安全护栏失效时必须阻断升级。
- 使用隔离构建路径，不在生产运行时上直接执行不可信 npm 脚本。
- 未通过审查前不改动 `main`、不标注 Release、不给 APK 起正式版本文件名。

**验收门槛**：精确补丁/来源检查零阻塞、实际新运行时通过测试、数据兼容/回滚有实证、Android 构建与签名通过后，才能讨论正式升级合并。

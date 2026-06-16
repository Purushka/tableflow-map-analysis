# RGSSA Catalog Tool — 打包与使用说明

## 一、打包成 exe（开发者操作）

在 `desktop_app_v2` 目录下，**双击 `build.bat`** 即可。

或命令行：
```
cd desktop_app_v2
python -m PyInstaller --noconfirm RGSSA_Catalog.spec
```

构建完成后，成品在：
```
desktop_app_v2\dist\RGSSA Catalog Tool.exe
```

这是**单文件 exe**，目标电脑**不需要装 Python**，直接双击运行。

> 首次构建需要几分钟（PySide6 较大）。最终 exe 约 **79 MB**（单文件）。

> **可能看到的无害报错：** 构建末尾若出现
> `set_exe_build_timestamp ... PermissionError` —— 这是 Windows Defender
> 在扫描刚生成的 exe 时临时锁了文件，**exe 已经完整生成**，不影响使用。
> `build.bat` 已按「exe 是否存在」判断成功，会正常提示 DONE。

## 二、交付给 Ingrid

1. 把 `dist\RGSSA Catalog Tool.exe` 单个文件拷给她（U 盘 / 网盘均可）。
2. 她双击运行，**不需要安装任何东西**。
3. 首次运行 Windows 可能弹 SmartScreen（未签名）——点「更多信息 → 仍要运行」。

## 三、首次使用（Ingrid 操作）

1. **填 API key + Workspace ID**（你提供），点 Save。
2. **选 Region**：
   - 国内用 → **China · Beijing**（默认，最稳）
   - 澳洲生产 → **US · Virginia**（延迟低）
3. **选输入文件夹**（放地图的目录）和输出文件夹。
4. 点 **Start processing**。
5. 处理完进入 **Review**：AI 拿不准的项（INFERRED）会列出来，逐条 确认/修改/删除。
6. Review 完导出，得到 3 个 sheet 的 xlsx（Review Queue / Full Catalog / AI Reasoning）。

## 三、五、代码签名（消除 McAfee / SmartScreen 拦截）

Ingrid 那边出现 McAfee + SmartScreen 拦截，是因为 exe **没有代码签名**。
方案：**Azure Trusted Signing**（云端 HSM，约 $10/月，不用买硬件 U-key）。

### A. 你在 Azure 那边做的一次性设置（我做不了，需要你的身份/付款）

1. 登录 [Azure 门户](https://portal.azure.com)，搜索 **Trusted Signing**，
   创建一个 **Trusted Signing account**（选区域，如 East US / West Europe）。
   - 定价层选 **Basic**（约 $9.99/月，含每月签名额度，足够）。
2. 在账户下创建 **Identity validation**（身份验证）：
   - 机构类型选 **Organization**，填 RGSSA 的法律名称、地址、网站。
   - 微软审核需 **1–7 个工作日**（这是必经步骤，无法跳过）。
   - RGSSA 是有多年历史的注册机构，通常能通过。
3. 审核通过后，创建 **Certificate profile**（证书配置，类型 Public Trust）。
4. 记下三个值（都不是机密）：
   - **Endpoint**：账户所在区域的 URL，如 `https://eus.codesigning.azure.net/`
   - **Account name**：你创建的账户名
   - **Certificate profile name**：证书配置名
5. **授权你的登录身份能签名**：在 Trusted Signing account 的
   「访问控制 (IAM)」里，给你自己的 Azure 账号分配
   **Trusted Signing Certificate Profile Signer** 角色。

### B. 本机配置（我已搭好脚手架，你只填 3 个值）

1. 把 `signing.config.example.bat` 复制为 **`signing.config.bat`**，
   填入上面记的 Endpoint / Account / Profile 三个值。
   （此文件已被 `.gitignore` 忽略，不会进 git。）
2. 装 Azure CLI（一次性）：[下载 az CLI](https://aka.ms/installazurecliwindows)，
   装完在 PowerShell 跑：
   ```
   az login
   ```
   用你那个有签名权限的 Azure 账号登录即可（浏览器弹窗认证，**不用存任何密钥**）。

### C. 签名（每次打包后）

- 跑过 `az login` 后，`build.bat` 末尾会**自动调用签名**（检测到
  `signing.config.bat` 就签）。
- 或单独跑 **`sign.bat`** 给已有的 `dist\RGSSA Catalog Tool.exe` 签名。
- 签完脚本会用 `signtool verify` 自动验证签名有效。

### 效果

- **McAfee**：签名 + 微软时间戳后，文件有可信发布者，启发式误报基本消除。
- **SmartScreen**：签名让 Ingrid 的下载开始**积累发布者信誉**；正规
  Trusted Signing 证书通常很快不再弹「未知发布者」警告（EV 证书才是
  「零等待」，但那要 $300+/年 + 硬件 U-key，对单机部署不划算）。
- 过渡期内若仍偶发拦截，配合下面第六节的本机白名单即可。

### 安全提醒

- `signing.config.bat` 里只有账户名/区域，**不是机密**，但仍被 gitignore。
- 认证用 `az login`（交互式），**不存任何 client secret**。若以后要做
  CI 自动签名，才用服务主体的 `AZURE_*` 环境变量，且绝不写进文件/git。

## 三、六、过渡期：本机临时放行（可选）

签名信誉积累前，若 Ingrid 机器仍偶发拦截：

- **McAfee**：打开 McAfee → 「实时扫描 / 排除项」→ 添加
  `RGSSA Catalog Tool.exe`（或其所在文件夹）为信任项。
- **SmartScreen**：双击若提示「Windows 已保护你的电脑」→ 点
  **「更多信息」→「仍要运行」**（只需一次）。

## 四、重要：安全

- **API key / Workspace 不写在程序里**，由用户在界面填写，保存在本机
  `%APPDATA%\RgssaCatalog\config.json`，不随 exe 分发。
- 交付前请到阿里云控制台**重新生成 key**，把旧 key 作废。
- 原始 400MB TIF **不离开本机**——只有压缩后的缩略图（≤3840px JPEG）发往 API。

## 五、配置/状态文件位置

- 配置：`%APPDATA%\RgssaCatalog\config.json`
- Review 进度（可断点续传）：输出文件夹下 `review_state.json`
- 每张图缓存：输出文件夹下 `per_map_cache\`
